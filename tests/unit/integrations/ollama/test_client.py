# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""
Unit tests for OllamaClient.
"""

import json
import sys
from unittest.mock import MagicMock, patch

import pytest

# Pre-mock the ollama package so the import never touches a real server.
if "ollama" not in sys.modules:
    _mock_ollama_module = MagicMock()
    sys.modules["ollama"] = _mock_ollama_module
    sys.modules["ollama._types"] = MagicMock()

from docpipe.exceptions.docpipe_exceptions import ConfigurationError, DocpipeException
from docpipe.exceptions.error_codes import ErrorCode
from docpipe.integrations.ollama.client import (
    DEFAULT_TOKEN_LIMIT,
    OLLAMA_MODEL_TOKEN_LIMITS,
    InteractionMode,
    OllamaClient,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_client(
    *,
    model_name: str = "granite4",
    mode: InteractionMode = InteractionMode.GENERATE,
    system_prompt: str | None = None,
    validate_model: bool = False,
    max_concurrent_requests: int = 4,
) -> OllamaClient:
    """Build an OllamaClient with model validation disabled by default."""
    return OllamaClient(
        model_name=model_name,
        host="http://localhost:11434",
        mode=mode,
        system_prompt=system_prompt,
        validate_model=validate_model,
        max_concurrent_requests=max_concurrent_requests,
    )


def _make_list_response(model_names: list[str]):
    """Build a mock ollama ListResponse with .models attribute."""
    response = MagicMock()
    response.models = [_model_obj(name) for name in model_names]
    return response


def _model_obj(name: str):
    m = MagicMock()
    m.model = name
    return m


# ---------------------------------------------------------------------------
# InteractionMode
# ---------------------------------------------------------------------------


class TestInteractionMode:
    def test_enum_values(self):
        assert InteractionMode.GENERATE.value == "generate"
        assert InteractionMode.CHAT.value == "chat"
        assert InteractionMode.EMBEDDINGS.value == "embeddings"


# ---------------------------------------------------------------------------
# __init__
# ---------------------------------------------------------------------------


class TestOllamaClientInit:
    def test_defaults_without_validation(self):
        client = _make_client()
        assert client.model_name == "granite4"
        assert client.host == "http://localhost:11434"
        assert client.mode == InteractionMode.GENERATE
        assert client.system_prompt is None
        assert client.timeout is None
        assert client.max_concurrent_requests == 4

    def test_mode_accepts_string(self):
        client = OllamaClient(
            model_name="llama3",
            host="http://localhost:11434",
            mode="chat",
            validate_model=False,
        )
        assert client.mode == InteractionMode.CHAT

    def test_validate_model_called_when_enabled(self):
        with patch.object(OllamaClient, "_validate_model") as mock_validate:
            OllamaClient(
                model_name="llama3",
                host="http://localhost:11434",
                validate_model=True,
            )
            mock_validate.assert_called_once()

    def test_validate_model_skipped_when_disabled(self):
        with patch.object(OllamaClient, "_validate_model") as mock_validate:
            _make_client(validate_model=False)
            mock_validate.assert_not_called()

    def test_host_defaults_to_service_constant_when_none(self):
        from docpipe.core.constants.constants import ServiceConstants

        client = OllamaClient(model_name="granite4", validate_model=False)
        assert client.host == ServiceConstants.DEFAULT_OLLAMA_HOST


# ---------------------------------------------------------------------------
# _validate_model
# ---------------------------------------------------------------------------


class TestValidateModel:
    def _client_skip_validate(self) -> OllamaClient:
        return _make_client(validate_model=False)

    def test_model_found_does_not_raise(self):
        client = self._client_skip_validate()
        mock_response = _make_list_response(["granite4", "llama3"])

        with patch("ollama.Client") as mock_client:
            mock_client.return_value.list.return_value = mock_response
            client._validate_model()  # should not raise

    def test_model_not_found_raises_docpipe_exception(self):
        client = self._client_skip_validate()
        mock_response = _make_list_response(["llama3"])

        with patch("ollama.Client") as mock_client:
            mock_client.return_value.list.return_value = mock_response
            with pytest.raises(DocpipeException) as exc_info:
                client._validate_model()
        assert exc_info.value.error_code == ErrorCode.OLLAMA_MODEL_NOT_FOUND

    @pytest.mark.parametrize("exc", [ConnectionError("refused"), TimeoutError("timed out")])
    def test_network_error_raises_connection_failed(self, exc):
        client = self._client_skip_validate()
        with patch("ollama.Client") as mock_client:
            mock_client.return_value.list.side_effect = exc
            with pytest.raises(DocpipeException) as exc_info:
                client._validate_model()
        assert exc_info.value.error_code == ErrorCode.OLLAMA_CONNECTION_FAILED

    def test_generic_exception_logs_warning_and_continues(self):
        client = self._client_skip_validate()
        with patch("ollama.Client") as mock_client:
            mock_client.return_value.list.side_effect = RuntimeError("unexpected failure")
            client._validate_model()  # should not raise

    def test_dict_response_format_is_handled(self):
        client = self._client_skip_validate()
        model_obj = MagicMock()
        model_obj.model = "granite4"
        dict_response = {"models": [model_obj]}

        with patch("ollama.Client") as mock_client:
            mock_client.return_value.list.return_value = dict_response
            client._validate_model()  # should not raise

    def test_model_with_tag_matches_base(self):
        client = OllamaClient(
            model_name="granite4:latest",
            host="http://localhost:11434",
            validate_model=False,
        )
        mock_response = _make_list_response(["granite4"])

        with patch("ollama.Client") as mock_client:
            mock_client.return_value.list.return_value = mock_response
            client._validate_model()  # should not raise

    def test_empty_model_list_raises(self):
        client = self._client_skip_validate()
        mock_response = _make_list_response([])

        with patch("ollama.Client") as mock_client:
            mock_client.return_value.list.return_value = mock_response
            with pytest.raises(DocpipeException) as exc_info:
                client._validate_model()
        assert exc_info.value.error_code == ErrorCode.OLLAMA_MODEL_NOT_FOUND

    def test_response_with_no_models_attribute(self):
        client = self._client_skip_validate()

        with patch("ollama.Client") as mock_client:
            mock_client.return_value.list.return_value = object()  # no .models, not dict
            with pytest.raises(DocpipeException) as exc_info:
                client._validate_model()
        assert exc_info.value.error_code == ErrorCode.OLLAMA_MODEL_NOT_FOUND


# ---------------------------------------------------------------------------
# run — GENERATE mode
# ---------------------------------------------------------------------------


class TestRunGenerate:
    def _client(self) -> OllamaClient:
        return _make_client(mode=InteractionMode.GENERATE)

    def test_returns_string_from_generate_response_object(self):
        client = self._client()
        mock_response = MagicMock()
        mock_response.response = "hello world"

        with patch("ollama.Client") as mock_client:
            mock_client.return_value.generate.return_value = mock_response
            result = client.run(prompt="test")
        assert result == "hello world"

    def test_returns_string_from_dict_response(self):
        client = self._client()
        with patch("ollama.Client") as mock_client:
            mock_client.return_value.generate.return_value = {"response": "dict answer"}
            result = client.run(prompt="test")
        assert result == "dict answer"

    def test_returns_empty_string_for_unexpected_response_type(self):
        client = self._client()
        with patch("ollama.Client") as mock_client:
            mock_client.return_value.generate.return_value = 42  # unexpected
            result = client.run(prompt="test")
        assert result == ""

    @pytest.mark.parametrize("exc", [ConnectionError("refused"), TimeoutError("timed out")])
    def test_network_error_raises_connection_failed(self, exc):
        client = self._client()
        with patch("ollama.Client") as mock_client:
            mock_client.return_value.generate.side_effect = exc
            with pytest.raises(DocpipeException) as exc_info:
                client.run(prompt="test")
        assert exc_info.value.error_code == ErrorCode.OLLAMA_CONNECTION_FAILED

    def test_value_error_raises_docpipe_exception(self):
        client = self._client()
        with patch("ollama.Client") as mock_client:
            mock_client.return_value.generate.side_effect = ValueError("bad model")
            with pytest.raises(DocpipeException) as exc_info:
                client.run(prompt="test")
        assert exc_info.value.error_code == ErrorCode.OLLAMA_MODEL_NOT_FOUND

    def test_generic_exception_is_reraised(self):
        client = self._client()
        with patch("ollama.Client") as mock_client:
            mock_client.return_value.generate.side_effect = RuntimeError("unexpected failure")
            with pytest.raises(RuntimeError):
                client.run(prompt="test")


# ---------------------------------------------------------------------------
# run — CHAT mode
# ---------------------------------------------------------------------------


class TestRunChat:
    def _client(self, system_prompt: str | None = None) -> OllamaClient:
        return _make_client(mode=InteractionMode.CHAT, system_prompt=system_prompt)

    def test_returns_content_from_chat_response_object(self):
        client = self._client()
        mock_resp = MagicMock(spec=[])
        msg = MagicMock(spec=[])
        msg.content = "chat answer"
        mock_resp.message = msg

        with patch("ollama.Client") as mock_client:
            mock_client.return_value.chat.return_value = mock_resp
            result = client.run(prompt="hello")
        assert result == "chat answer"

    def test_returns_content_from_dict_response(self):
        client = self._client()
        with patch("ollama.Client") as mock_client:
            mock_client.return_value.chat.return_value = {"message": {"content": "dict chat answer"}}
            result = client.run(prompt="hello")
        assert result == "dict chat answer"

    def test_system_prompt_is_included_in_messages(self):
        client = self._client(system_prompt="You are helpful.")
        mock_resp = MagicMock()
        mock_resp.message = MagicMock()
        mock_resp.message.content = "ok"

        with patch("ollama.Client") as mock_client:
            mock_client.return_value.chat.return_value = mock_resp
            client.run(prompt="hello")
            call_kwargs = mock_client.return_value.chat.call_args
            messages = call_kwargs[1]["messages"]

        system_msgs = [m for m in messages if m["role"] == "system"]
        assert len(system_msgs) == 1
        assert system_msgs[0]["content"] == "You are helpful."

    def test_dict_message_content_is_extracted(self):
        client = self._client()
        mock_resp = MagicMock(spec=[])
        mock_resp.message = {"content": "from dict message"}

        with patch("ollama.Client") as mock_client:
            mock_client.return_value.chat.return_value = mock_resp
            result = client.run(prompt="hello")
        assert result == "from dict message"

    def test_fallback_empty_string_for_unexpected_response(self):
        client = self._client()
        mock_resp = MagicMock(spec=[])  # no .message attribute

        with patch("ollama.Client") as mock_client:
            mock_client.return_value.chat.return_value = mock_resp
            result = client.run(prompt="hello")
        assert result == ""


# ---------------------------------------------------------------------------
# _parse_json_response
# ---------------------------------------------------------------------------


class TestParseJsonResponse:
    def _client(self) -> OllamaClient:
        return _make_client()

    def test_returns_none_for_empty_string(self):
        assert self._client()._parse_json_response("") is None

    def test_returns_none_for_whitespace(self):
        assert self._client()._parse_json_response("   ") is None

    def test_direct_json_parse(self):
        result = self._client()._parse_json_response('{"key": "value"}')
        assert result == {"key": "value"}

    def test_json_in_markdown_code_block(self):
        raw = '```json\n{"detections": []}\n```'
        result = self._client()._parse_json_response(raw)
        assert result == {"detections": []}

    def test_json_in_markdown_code_block_without_language_tag(self):
        raw = '```\n{"detections": [1]}\n```'
        result = self._client()._parse_json_response(raw)
        assert result == {"detections": [1]}

    def test_json_embedded_in_text(self):
        raw = 'Here is your answer: {"items": [1, 2, 3]} done.'
        result = self._client()._parse_json_response(raw)
        assert result == {"items": [1, 2, 3]}

    def test_json_array_wrapped_in_detections(self):
        raw = '["foo", "bar"]'
        result = self._client()._parse_json_response(raw)
        assert result == ["foo", "bar"]

    def test_returns_none_for_plain_text(self):
        result = self._client()._parse_json_response("This is just plain text with no JSON.")
        assert result is None


# ---------------------------------------------------------------------------
# run_json
# ---------------------------------------------------------------------------


class TestRunJson:
    def _client(self) -> OllamaClient:
        return _make_client()

    def test_returns_parsed_dict_on_first_attempt(self):
        client = self._client()
        with patch.object(client, "run", return_value='{"detections": []}'):
            result = client.run_json(prompt="detect entities")
        assert result == {"detections": []}

    def test_retries_and_succeeds_on_second_attempt(self):
        client = self._client()
        calls = iter(["not json", '{"ok": true}'])
        with patch.object(client, "run", side_effect=calls):
            result = client.run_json(prompt="test", retries=2)
        assert result == {"ok": True}

    def test_raises_json_decode_error_after_all_retries(self):
        client = self._client()
        with patch.object(client, "run", return_value="still not json"):
            with pytest.raises(json.JSONDecodeError):
                client.run_json(prompt="test", retries=3)

    def test_emphasis_added_after_first_failure(self):
        client = self._client()
        prompts_seen: list[str] = []

        def capture_run(*, prompt: str) -> str:
            prompts_seen.append(prompt)
            return "not json"

        with patch.object(client, "run", side_effect=capture_run):
            with pytest.raises(json.JSONDecodeError):
                client.run_json(prompt="base prompt", retries=3)

        # After first failure, subsequent prompts should contain the emphasis
        assert "IMPORTANT" in prompts_seen[1]
        # Emphasis is added only once
        assert prompts_seen[1] == prompts_seen[2]


# ---------------------------------------------------------------------------
# generate_embeddings
# ---------------------------------------------------------------------------


class TestGenerateEmbeddings:
    def _client(self) -> OllamaClient:
        return _make_client()

    def test_returns_embedding_from_response_object(self):
        client = self._client()
        mock_resp = MagicMock(spec=[])
        mock_resp.embedding = [0.1, 0.2, 0.3]

        with patch("ollama.Client") as mock_client:
            mock_client.return_value.embeddings.return_value = mock_resp
            result = client.generate_embeddings("hello")
        assert result == [0.1, 0.2, 0.3]

    def test_returns_embedding_from_dict_response(self):
        client = self._client()
        with patch("ollama.Client") as mock_client:
            mock_client.return_value.embeddings.return_value = {"embedding": [0.4, 0.5]}
            result = client.generate_embeddings("hello")
        assert result == [0.4, 0.5]

    @pytest.mark.parametrize("bad_input", ["", None])
    def test_raises_configuration_error_for_invalid_text(self, bad_input):
        client = self._client()
        with pytest.raises(ConfigurationError):
            client.generate_embeddings(bad_input)  # type: ignore[arg-type]

    def test_raises_docpipe_exception_for_unexpected_response_type(self):
        client = self._client()
        with patch("ollama.Client") as mock_client:
            mock_client.return_value.embeddings.return_value = 42  # unexpected
            with pytest.raises(DocpipeException) as exc_info:
                client.generate_embeddings("text")
        assert exc_info.value.error_code == ErrorCode.EXTERNAL_SERVICE_ERROR

    def test_raises_docpipe_exception_for_empty_embedding(self):
        client = self._client()
        with patch("ollama.Client") as mock_client:
            mock_client.return_value.embeddings.return_value = {"embedding": []}
            with pytest.raises(DocpipeException) as exc_info:
                client.generate_embeddings("text")
        assert exc_info.value.error_code == ErrorCode.EXTERNAL_SERVICE_ERROR

    def test_connection_error_raises_docpipe_exception(self):
        client = self._client()
        with patch("ollama.Client") as mock_client:
            mock_client.return_value.embeddings.side_effect = ConnectionError("refused")
            with pytest.raises(DocpipeException) as exc_info:
                client.generate_embeddings("text")
        assert exc_info.value.error_code == ErrorCode.OLLAMA_CONNECTION_FAILED

    def test_value_error_raises_docpipe_exception(self):
        client = self._client()
        with patch("ollama.Client") as mock_client:
            mock_client.return_value.embeddings.side_effect = ValueError("bad")
            with pytest.raises(DocpipeException) as exc_info:
                client.generate_embeddings("text")
        assert exc_info.value.error_code == ErrorCode.EXTERNAL_SERVICE_ERROR

    def test_unexpected_exception_wrapped_in_docpipe_exception(self):
        client = self._client()
        with patch("ollama.Client") as mock_client:
            mock_client.return_value.embeddings.side_effect = RuntimeError("unexpected failure")
            with pytest.raises(DocpipeException) as exc_info:
                client.generate_embeddings("text")
        assert exc_info.value.error_code == ErrorCode.EXTERNAL_SERVICE_ERROR


# ---------------------------------------------------------------------------
# _generate_single_embedding
# ---------------------------------------------------------------------------


class TestGenerateSingleEmbedding:
    def _client(self) -> OllamaClient:
        return _make_client()

    def test_returns_index_and_embedding_from_response_object(self):
        client = self._client()
        mock_resp = MagicMock(spec=[])
        mock_resp.embedding = [1.0, 2.0]
        mock_client = MagicMock()
        mock_client.embeddings.return_value = mock_resp

        idx, emb = client._generate_single_embedding(client=mock_client, index=3, text="hi")
        assert idx == 3
        assert emb == [1.0, 2.0]

    def test_returns_index_and_embedding_from_dict(self):
        client = self._client()
        mock_client = MagicMock()
        mock_client.embeddings.return_value = {"embedding": [0.9]}

        idx, emb = client._generate_single_embedding(client=mock_client, index=0, text="hi")
        assert idx == 0
        assert emb == [0.9]

    def test_raises_for_unexpected_response_type(self):
        client = self._client()
        mock_client = MagicMock()
        mock_client.embeddings.return_value = "string response"

        with pytest.raises(DocpipeException) as exc_info:
            client._generate_single_embedding(client=mock_client, index=0, text="hi")
        assert exc_info.value.error_code == ErrorCode.EXTERNAL_SERVICE_ERROR

    def test_raises_for_empty_embedding(self):
        client = self._client()
        mock_client = MagicMock()
        mock_client.embeddings.return_value = {"embedding": []}

        with pytest.raises(DocpipeException) as exc_info:
            client._generate_single_embedding(client=mock_client, index=0, text="hi")
        assert exc_info.value.error_code == ErrorCode.EXTERNAL_SERVICE_ERROR


# ---------------------------------------------------------------------------
# generate_embeddings_batch
# ---------------------------------------------------------------------------


class TestGenerateEmbeddingsBatch:
    def _client(self) -> OllamaClient:
        return _make_client()

    def test_returns_list_of_embeddings(self):
        client = self._client()
        embeddings = [[0.1, 0.2], [0.3, 0.4]]

        def fake_single(*, client, index, text):
            return index, embeddings[index]

        with patch("ollama.Client"):
            with patch.object(client, "_generate_single_embedding", side_effect=fake_single):
                result = client.generate_embeddings_batch(["text0", "text1"])

        assert result == embeddings

    def test_raises_configuration_error_for_empty_list(self):
        client = self._client()
        with pytest.raises(ConfigurationError):
            client.generate_embeddings_batch([])

    def test_raises_configuration_error_for_non_list(self):
        client = self._client()
        with pytest.raises(ConfigurationError):
            client.generate_embeddings_batch("not a list")  # type: ignore[arg-type]

    def test_raises_configuration_error_for_empty_strings_in_list(self):
        client = self._client()
        with pytest.raises(ConfigurationError):
            client.generate_embeddings_batch(["valid", ""])

    def test_connection_error_from_client_construction_propagates(self):
        client = self._client()
        import sys

        mock_ollama = sys.modules["ollama"]
        original_client = mock_ollama.Client  # type: ignore[attr-defined]
        try:
            mock_ollama.Client = MagicMock(side_effect=ConnectionError("refused"))  # type: ignore[attr-defined]
            with pytest.raises(ConnectionError):
                client.generate_embeddings_batch(["text"])
        finally:
            mock_ollama.Client = original_client  # type: ignore[attr-defined]

    def test_docpipe_exception_from_worker_is_reraised(self):
        client = self._client()

        def fail_single(*, client, index, text):
            raise DocpipeException("embedding failed", error_code=ErrorCode.EXTERNAL_SERVICE_ERROR)

        with patch("ollama.Client"):
            with patch.object(client, "_generate_single_embedding", side_effect=fail_single):
                with pytest.raises(DocpipeException) as exc_info:
                    client.generate_embeddings_batch(["text"])
        assert exc_info.value.error_code == ErrorCode.EXTERNAL_SERVICE_ERROR


# ---------------------------------------------------------------------------
# is_installed
# ---------------------------------------------------------------------------


class TestIsInstalled:
    def test_returns_true_when_ollama_in_path_and_version_exits_zero(self):
        with patch("shutil.which", return_value="/usr/bin/ollama"):
            mock_result = MagicMock()
            mock_result.returncode = 0
            with patch("subprocess.run", return_value=mock_result):
                assert OllamaClient.is_installed() is True

    def test_returns_false_when_ollama_not_in_path(self):
        with patch("shutil.which", return_value=None):
            assert OllamaClient.is_installed() is False

    def test_returns_false_when_version_command_returns_nonzero(self):
        with patch("shutil.which", return_value="/usr/bin/ollama"):
            mock_result = MagicMock()
            mock_result.returncode = 1
            with patch("subprocess.run", return_value=mock_result):
                assert OllamaClient.is_installed() is False

    def test_returns_false_on_subprocess_exception(self):
        with patch("shutil.which", return_value="/usr/bin/ollama"):
            with patch("subprocess.run", side_effect=Exception("error")):
                assert OllamaClient.is_installed() is False


# ---------------------------------------------------------------------------
# is_server_running
# ---------------------------------------------------------------------------


class TestIsServerRunning:
    def test_returns_true_when_list_succeeds(self):
        with patch("ollama.Client") as mock_client:
            mock_client.return_value.list.return_value = MagicMock()
            assert OllamaClient.is_server_running() is True

    def test_returns_false_when_exception_raised(self):
        with patch("ollama.Client") as mock_client:
            mock_client.return_value.list.side_effect = ConnectionError("refused")
            assert OllamaClient.is_server_running() is False

    def test_uses_provided_host(self):
        with patch("ollama.Client") as mock_client:
            mock_client.return_value.list.return_value = MagicMock()
            OllamaClient.is_server_running(host="http://custom:11434")
            mock_client.assert_called_once_with(host="http://custom:11434", trust_env=False)

    def test_uses_default_host_when_none(self):
        from docpipe.core.constants.constants import ServiceConstants

        with patch("ollama.Client") as mock_client:
            mock_client.return_value.list.return_value = MagicMock()
            OllamaClient.is_server_running(host=None)
            mock_client.assert_called_once_with(host=ServiceConstants.DEFAULT_OLLAMA_HOST, trust_env=False)


# ---------------------------------------------------------------------------
# is_model_available
# ---------------------------------------------------------------------------


class TestIsModelAvailable:
    def test_returns_true_when_model_in_list_as_object(self):
        mock_model = MagicMock()
        mock_model.model = "llama3"
        mock_models_resp = MagicMock()
        mock_models_resp.models = [mock_model]

        with patch("ollama.Client") as mock_client:
            mock_client.return_value.list.return_value = mock_models_resp
            assert OllamaClient.is_model_available("llama3") is True

    def test_returns_true_when_model_in_list_as_dict(self):
        with patch("ollama.Client") as mock_client:
            mock_client.return_value.list.return_value = {"models": [{"name": "llama3"}]}
            # dict format: uses "name" key
            assert OllamaClient.is_model_available("llama3") is True

    def test_returns_false_when_model_not_in_list(self):
        mock_model = MagicMock()
        mock_model.model = "llama2"
        mock_models_resp = MagicMock()
        mock_models_resp.models = [mock_model]

        with patch("ollama.Client") as mock_client:
            mock_client.return_value.list.return_value = mock_models_resp
            assert OllamaClient.is_model_available("granite4") is False

    def test_returns_false_on_exception(self):
        with patch("ollama.Client") as mock_client:
            mock_client.return_value.list.side_effect = Exception("error")
            assert OllamaClient.is_model_available("llama3") is False

    @pytest.mark.parametrize(
        ("server_name", "query_name"),
        [
            ("llama3:latest", "llama3"),
            ("llama3.2:latest", "llama3.2"),
            ("granite4:latest", "granite4"),
        ],
    )
    def test_returns_true_for_versioned_model_tag(self, server_name, query_name):
        mock_model = MagicMock()
        mock_model.model = server_name
        mock_models_resp = MagicMock()
        mock_models_resp.models = [mock_model]

        with patch("ollama.Client") as mock_client:
            mock_client.return_value.list.return_value = mock_models_resp
            assert OllamaClient.is_model_available(query_name) is True


# ---------------------------------------------------------------------------
# get_model_token_limit
# ---------------------------------------------------------------------------


class TestGetModelTokenLimit:
    def test_known_model_returns_correct_limit(self):
        assert OllamaClient.get_model_token_limit("llama3") == 8192
        assert OllamaClient.get_model_token_limit("granite4") == 131072

    def test_unknown_model_returns_default(self):
        assert OllamaClient.get_model_token_limit("unknown-model") == DEFAULT_TOKEN_LIMIT

    def test_model_with_tag_uses_base_name(self):
        # "llama3:latest" → base "llama3" → 8192
        assert OllamaClient.get_model_token_limit("llama3:latest") == 8192

    def test_all_known_models_have_entries(self):
        for model_name, expected_limit in OLLAMA_MODEL_TOKEN_LIMITS.items():
            if ":" not in model_name:
                assert OllamaClient.get_model_token_limit(model_name) == expected_limit


# ---------------------------------------------------------------------------
# get_embedding_dimension
# ---------------------------------------------------------------------------


class TestGetEmbeddingDimension:
    def test_always_returns_zero(self):
        assert OllamaClient.get_embedding_dimension("granite4") == 0
        assert OllamaClient.get_embedding_dimension("llama3") == 0
        assert OllamaClient.get_embedding_dimension("unknown") == 0


# ---------------------------------------------------------------------------
# generate (delegates to run)
# ---------------------------------------------------------------------------


class TestGenerate:
    def test_delegates_to_run(self):
        client = _make_client()
        with patch.object(client, "run", return_value="generated text") as mock_run:
            result = client.generate("my prompt")
        mock_run.assert_called_once_with(prompt="my prompt")
        assert result == "generated text"


# ---------------------------------------------------------------------------
# chat method
# ---------------------------------------------------------------------------


class TestChatMethod:
    def test_switches_mode_to_chat_and_restores(self):
        client = _make_client(mode=InteractionMode.GENERATE)

        with patch.object(client, "run", return_value="chat reply"):
            result = client.chat([{"role": "user", "content": "hello"}])

        assert result == "chat reply"
        # Mode should be restored after the call
        assert client.mode == InteractionMode.GENERATE

    def test_system_messages_are_skipped(self):
        client = _make_client()
        captured_prompts: list[str] = []

        def capture_run(*, prompt: str) -> str:
            captured_prompts.append(prompt)
            return "ok"

        with patch.object(client, "run", side_effect=capture_run):
            client.chat(
                [
                    {"role": "system", "content": "be helpful"},
                    {"role": "user", "content": "tell me something"},
                ]
            )

        assert captured_prompts[0] == "tell me something"

    def test_multiple_user_messages_joined(self):
        client = _make_client()
        captured_prompts: list[str] = []

        def capture_run(*, prompt: str) -> str:
            captured_prompts.append(prompt)
            return "ok"

        with patch.object(client, "run", side_effect=capture_run):
            client.chat(
                [
                    {"role": "user", "content": "part1"},
                    {"role": "user", "content": "part2"},
                ]
            )

        assert captured_prompts[0] == "part1\npart2"

    def test_mode_restored_even_on_exception(self):
        client = _make_client(mode=InteractionMode.GENERATE)

        with patch.object(client, "run", side_effect=RuntimeError("unexpected failure")):
            with pytest.raises(RuntimeError):
                client.chat([{"role": "user", "content": "hi"}])

        assert client.mode == InteractionMode.GENERATE


# ---------------------------------------------------------------------------
# _ensure_server_running
# ---------------------------------------------------------------------------


class TestEnsureServerRunning:
    def test_returns_true_when_server_already_running(self):
        with patch.object(OllamaClient, "is_server_running", return_value=True):
            ok, msg = OllamaClient._ensure_server_running(auto_start=False)
        assert ok is True
        assert msg == ""

    def test_returns_false_when_not_running_and_auto_start_disabled(self):
        with patch.object(OllamaClient, "is_server_running", return_value=False):
            ok, msg = OllamaClient._ensure_server_running(auto_start=False)
        assert ok is False
        assert "not running" in msg

    def test_auto_starts_server_when_not_running(self):
        with patch.object(OllamaClient, "is_server_running", return_value=False):
            with patch.object(OllamaClient, "start_server", return_value=True):
                ok, msg = OllamaClient._ensure_server_running(auto_start=True)
        assert ok is True
        assert msg == ""

    def test_returns_false_when_auto_start_fails(self):
        with patch.object(OllamaClient, "is_server_running", return_value=False):
            with patch.object(OllamaClient, "start_server", return_value=False):
                ok, msg = OllamaClient._ensure_server_running(auto_start=True)
        assert ok is False
        assert "Failed" in msg


# ---------------------------------------------------------------------------
# _ensure_model_available
# ---------------------------------------------------------------------------


class TestEnsureModelAvailable:
    def test_returns_true_when_model_already_available(self):
        with patch.object(OllamaClient, "is_model_available", return_value=True):
            ok, _msg = OllamaClient._ensure_model_available("llama3", auto_pull=False)
        assert ok is True

    def test_returns_false_when_model_unavailable_and_auto_pull_disabled(self):
        with patch.object(OllamaClient, "is_model_available", return_value=False):
            ok, msg = OllamaClient._ensure_model_available("llama3", auto_pull=False)
        assert ok is False
        assert "llama3" in msg

    def test_auto_pulls_when_model_unavailable(self):
        with patch.object(OllamaClient, "is_model_available", return_value=False):
            with patch.object(OllamaClient, "pull_model", return_value=True):
                ok, _msg = OllamaClient._ensure_model_available("llama3", auto_pull=True)
        assert ok is True

    def test_returns_false_when_auto_pull_fails(self):
        with patch.object(OllamaClient, "is_model_available", return_value=False):
            with patch.object(OllamaClient, "pull_model", return_value=False):
                ok, msg = OllamaClient._ensure_model_available("llama3", auto_pull=True)
        assert ok is False
        assert "Failed" in msg


# ---------------------------------------------------------------------------
# ensure_ready
# ---------------------------------------------------------------------------


class TestEnsureReady:
    def test_returns_false_when_not_installed(self):
        with patch.object(OllamaClient, "is_installed", return_value=False):
            ok, msg = OllamaClient.ensure_ready("llama3")
        assert ok is False
        assert "not installed" in msg.lower()

    def test_returns_false_when_server_not_ready(self):
        with patch.object(OllamaClient, "is_installed", return_value=True):
            with patch.object(OllamaClient, "_ensure_server_running", return_value=(False, "server error")):
                ok, msg = OllamaClient.ensure_ready("llama3", auto_start=False)
        assert ok is False
        assert msg == "server error"

    def test_returns_false_when_model_not_available(self):
        with patch.object(OllamaClient, "is_installed", return_value=True):
            with patch.object(OllamaClient, "_ensure_server_running", return_value=(True, "")):
                with patch.object(OllamaClient, "_ensure_model_available", return_value=(False, "model error")):
                    ok, msg = OllamaClient.ensure_ready("llama3", auto_pull=False)
        assert ok is False
        assert msg == "model error"

    def test_returns_true_when_everything_ready(self):
        with patch.object(OllamaClient, "is_installed", return_value=True):
            with patch.object(OllamaClient, "_ensure_server_running", return_value=(True, "")):
                with patch.object(OllamaClient, "_ensure_model_available", return_value=(True, "")):
                    ok, msg = OllamaClient.ensure_ready("llama3")
        assert ok is True
        assert "llama3" in msg

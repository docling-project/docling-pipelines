# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Unit tests for sanitize_exception and its catch sites."""

import socket
import ssl
from typing import Self
from unittest.mock import MagicMock, patch

import pytest
import requests
from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator
from pydantic_core import PydanticCustomError

from docpipe.core.operators.ingest.adapters.outbound.sources.s3.config import S3SourceConfig
from docpipe.core.operators.ingest.ingest_source import IngestSourceOperator
from docpipe.exceptions.docpipe_exceptions import DocpipeException
from docpipe.utils.infrastructure.exception_sanitizer import (
    CATEGORY_CONNECTION,
    CATEGORY_DATABASE,
    CATEGORY_HTTP,
    CATEGORY_TIMEOUT,
    CATEGORY_TLS,
    CATEGORY_VALIDATION,
    format_pydantic_errors,
    sanitize_exception,
)

CANARY = "CANARY-7c1e9b52-secret"
KEY = "ingest_source.provider_config"


class _Model(BaseModel):
    password: str
    port: int


class _Item(BaseModel):
    val: int


class _Nested(BaseModel):
    items: list[_Item]


class _Bounded(BaseModel):
    count: int = Field(gt=0)


class _Named(BaseModel):
    name: str

    @field_validator("name")
    @classmethod
    def check_name(cls, value: str) -> str:
        if not value.startswith("ok"):
            raise ValueError("name must start with ok")
        return value


class _Paired(BaseModel):
    low: int
    high: int

    @model_validator(mode="after")
    def check_order(self) -> Self:
        if self.low > self.high:
            raise ValueError("low must not exceed high")
        return self


def _validation_error(*, value: object) -> ValidationError:
    with pytest.raises(ValidationError) as info:
        _Model(password="x", port=value)  # type: ignore[arg-type]
    return info.value


class TestValidationError:
    def test_input_value_is_not_rendered(self):
        exc = _validation_error(value=CANARY)

        assert CANARY in str(exc)  # Pydantic echoes the input; this is the leak being closed.
        text = sanitize_exception(exc=exc, config_key=KEY)

        assert CANARY not in text
        assert "input_value" not in text
        assert "errors.pydantic.dev" not in text
        assert f"{KEY}.port" in text
        assert CATEGORY_VALIDATION in text

    def test_s3_endpoint_url_without_scheme(self):
        with pytest.raises(ValidationError) as info:
            S3SourceConfig(
                access_key="ak",
                secret_key=CANARY,
                bucket="bucket",
                endpoint_url=f"{CANARY}.example.com",
            )

        assert CANARY in str(info.value)
        text = sanitize_exception(exc=info.value, config_key=KEY)

        assert CANARY not in text
        assert f"{KEY}.endpoint_url" in text
        assert "endpoint_url must start with http:// or https://" in text

    def test_wrapped_validation_error_is_rendered_from_the_chain(self):
        inner = _validation_error(value=CANARY)
        try:
            raise ValueError(f"wrapper: {inner}") from inner
        except ValueError as wrapper:
            text = sanitize_exception(exc=wrapper, config_key=KEY)

        assert CANARY not in text
        assert CATEGORY_VALIDATION in text
        assert text.count(KEY + ": ") == 1


class TestFormatPydanticErrors:
    @staticmethod
    def _rejected(*, model: type[BaseModel], data: dict[str, object]) -> ValidationError:
        with pytest.raises(ValidationError) as info:
            model.model_validate(data)
        return info.value

    def test_missing_field_is_not_provided(self):
        exc = self._rejected(model=_Model, data={"port": 1})

        assert format_pydantic_errors(exc=exc) == ["password is not provided"]
        assert format_pydantic_errors(exc=exc, prefix=KEY) == [f"{KEY}.password is not provided"]

    def test_nested_field_and_list_index(self):
        missing = self._rejected(model=_Nested, data={"items": [{"val": 1}, {}]})
        mistyped = self._rejected(model=_Nested, data={"items": [{"val": "x"}]})

        assert format_pydantic_errors(exc=missing, prefix=KEY) == [f"{KEY}.items[1].val is not provided"]
        assert format_pydantic_errors(exc=mistyped) == [
            "items[0].val: Input should be a valid integer, unable to parse string as an integer"
        ]

    def test_built_in_constraint_and_type_errors(self):
        constraint = self._rejected(model=_Bounded, data={"count": 0})
        wrong_type = self._rejected(model=_Model, data={"password": 1, "port": 1})

        assert format_pydantic_errors(exc=constraint) == ["count: Input should be greater than 0"]
        assert format_pydantic_errors(exc=wrong_type) == ["password: Input should be a valid string"]

    def test_field_level_value_error_is_normalized(self):
        exc = self._rejected(model=_Named, data={"name": "bad"})

        assert format_pydantic_errors(exc=exc, prefix=KEY) == [f"{KEY}.name: Value error: name must start with ok"]

    def test_model_level_value_error_has_no_path(self):
        exc = self._rejected(model=_Paired, data={"low": 2, "high": 1})

        assert format_pydantic_errors(exc=exc) == ["Value error: low must not exceed high"]
        assert format_pydantic_errors(exc=exc, prefix=KEY) == [f"{KEY}: Value error: low must not exceed high"]

    def test_value_error_prefix_is_normalized_only_for_value_error_type(self):
        exc = ValidationError.from_exception_data(
            title="_Model",
            line_errors=[
                {"type": PydanticCustomError("value_error", "Value error, boom"), "loc": ("port",), "input": 0},
                {"type": PydanticCustomError("value_error", "boom"), "loc": ("password",), "input": 0},
                {"type": PydanticCustomError("custom_code", "Value error, boom"), "loc": ("name",), "input": 0},
            ],
        )

        assert format_pydantic_errors(exc=exc) == [
            "port: Value error: boom",
            "password: boom",
            "name: Value error, boom",
        ]

    def test_message_that_repeats_the_field_name_is_not_deduplicated(self):
        exc = ValidationError.from_exception_data(
            title="_Model",
            line_errors=[
                {"type": PydanticCustomError("custom_code", "port must be positive"), "loc": ("port",), "input": -1},
            ],
        )

        assert format_pydantic_errors(exc=exc) == ["port: port must be positive"]

    def test_rejected_input_and_context_never_appear(self):
        custom = ValidationError.from_exception_data(
            title="_Model",
            line_errors=[
                {
                    "type": PydanticCustomError("custom_code", "static message", {"secret": CANARY, "error": CANARY}),
                    "loc": ("password",),
                    "input": CANARY,
                },
            ],
        )
        native = _validation_error(value=CANARY)

        messages = format_pydantic_errors(exc=custom, prefix=KEY) + format_pydantic_errors(exc=native, prefix=KEY)

        assert messages == [
            f"{KEY}.password: static message",
            f"{KEY}.port: Input should be a valid integer, unable to parse string as an integer",
        ]
        assert CANARY not in "\n".join(messages)

    def test_sanitizer_envelope_uses_the_formatter_wording(self):
        exc = self._rejected(model=_Model, data={"port": 1})

        assert sanitize_exception(exc=exc, config_key=KEY) == (
            f"{KEY}: {CATEGORY_VALIDATION} ({KEY}.password is not provided)"
        )


class TestWrapperMessageIsKept:
    """A wrapper with its own actionable text keeps it; only the wrapped third-party text is replaced."""

    @staticmethod
    def _docpipe_exception(*, message: str, cause: BaseException) -> DocpipeException:
        try:
            raise DocpipeException(message=message, status_code=400) from cause
        except DocpipeException as wrapper:
            return wrapper

    def test_duckdb_wrapper_keeps_the_hint(self):
        import duckdb

        with pytest.raises(duckdb.Error) as info:
            duckdb.connect().execute(f"select '{CANARY}' > 1")
        hint = "Filter condition is invalid due to mismatched data types. Please review the filter expression."
        wrapper = self._docpipe_exception(message=f"{hint} {info.value}", cause=info.value)

        text = sanitize_exception(exc=wrapper, config_key="sql_filter_node")

        assert hint in text
        assert CANARY not in text
        assert str(info.value) not in text
        assert text.endswith(CATEGORY_DATABASE)

    def test_fixed_text_wrapper_around_a_cause_is_unchanged(self):
        cause = requests.exceptions.ConnectionError(f"https://u:{CANARY}@host")
        wrapper = self._docpipe_exception(message="Could not reach the embeddings service.", cause=cause)

        assert sanitize_exception(exc=wrapper, config_key=KEY) == f"{KEY}: Could not reach the embeddings service."

    def test_wrapper_around_a_validation_error_keeps_hint_and_drops_input(self):
        inner = _validation_error(value=CANARY)
        wrapper = self._docpipe_exception(message=f"Invalid operator configuration. {inner}", cause=inner)

        text = sanitize_exception(exc=wrapper, config_key=KEY)

        assert text.startswith(f"{KEY}: Invalid operator configuration. {CATEGORY_VALIDATION} (")
        assert CANARY not in text
        assert f"{KEY}.port" in text

    def test_wrapper_around_a_requests_error_keeps_hint(self):
        cause = requests.exceptions.ConnectionError(f"https://u:{CANARY}@host")
        wrapper = self._docpipe_exception(message=f"Embedding call failed: {cause}", cause=cause)

        assert sanitize_exception(exc=wrapper, config_key=KEY) == f"{KEY}: Embedding call failed: {CATEGORY_CONNECTION}"

    def test_message_equal_to_the_cause_text_becomes_the_category(self):
        cause = requests.exceptions.ConnectionError(f"https://u:{CANARY}@host")
        wrapper = self._docpipe_exception(message=str(cause), cause=cause)

        assert sanitize_exception(exc=wrapper, config_key=KEY) == f"{KEY}: {CATEGORY_CONNECTION}"

    def test_truncated_copy_of_the_cause_falls_back_to_the_category(self):
        cause = requests.exceptions.ConnectionError(f"https://user:{CANARY}@host/path")
        wrapper = self._docpipe_exception(message=f"Failed: {str(cause)[:-8]}", cause=cause)

        text = sanitize_exception(exc=wrapper, config_key=KEY)

        assert CANARY not in text
        assert text == f"{KEY}: {CATEGORY_CONNECTION}"

    def test_repr_of_the_cause_is_redacted_in_place(self):
        cause = requests.exceptions.ConnectionError(f"https://user:{CANARY}@host/path")
        wrapper = self._docpipe_exception(message=f"Failed: {cause!r}", cause=cause)

        text = sanitize_exception(exc=wrapper, config_key=KEY)

        assert CANARY not in text
        assert text.startswith(f"{KEY}: Failed: ")

    def test_escaped_copy_of_the_cause_falls_back_to_the_category(self):
        cause = requests.exceptions.ConnectionError(f"""it's "quoted" {CANARY} @host""")
        wrapper = self._docpipe_exception(message=f"Failed: {cause!r}", cause=cause)
        assert str(cause) not in str(wrapper)  # repr escaped the quote, so verbatim replacement cannot work

        text = sanitize_exception(exc=wrapper, config_key=KEY)

        assert CANARY not in text
        assert text == f"{KEY}: {CATEGORY_CONNECTION}"

    def test_wrapper_without_a_secret_in_the_cause_text(self):
        cause = requests.exceptions.ConnectionError("boom")
        wrapper = self._docpipe_exception(message="Step failed.", cause=cause)

        assert sanitize_exception(exc=wrapper, config_key=KEY) == f"{KEY}: Step failed."

    def test_node_failure_message_keeps_the_hint(self):
        from docpipe.core.job_management.adapters.services.job_tracker_service import JobTrackerService

        cause = requests.exceptions.ConnectionError(f"https://u:{CANARY}@h")
        wrapper = self._docpipe_exception(message=f"Search backend unreachable: {cause}", cause=cause)
        service = JobTrackerService.__new__(JobTrackerService)
        store = MagicMock()
        store.get_node_stats_by_batch_and_node.return_value = None
        service.job_stats_store = store

        service.fail_node_execution(job_run_id="r", node_id="n", node_name="vectordb_node", exception=wrapper)

        stored = str(store.mock_calls)
        assert "Search backend unreachable" in stored
        assert CANARY not in stored


class TestCategories:
    def test_http_connection_error_with_canary(self):
        exc = requests.exceptions.ConnectionError(f"HTTPSConnectionPool(host='https://user:{CANARY}@h', port=443)")

        text = sanitize_exception(exc=exc, config_key=KEY)

        assert text == f"{KEY}: {CATEGORY_CONNECTION}"
        assert CANARY not in text

    def test_timeout(self):
        text = sanitize_exception(exc=requests.exceptions.ReadTimeout(CANARY), config_key=KEY)

        assert text == f"{KEY}: {CATEGORY_TIMEOUT}"

    def test_tls(self):
        text = sanitize_exception(exc=ssl.SSLError(CANARY), config_key=KEY)

        assert text == f"{KEY}: {CATEGORY_TLS}"

    def test_generic_http_error(self):
        text = sanitize_exception(
            exc=requests.exceptions.HTTPError(f"401 for url: https://h/?token={CANARY}"), config_key=KEY
        )

        assert text == f"{KEY}: {CATEGORY_HTTP}"

    def test_dns_failure(self):
        text = sanitize_exception(exc=socket.gaierror(f"{CANARY}.internal"), config_key=KEY)

        assert text == f"{KEY}: {CATEGORY_CONNECTION}"

    def test_botocore_client_error(self):
        from botocore.exceptions import EndpointConnectionError

        text = sanitize_exception(exc=EndpointConnectionError(endpoint_url=f"https://{CANARY}.example"), config_key=KEY)

        assert CANARY not in text
        assert text.startswith(f"{KEY}: ")

    def test_database_error(self):
        import sqlalchemy.exc

        exc = sqlalchemy.exc.OperationalError("SELECT 1", {}, Exception(f"postgresql://u:{CANARY}@h/db"))

        text = sanitize_exception(exc=exc, config_key=KEY)

        assert CANARY not in text
        assert text == f"{KEY}: database error"

    def test_wrapper_hides_a_canary_cause(self):
        try:
            try:
                raise requests.exceptions.ConnectionError(f"https://u:{CANARY}@host")
            except requests.exceptions.ConnectionError as inner:
                msg = f"Failed to fetch documents: {inner!s}"
                raise ValueError(msg) from inner
        except ValueError as wrapper:
            text = sanitize_exception(exc=wrapper, config_key=KEY)

        assert CANARY not in text
        assert text == f"{KEY}: Failed to fetch documents: {CATEGORY_CONNECTION}"

    def test_unknown_exception_keeps_its_message(self):
        assert sanitize_exception(exc=ValueError("bad range"), config_key=KEY) == "bad range"

    def test_empty_message_falls_back_to_class_name(self):
        assert sanitize_exception(exc=RuntimeError(), config_key=KEY) == "RuntimeError"

    def test_cyclic_chain_terminates(self):
        a = RuntimeError("a")
        b = RuntimeError("b")
        a.__cause__ = b
        b.__cause__ = a

        assert sanitize_exception(exc=a, config_key=KEY) == "a"


class TestIngestCatchSites:
    @staticmethod
    def _s3_operator() -> IngestSourceOperator:
        return IngestSourceOperator(
            {
                "provider": "s3",
                "provider_config": {
                    "access_key": "ak",
                    "secret_key": CANARY,
                    "bucket": "b",
                    "endpoint_url": f"{CANARY}.example.com",
                },
            }
        )

    def test_validate_does_not_echo_endpoint_url(self):
        operator = self._s3_operator()
        errors: list[str] = []

        operator.validate(errors=errors, warnings=[], available_features=[])

        assert errors
        assert CANARY not in " ".join(errors)
        assert "endpoint_url" in errors[0]
        assert CATEGORY_VALIDATION in errors[0]

    def test_process_documents_failure_reason_and_log(self, caplog):
        operator = self._s3_operator()
        metadata = operator.create_base_metadata(total_docs_count=0)

        with caplog.at_level("DEBUG"):
            operator.process_documents(metadata)

        assert metadata["failed_docs_count"] == 1
        assert CANARY not in str(metadata["failed_docs"])
        assert CANARY not in caplog.text

    def test_loader_connection_error_with_canary(self, caplog):
        operator = IngestSourceOperator({"provider": "custom", "provider_config": {"loader_class_path": "pkg.Loader"}})
        metadata = operator.create_base_metadata(total_docs_count=0)
        error = requests.exceptions.ConnectionError(f"https://user:{CANARY}@host")

        with patch.object(operator, "_get_loader", side_effect=error), caplog.at_level("DEBUG"):
            operator.process_documents(metadata)

        assert CANARY not in str(metadata["failed_docs"])
        assert CANARY not in caplog.text
        assert CATEGORY_CONNECTION in metadata["failed_docs"][0]["reason"]

    def test_process_document_failure_reason(self, caplog):
        operator = IngestSourceOperator({"provider": "custom", "provider_config": {"loader_class_path": "pkg.Loader"}})
        metadata = operator.create_base_metadata(total_docs_count=1)
        doc = MagicMock()
        doc.metadata.get.side_effect = [requests.exceptions.ConnectionError(CANARY), "file.txt"]

        with caplog.at_level("DEBUG"):
            assert operator.process_document(doc, 0, metadata) is None

        assert CANARY not in str(metadata["failed_docs"])
        assert CANARY not in caplog.text


class TestStorageCatchSites:
    def test_s3_destination_write_error(self, caplog):
        from docpipe.core.operators.storage.adapters.outbound.destinations.s3.adapter import S3DestinationAdapter
        from docpipe.core.operators.storage.adapters.outbound.destinations.s3.config import S3DestinationConfig

        adapter = S3DestinationAdapter()
        config = S3DestinationConfig(access_key="ak", secret_key=CANARY, bucket="b")
        error = requests.exceptions.ConnectionError(f"https://ak:{CANARY}@host")

        with (
            patch.object(adapter, "_create_s3_client", side_effect=error),
            caplog.at_level("DEBUG"),
        ):
            result = adapter.write_document(content=b"x", destination_path="k", config=config)

        assert result.success is False
        assert CANARY not in (result.error_message or "")
        assert CANARY not in caplog.text

    def test_filesystem_destination_write_error(self):
        from docpipe.core.operators.storage.adapters.outbound.destinations.filesystem.adapter import (
            FilesystemDestinationAdapter,
        )

        adapter = FilesystemDestinationAdapter()
        with patch("pathlib.Path.write_bytes", side_effect=requests.exceptions.ConnectionError(CANARY)):
            result = adapter.write_document(content=b"x", destination_path="/tmp/docpipe-a2-test.bin")

        assert result.success is False
        assert CANARY not in (result.error_message or "")


class TestVectorDBCatchSites:
    @staticmethod
    def _config() -> dict:
        return {
            "provider": "opensearch",
            "provider_config": {"host": "http://localhost:9200", "index_name": "idx"},
            "feature_mappings": [],
        }

    def test_init_failure_message(self):
        from docpipe.core.operators.vectordb.vectordb_operator import VectorDBOperator
        from docpipe.exceptions.docpipe_exceptions import DocpipeException

        error = requests.exceptions.ConnectionError(f"https://admin:{CANARY}@host:9200")
        with (
            patch(
                "docpipe.core.operators.vectordb.vectordb_operator.VectorStoreFactory.create",
                side_effect=error,
            ),
            pytest.raises(DocpipeException) as info,
        ):
            VectorDBOperator(config=self._config())

        assert CANARY not in str(info.value)
        assert CATEGORY_CONNECTION in str(info.value)

    def test_indexing_failure_reason_and_log(self, caplog):
        from docpipe.core.operators.vectordb.vectordb_operator import VectorDBOperator

        adapter = MagicMock()
        adapter.create_index.side_effect = requests.exceptions.ConnectionError(f"https://admin:{CANARY}@host")
        adapter.index_exists.return_value = False
        with patch(
            "docpipe.core.operators.vectordb.vectordb_operator.VectorStoreFactory.create",
            return_value=adapter,
        ):
            operator = VectorDBOperator(config=self._config())

        metadata = operator.create_base_metadata(total_docs_count=1)
        with caplog.at_level("DEBUG"):
            ready = operator._ensure_index_ready(
                dimension_mapping={},
                unique_doc_ids={"d1"},
                doc_hash_to_id={"d1": "d1"},
                doc_hash_to_name={"d1": "doc"},
                metadata=metadata,
            )

        assert ready is False
        assert CANARY not in caplog.text
        assert CANARY not in str(metadata)
        assert CATEGORY_CONNECTION in str(metadata)


class TestMessageWriters:
    def test_fail_node_execution_stores_sanitized_error(self):
        from docpipe.core.job_management.adapters.services.job_tracker_service import JobTrackerService

        service = JobTrackerService.__new__(JobTrackerService)
        store = MagicMock()
        store.get_node_stats_by_batch_and_node.return_value = None
        service.job_stats_store = store

        service.fail_node_execution(
            job_run_id="r",
            node_id="n",
            node_name="vectordb_node",
            exception=requests.exceptions.ConnectionError(f"https://u:{CANARY}@h"),
        )

        stored = str(store.mock_calls)
        assert CANARY not in stored
        assert CATEGORY_CONNECTION in stored

    def test_orchestrator_job_message(self):
        from docpipe.core.orchestration.abstract_orchestrator import AbstractOrchestrator

        orchestrator = MagicMock()
        orchestrator.job_status = None
        orchestrator.flow_id = "f"
        global_config: dict = {}
        op_def = {"id": "n1", "name": "vectordb_node", "operator": "vectordb"}
        error = requests.exceptions.ConnectionError(f"https://u:{CANARY}@h")

        AbstractOrchestrator._handle_node_failure(orchestrator, e=error, op_def=op_def, global_config=global_config)

        assert CANARY not in str(orchestrator.message)
        assert CATEGORY_CONNECTION in str(orchestrator.message)

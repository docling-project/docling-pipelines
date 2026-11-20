
"""Unit tests for the provider-agnostic translation service."""

from unittest.mock import Mock

import pytest

from docpipe.core.operators.functional.translation_service import TranslationService


@pytest.fixture
def mock_adapter():
    """Provide a mock LLM inference adapter."""
    adapter = Mock()
    adapter.chat.return_value = "Bonjour le monde."
    return adapter


@pytest.fixture
def service(mock_adapter):
    """Create a translation service with a mock adapter."""
    return TranslationService(
        llm_adapter=mock_adapter,
        source_language="English",
        target_language="French",
    )


def test_translate_sends_prompt_to_adapter(service, mock_adapter):
    """Translation sends the text and language settings to the adapter."""
    result = service.translate(content="Hello world.")

    assert result == "Bonjour le monde."
    mock_adapter.chat.assert_called_once()

    messages = mock_adapter.chat.call_args.kwargs["messages"]
    prompt = messages[0]["content"]

    assert "Hello world." in prompt
    assert "Source language: English" in prompt
    assert "Target language: French" in prompt
    assert mock_adapter.chat.call_args.kwargs["temperature"] == 0.0


def test_translate_empty_content_skips_adapter(service, mock_adapter):
    """Empty content is returned unchanged without calling the adapter."""
    assert service.translate(content="") == ""
    assert service.translate(content="   ") == "   "
    mock_adapter.chat.assert_not_called()


def test_translate_rejects_empty_provider_response(service, mock_adapter):
    """An empty provider response raises an error."""
    mock_adapter.chat.return_value = "   "

    with pytest.raises(ValueError, match="empty response"):
        service.translate(content="Hello world.")


def test_translate_preserves_markdown_instruction(mock_adapter):
    """The prompt requests Markdown preservation when enabled."""
    service = TranslationService(
        llm_adapter=mock_adapter,
        target_language="French",
        preserve_markdown=True,
    )

    service.translate(content="# Hello **world**")

    prompt = mock_adapter.chat.call_args.kwargs["messages"][0]["content"]
    assert "Preserve all Markdown formatting" in prompt


def test_translate_splits_long_content_in_order(mock_adapter):
    """Long content keeps paragraph spacing and translation order."""
    mock_adapter.chat.side_effect = [
        "Premier paragraphe.",
        "Deuxième paragraphe.",
    ]

    service = TranslationService(
        llm_adapter=mock_adapter,
        target_language="French",
        max_input_tokens=8,
    )

    result = service.translate(
        content="First paragraph.\n\nSecond paragraph."
    )

    assert mock_adapter.chat.call_count == 2
    assert result == "Premier paragraphe.\n\nDeuxième paragraphe."

    prompts = [
        call.kwargs["messages"][0]["content"]
        for call in mock_adapter.chat.call_args_list
    ]
    assert "First paragraph." in prompts[0]
    assert "Second paragraph." in prompts[1]


def test_translate_preserves_multiple_paragraph_separators(mock_adapter):
    """Multiple paragraph breaks remain unchanged after translation."""
    mock_adapter.chat.side_effect = [
        "Premier.",
        "Deuxième.",
        "Troisième.",
    ]

    service = TranslationService(
        llm_adapter=mock_adapter,
        target_language="French",
        max_input_tokens=4,
    )

    result = service.translate(
        content="First.\n\nSecond.\n\n\nThird."
    )

    assert result == "Premier.\n\nDeuxième.\n\n\nTroisième."
    assert mock_adapter.chat.call_count == 3

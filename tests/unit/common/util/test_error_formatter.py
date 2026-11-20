# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Unit tests for error_formatter module."""

import pytest

from docpipe.exceptions.docpipe_exceptions import (
    DocpipeException,
    FlowValidationException,
    ValidationAlert,
)
from docpipe.exceptions.error_messages import ValidationMessage
from docpipe.utils.infrastructure.error_formatter import (
    ErrorFormatter,
    format_docpipe_exception,
    format_generic_exception,
    format_validation_exception,
)


@pytest.fixture
def formatter():
    """Create an ErrorFormatter instance for testing."""
    return ErrorFormatter()


class TestValidationExceptionFormatting:
    """Test validation exception formatting."""

    def test_format_with_errors_and_flow_name(self, formatter):
        """Test formatting validation exception with errors and flow name."""
        errors: list[ValidationAlert | ValidationMessage] = [
            ValidationAlert(operator="ChunkerOperator", message="Invalid chunk_type value")
        ]
        exception = FlowValidationException(errors=errors)

        result = formatter.format_validation_exception(exception=exception, flow_name="test_flow")

        assert all(x in result for x in ["FLOW VALIDATION FAILED", "test_flow", "ChunkerOperator", "ERROR 1:"])

    def test_format_without_flow_name(self, formatter):
        """Test formatting without flow name."""
        errors: list[ValidationAlert | ValidationMessage] = [ValidationAlert(operator="TestOp", message="Test error")]
        exception = FlowValidationException(errors=errors)

        result = formatter.format_validation_exception(exception=exception, flow_name=None)

        assert "Found 1 validation error" in result
        assert "in flow" not in result

    def test_format_no_errors_falls_back_to_generic(self, formatter):
        """Test formatting with no errors uses generic formatter."""
        exception = FlowValidationException(message="Generic validation error", errors=None)

        result = formatter.format_validation_exception(exception=exception)

        assert "EXECUTION ERROR" in result
        assert "FlowValidationException" in result

    def test_format_multiple_errors(self, formatter):
        """Test formatting multiple validation errors."""
        errors = [
            ValidationAlert(operator="Op1", message="Error 1"),
            ValidationAlert(operator="Op2", message="Error 2"),
        ]

        result = formatter.format_validation_errors(errors=errors)

        assert "Found 2 validation errors" in result
        assert all(f"ERROR {i}:" in result for i in [1, 2])

    def test_format_empty_errors_returns_empty(self, formatter):
        """Test formatting empty errors list returns empty string."""
        assert formatter.format_validation_errors(errors=[]) == ""

    def test_format_validation_message_type(self, formatter):
        """Test formatting ValidationMessage objects."""
        errors = [ValidationMessage.create(message="Missing parameter", operator="ExtractOperator")]

        result = formatter.format_validation_errors(errors=errors)

        assert all(x in result for x in ["ExtractOperator", "Missing parameter"])


class TestDocpipeExceptionFormatting:
    """Test DocpipeException formatting."""

    def test_format_basic_exception(self, formatter):
        """Test formatting basic DocpipeException."""
        exception = DocpipeException("Test error message")

        result = formatter.format_docpipe_exception(exception=exception)

        assert all(x in result for x in ["DOCPIPE", "Test error message"])

    def test_format_with_context_attributes(self, formatter):
        """Test formatting with context attributes."""

        class CustomException(DocpipeException):
            def __init__(self, message):
                super().__init__(message)
                self.flow_id = "flow-123"
                self.job_id = "job-456"

        exception = CustomException("Error with context")
        result = formatter.format_docpipe_exception(exception=exception)

        assert " Details:" in result
        assert " Flow Id: flow-123" in result
        assert " Job Id: job-456" in result

    def test_extract_context_from_exception(self, formatter):
        """Test extracting context from exception attributes."""

        class TestException(Exception):
            def __init__(self):
                super().__init__()
                self.flow_id = "test-flow"
                self.host = "localhost"

        exception = TestException()
        result = formatter._extract_exception_context(exception=exception)

        result_str = "\n".join(result)
        assert " Details:" in result_str
        assert " Flow Id: test-flow" in result_str
        assert " Host: localhost" in result_str

    def test_extract_context_no_attributes(self, formatter):
        """Test extracting context with no relevant attributes."""
        assert formatter._extract_exception_context(exception=Exception()) == []


class TestErrorCardFormatting:
    """Test error card formatting."""

    def test_format_validation_alert(self, formatter):
        """Test formatting ValidationAlert as error card."""
        error = ValidationAlert(operator="ChunkerOperator", message="Invalid configuration")

        result = "\n".join(formatter._format_error_card(error=error, error_number=1))

        assert all(x in result for x in ["ERROR 1: ChunkerOperator operator", "Invalid configuration"])

    def test_format_validation_message(self, formatter):
        """Test formatting ValidationMessage as error card."""
        error = ValidationMessage.create(message="Missing parameter", operator="ExtractOperator")

        result = "\n".join(formatter._format_error_card(error=error, error_number=2))

        assert all(x in result for x in ["ERROR 2: ExtractOperator operator", "Missing parameter"])

    def test_format_dict(self, formatter):
        """Test formatting plain dict as error card."""
        error = {"operator": "TestOperator", "message": "Test error"}

        result = "\n".join(formatter._format_error_card(error=error, error_number=3))

        assert all(x in result for x in ["ERROR 3: TestOperator operator", "Test error"])

    def test_format_unknown_type(self, formatter):
        """Test formatting unknown type falls back gracefully."""
        result = "\n".join(formatter._format_error_card(error="Plain string", error_number=1))

        assert "Plain string" in result

    def test_format_missing_operator(self, formatter):
        """Test formatting with missing operator."""
        result = "\n".join(formatter._format_error_card(error={"message": "Error"}, error_number=1))

        assert "Unknown operator" in result

    def test_format_missing_message(self, formatter):
        """Test formatting with missing message."""
        result = "\n".join(formatter._format_error_card(error={"operator": "TestOp"}, error_number=1))

        assert "No error message provided" in result

    def test_format_error_card_renders_all_extra_fields_under_details(self, formatter):
        """Test extra fields are rendered under a single Details section."""
        error = ValidationAlert(
            operator="Merge",
            message="Invalid merge type",
            message_code="INVALID_MERGE_TYPE",
            merge_type="sideways",
            valid_values=["rows", "columns"],
            column_option="innerish",
        )

        result = "\n".join(formatter._format_error_card(error=error, error_number=1))

        assert " Details:" in result
        assert " Merge Type: sideways" in result
        assert " Valid Values: rows, columns" in result
        assert " Column Option: innerish" in result


class TestErrorConversion:
    """Test conversion of supported error inputs."""

    def test_to_error_dict_from_validation_alert(self, formatter):
        """Test ValidationAlert conversion preserves fields."""
        error = ValidationAlert(
            operator="Chunker",
            message="Invalid chunk type",
            message_code="CHUNKER_INVALID_CHUNK_TYPE",
            chunk_type="bad",
            valid_values=["sentence", "token"],
        )

        raw = formatter._to_error_dict(error=error)

        assert raw["operator"] == "Chunker"
        assert raw["message_code"] == "CHUNKER_INVALID_CHUNK_TYPE"
        assert raw["chunk_type"] == "bad"
        assert raw["valid_values"] == ["sentence", "token"]

    def test_to_error_dict_from_validation_message(self, formatter):
        """Test ValidationMessage conversion preserves extra fields."""
        error = ValidationMessage.create(
            message="Missing features",
            message_code="MISSING_FEATURES",
            operator="Embeddings",
            missing_features=["content"],
        )

        raw = formatter._to_error_dict(error=error)

        assert raw["operator"] == "Embeddings"
        assert raw["missing_features"] == ["content"]

    def test_to_error_dict_unknown_input(self, formatter):
        """Test unknown input falls back to message-only dict."""
        raw = formatter._to_error_dict(error=RuntimeError("boom"))

        assert raw == {"message": "boom"}


class TestDetailsRendering:
    """Test details rendering from error dicts."""

    def test_build_details_block_with_scalar_fields(self, formatter):
        """Test scalar extra fields are rendered in Details."""
        result = formatter._build_details_block(
            details={
                "chunk_type": "invalid",
                "max_size": 1000,
            }
        )

        result_str = "\n".join(result)
        assert " Details:" in result_str
        assert " Chunk Type: invalid" in result_str
        assert " Max Size: 1000" in result_str

    def test_build_details_block_with_list_values(self, formatter):
        """Test list values are rendered in Details."""
        result = "\n".join(
            formatter._build_details_block(
                details={
                    "valid_values": ["opt1", "opt2", "opt3"],
                }
            )
        )

        assert "Details:" in result
        assert "Valid Values: opt1, opt2, opt3" in result

    def test_build_details_block_empty_returns_no_output(self, formatter):
        """Test empty details return no output."""
        assert formatter._build_details_block(details={}) == []

    def test_build_details_block_with_dict_values(self, formatter):
        """Test nested dictionary values are rendered."""
        result = "\n".join(
            formatter._build_details_block(
                details={
                    "config": {"key1": "value1", "key2": "value2"},
                }
            )
        )

        assert "Details:" in result
        assert "Config:" in result
        assert "Key1: value1" in result
        assert "Key2: value2" in result


class TestSuggestionRendering:
    """Test explicit suggestion rendering."""

    def test_explicit_suggestion_is_preserved_in_error_dict(self, formatter):
        """Test producer-provided suggestion is preserved."""
        raw = formatter._to_error_dict(
            error={
                "operator": "ACL",
                "message": "Invalid provider",
                "suggestion": "Use a supported provider for this operator.",
            }
        )

        assert raw["suggestion"] == "Use a supported provider for this operator."

    def test_error_card_renders_explicit_suggestion_only(self, formatter):
        """Test error card renders explicit suggestion when provided."""
        result = "\n".join(
            formatter._format_error_card(
                error={
                    "operator": "ACL",
                    "message": "Invalid provider",
                    "suggestion": "Use a supported provider for this operator.",
                },
                error_number=1,
            )
        )

        assert "Suggestion:" in result
        assert "Use a supported provider for this operator." in result

    def test_error_card_omits_suggestion_when_not_provided(self, formatter):
        """Test error card omits suggestion block when not provided."""
        result = "\n".join(
            formatter._format_error_card(
                error={
                    "operator": "ChunkerOperator",
                    "message": "Invalid configuration",
                },
                error_number=1,
            )
        )

        assert "Suggestion:" not in result


class TestTextWrapping:
    """Test text wrapping functionality."""

    def test_wrap_short_text(self, formatter):
        """Test wrapping short text."""
        result = formatter._wrap_text(text="Short text", indent=" ")

        assert result == [" Short text"]

    def test_wrap_long_text(self, formatter):
        """Test wrapping long text across multiple lines."""
        text = "word " * 30
        result = formatter._wrap_text(text=text, indent=" ", max_width=40)

        assert len(result) > 1
        assert all(len(line) <= 40 for line in result)

    def test_wrap_with_custom_indent(self, formatter):
        """Test wrapping with custom indentation."""
        result = formatter._wrap_text(text="Text", indent="    ")

        assert result[0].startswith("    ")

    def test_wrap_empty_string(self, formatter):
        """Test wrapping empty string."""
        assert formatter._wrap_text(text="", indent=" ") == [" "]

    def test_build_message_block_preserves_line_breaks(self, formatter):
        """Test explicit line breaks are preserved in message blocks."""
        result = formatter._build_message_block(message="Line one\nLine two", indent=" ")

        assert result[:2] == [" Line one", " Line two"]


class TestConvenienceFunctions:
    """Test module-level convenience functions."""

    def test_format_validation_exception_function(self):
        """Test format_validation_exception convenience function."""
        errors: list[ValidationAlert | ValidationMessage] = [ValidationAlert(operator="TestOp", message="Test error")]
        exception = FlowValidationException(errors=errors)

        result = format_validation_exception(exception=exception, flow_name="test")

        assert all(x in result for x in ["FLOW VALIDATION FAILED", "TestOp"])

    def test_format_docpipe_exception_routes_validation(self):
        """Test format_docpipe_exception routes validation exceptions."""
        errors: list[ValidationAlert | ValidationMessage] = [ValidationAlert(operator="TestOp", message="Test error")]
        exception = FlowValidationException(errors=errors)

        result = format_docpipe_exception(exception=exception)

        assert "FLOW VALIDATION FAILED" in result

    def test_format_docpipe_exception_generic(self):
        """Test format_docpipe_exception with generic exception."""
        exception = DocpipeException("Generic error")

        result = format_docpipe_exception(exception=exception)

        assert all(x in result for x in ["DOCPIPE", "Generic error"])

    def test_format_generic_exception_function(self):
        """Test format_generic_exception convenience function."""
        exception = ValueError("Test value error")

        result = format_generic_exception(exception=exception)

        assert all(x in result for x in ["EXECUTION ERROR", "ValueError", "DS_LOG_LEVEL=DEBUG"])


class TestEdgeCases:
    """Test edge cases and error conditions."""

    def test_mixed_error_types(self, formatter):
        """Test formatting mixed error types."""
        errors: list[ValidationAlert | ValidationMessage | dict] = [
            ValidationAlert(operator="Op1", message="Alert"),
            ValidationMessage.create(message="Message", operator="Op2"),
            {"operator": "Op3", "message": "Dict"},
        ]

        result = formatter.format_validation_errors(errors=errors)

        assert all(f"Op{i}" in result for i in [1, 2, 3])

    def test_special_characters_in_message(self, formatter):
        """Test special characters are preserved."""
        exception = DocpipeException("Error: @#$%^&*()")

        result = formatter.format_docpipe_exception(exception=exception)

        assert "@#$%^&*()" in result

    def test_very_long_message_wraps(self, formatter):
        """Test very long messages wrap correctly."""
        long_message = "word " * 100
        exception = DocpipeException(long_message)

        result = formatter.format_docpipe_exception(exception=exception)
        message_lines = [line for line in result.split("\n") if line.startswith(" ") and "word" in line]

        assert message_lines
        assert all(len(line) <= formatter.WIDTH for line in message_lines)

    def test_none_values_handled(self, formatter):
        """Test None values are handled gracefully."""
        result = formatter._format_error_card(error={"operator": None, "message": None}, error_number=1)

        assert "ERROR 1:" in "\n".join(result)


class TestConstants:
    """Test formatter constants."""

    def test_width_constant(self, formatter):
        """Test WIDTH constant."""
        assert formatter.WIDTH == 80

    def test_separator_constant(self, formatter):
        """Test SEPARATOR constant."""
        assert formatter.SEPARATOR == "=" * 80

    def test_card_separator_constant(self, formatter):
        """Test CARD_SEPARATOR constant."""
        assert formatter.CARD_SEPARATOR == "─" * 79


class TestDocpipeExceptionBlocks:
    """Test optional blocks of format_docpipe_exception."""

    def test_node_failures_are_rendered_in_their_own_block(self, formatter):
        """node_failures are listed per operator and not repeated under Details."""
        exc = DocpipeException("Flow execution failed", status_code=500)
        exc.node_failures = {"extract": "Docling conversion failed", "chunker": ""}  # type: ignore[attr-defined]

        lines = formatter.format_docpipe_exception(exception=exc).splitlines()

        start = lines.index(" Failed operators:")
        assert lines[start + 1] == f" {formatter.CARD_SEPARATOR}"
        assert lines[start + 2] == "  [extract]"
        assert lines[start + 3] == "  Docling conversion failed"
        assert lines[start + 5] == "  [chunker]"
        # An empty node error still renders an (empty) message block.
        assert lines[start + 6] == "  "
        assert "Node Failures" not in "\n".join(lines)

    def test_non_docpipe_exception_has_no_details_block(self, formatter):
        """A plain exception gets the header and message but no Details section."""
        exc = ValueError("plain failure")
        exc.status_code = 418  # type: ignore[attr-defined]

        result = formatter.format_docpipe_exception(exception=exc)

        assert " VALUE" in result
        assert "plain failure" in result
        assert "Details:" not in result
        assert "418" not in result

    def test_docpipe_exception_without_displayable_context(self, formatter):
        """A DocpipeException whose attributes are all empty renders no Details section."""
        exc = DocpipeException("nothing to add")
        exc.status_code = None  # type: ignore[assignment]

        result = formatter.format_docpipe_exception(exception=exc)

        assert "nothing to add" in result
        assert "Details:" not in result

    def test_blank_lines_in_message_are_preserved(self, formatter):
        """Explicit blank lines inside a message are kept as indented empty lines."""
        lines = formatter._build_message_block(message="first\n\nsecond", indent=" ")

        assert lines == [" first", " ", " second", ""]

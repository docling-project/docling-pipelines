# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Unit tests for ValidationService wrapper unwrapping and alert normalisation."""

from unittest.mock import patch

import pytest

from docpipe.core.assets.flows.application.services.validation_service import ValidationService
from docpipe.exceptions.docpipe_exceptions import FlowValidationException
from docpipe.exceptions.error_messages import ValidationMessage

_ELYRA_CONVERTER = "docpipe.utils.orchestration.elyra_converter.ElyraConverter"
_FLOW_VALIDATOR = "docpipe.core.orchestration.flow_validator.FlowValidator"
_ORCHESTRATOR_FACTORY = "docpipe.core.orchestration.orchestrator_factory.OrchestratorFactory"


class TestConvertToDagFlowWrapper:
    """Tests for unwrapping the {"flow": {...}} wrapper after conversion."""

    @pytest.mark.parametrize("inner", [None, ["not", "a", "dict"]])
    def test_invalid_wrapper_raises_flow_validation_exception(self, inner):
        """A wrapper whose inner value is not a dict raises INVALID_FLOW_WRAPPER."""
        with patch(_ELYRA_CONVERTER) as converter_cls:
            converter_cls.return_value.transform_elyra_to_internal.return_value = {"flow": inner}

            with pytest.raises(FlowValidationException) as exc_info:
                ValidationService()._convert_to_dag_flow(flow_definition={"doc_type": "pipeline"}, is_elyra=True)

        errors = exc_info.value.errors
        assert errors is not None
        assert len(errors) == 1
        assert errors[0]["message_code"] == "INVALID_FLOW_WRAPPER"
        assert errors[0]["message"] == "Flow wrapper contains invalid structure"

    def test_valid_wrapper_is_unwrapped(self):
        """A dict inside the wrapper is returned on its own."""
        inner: dict[str, object] = {"dag": [], "global_config": {}}
        with patch(_ELYRA_CONVERTER) as converter_cls:
            converter_cls.return_value.transform_elyra_to_internal.return_value = {"flow": inner}

            result = ValidationService()._convert_to_dag_flow(flow_definition={"doc_type": "pipeline"}, is_elyra=True)

        assert result is inner


class TestAlertNormalisation:
    """Tests for turning validator alerts of various types into response dicts."""

    def test_validation_message_without_code_gets_default_code(self):
        """A ValidationMessage without a code field receives the default code."""
        alert = ValidationMessage(message="bad node", message_code="BAD_NODE")

        result = ValidationService()._normalize_validation_alert(alert=alert, default_code="VALIDATION_ERROR")

        assert result == {"message": "bad node", "message_code": "BAD_NODE", "code": "VALIDATION_ERROR"}

    def test_validation_message_with_code_keeps_its_code(self):
        """A ValidationMessage that carries a code as an extra field keeps it."""
        alert = ValidationMessage(message="bad node", code="OWN_CODE")

        result = ValidationService()._normalize_validation_alert(alert=alert, default_code="VALIDATION_ERROR")

        assert result == {"message": "bad node", "code": "OWN_CODE"}

    def test_unknown_alert_type_falls_back_to_string(self):
        """Any other alert object is stringified with the default code."""
        result = ValidationService()._normalize_validation_alert(alert=42, default_code="VALIDATION_WARNING")

        assert result == {"code": "VALIDATION_WARNING", "message": "42"}

    def test_validate_flow_normalises_mixed_errors_and_warnings(self):
        """validate_flow reports ValidationMessage errors and plain-string warnings in normalised form."""
        flow_definition = {
            "flow_name": "f",
            "flow": [{"type": "ingest_source", "name": "ingest", "config": {}, "depends_on": []}],
        }
        exception = FlowValidationException(
            errors=[ValidationMessage(message="missing feature")],
            warnings=["consider a vectordb"],  # type: ignore[list-item]
        )

        with patch(_ORCHESTRATOR_FACTORY), patch(_FLOW_VALIDATOR) as validator_cls:
            validator_cls.return_value.validate_dag_with_features.side_effect = exception

            result = ValidationService().validate_flow(flow_definition=flow_definition, is_elyra=False)

        assert result == {
            "status": "FAILED",
            "message": "Flow validation failed.",
            "errors": [{"message": "missing feature", "code": "VALIDATION_ERROR"}],
            "warnings": [{"code": "VALIDATION_WARNING", "message": "consider a vectordb"}],
        }

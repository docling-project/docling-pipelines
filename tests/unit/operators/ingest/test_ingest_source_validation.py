"""Unit tests for IngestSourceOperator validation functionality."""

from typing import Any
from unittest.mock import patch

import pytest

from docpipe.core.operators.ingest.ingest_source import IngestSourceOperator
from docpipe.exceptions.error_messages import ValidationCodeMessages, ValidationMessage


@pytest.mark.parametrize("config", [{}, {"provider": None}, {"provider": ""}, {"provider": " \t\n "}])
def test_missing_provider_returns_actionable_validation_error(config):
    """Incomplete selections report a structured alert instead of constructor errors."""
    operator = IngestSourceOperator(config)
    errors: list[Any] = []
    operator.validate(errors=errors, warnings=[], available_features=[])

    assert errors == [
        ValidationMessage(
            message=ValidationCodeMessages.INGEST_PROVIDER_MISSING.value,
            message_code="INGEST_PROVIDER_MISSING",
        )
    ]


@pytest.mark.parametrize("config", [{}, {"provider": None}, {"provider": ""}, {"provider": " \t\n "}])
def test_missing_provider_rejects_execution_before_storage_access(config):
    """Execution still requires a provider when flow validation is bypassed."""
    operator = IngestSourceOperator(config)
    with patch("docpipe.core.operators.ingest.ingest_source.get_incremental_update_service") as storage:
        with pytest.raises(ValueError, match="Provider not added"):
            operator.transform(None)
        storage.assert_not_called()


def test_provider_normalization_preserves_valid_configuration():
    """Provider selections remain case-insensitive and ignore surrounding whitespace."""
    operator = IngestSourceOperator({"provider": "  FiLeSyStEm  ", "provider_config": {"paths": ["/tmp"]}})
    errors: list[Any] = []
    operator.validate(errors=errors, warnings=[], available_features=[])
    assert operator.provider == "filesystem"
    assert errors == []


@pytest.mark.parametrize("provider", [123, False, [], {}])
def test_non_string_provider_reports_clear_type_error(provider):
    """Malformed values must not expose an AttributeError."""
    with pytest.raises(ValueError, match="Provider must be a string"):
        IngestSourceOperator({"provider": provider})


class TestIngestSourceOperatorValidation:
    """Test validation of IngestSourceOperator configurations."""

    def test_validation_catches_missing_secret_key_for_s3(self):
        """Test that validation catches missing secret_key for S3 provider."""
        config = {
            "provider": "s3",
            "provider_config": {
                "access_key": "test_access_key",
                # Missing secret_key - should trigger validation error
                "bucket": "test-bucket",
                "prefix": "test/",
            },
            "validating_flow": True,
        }

        operator = IngestSourceOperator(config)

        errors: list[str] = []
        warnings: list[str] = []
        available_features: list[str] = []

        operator.validate(errors=errors, warnings=warnings, available_features=available_features)

        # Should have at least one error about missing secret_key
        assert len(errors) > 0, "Expected validation error for missing secret_key"
        assert any("secret_key" in str(error).lower() for error in errors), (
            "Expected error message to mention 'secret_key'"
        )

    def test_validation_catches_missing_access_key_for_s3(self):
        """Test that validation catches missing access_key for S3 provider."""
        config = {
            "provider": "s3",
            "provider_config": {
                "secret_key": "test_secret_key",  # pragma: allowlist secret
                # Missing access_key - should trigger validation error
                "bucket": "test-bucket",
                "prefix": "test/",
            },
            "validating_flow": True,
        }

        operator = IngestSourceOperator(config)

        errors: list[str] = []
        warnings: list[str] = []
        available_features: list[str] = []

        operator.validate(errors=errors, warnings=warnings, available_features=available_features)

        # Should have at least one error about missing access_key
        assert len(errors) > 0, "Expected validation error for missing access_key"
        assert any("access_key" in str(error).lower() for error in errors), (
            "Expected error message to mention 'access_key'"
        )

    def test_validation_catches_missing_bucket_for_s3(self):
        """Test that validation catches missing bucket for S3 provider."""
        config = {
            "provider": "s3",
            "provider_config": {
                "access_key": "test_access_key",
                "secret_key": "test_secret_key",  # pragma: allowlist secret
                # Missing bucket - should trigger validation error
                "prefix": "test/",
            },
            "validating_flow": True,
        }

        operator = IngestSourceOperator(config)

        errors: list[str] = []
        warnings: list[str] = []
        available_features: list[str] = []

        operator.validate(errors=errors, warnings=warnings, available_features=available_features)

        # Should have at least one error about missing bucket
        assert len(errors) > 0, "Expected validation error for missing bucket"
        assert any("bucket" in str(error).lower() for error in errors), "Expected error message to mention 'bucket'"

    def test_validation_passes_with_complete_s3_config(self):
        """Test that validation passes with complete S3 configuration."""
        config = {
            "provider": "s3",
            "provider_config": {
                "access_key": "test_access_key",
                "secret_key": "test_secret_key",  # pragma: allowlist secret
                "bucket": "test-bucket",
                "prefix": "test/",
            },
            "validating_flow": True,
        }

        operator = IngestSourceOperator(config)

        errors: list[str] = []
        warnings: list[str] = []
        available_features: list[str] = []

        operator.validate(errors=errors, warnings=warnings, available_features=available_features)

        # Should have no errors with complete config
        assert len(errors) == 0, f"Expected no validation errors, but got: {errors}"

    def test_validation_catches_empty_credentials_for_s3(self):
        """Test that validation catches empty string credentials for S3."""
        config = {
            "provider": "s3",
            "provider_config": {
                "access_key": "",  # Empty string
                "secret_key": "test_secret_key",  # pragma: allowlist secret
                "bucket": "test-bucket",
            },
            "validating_flow": True,
        }

        operator = IngestSourceOperator(config)

        errors: list[str] = []
        warnings: list[str] = []
        available_features: list[str] = []

        operator.validate(errors=errors, warnings=warnings, available_features=available_features)

        # Should have error about empty access_key
        assert len(errors) > 0, "Expected validation error for empty access_key"
        assert any("access_key" in str(error).lower() for error in errors), (
            "Expected error message to mention 'access_key'"
        )

    def test_validation_works_for_other_adapter_providers(self):
        """Test that validation works for other adapter-managed providers like Google Drive."""
        config = {
            "provider": "google_drive",
            "provider_config": {
                # Missing required credentials for Google Drive
            },
            "validating_flow": True,
        }

        operator = IngestSourceOperator(config)

        errors: list[str] = []
        warnings: list[str] = []
        available_features: list[str] = []

        operator.validate(errors=errors, warnings=warnings, available_features=available_features)

        # Should catch validation errors for Google Drive too
        assert len(errors) > 0, "Expected validation error for incomplete Google Drive config"

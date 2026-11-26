# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

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

    def test_filesystem_path_outside_allowed_roots_rejected_when_auth_enabled(self, monkeypatch, tmp_path):
        """When DOCPIPE_AUTH_ENABLED=true, filesystem paths outside allowed roots fail validation and execution."""
        allowed_root = tmp_path / "allowed"
        allowed_root.mkdir()
        outside_dir = tmp_path / "outside"
        outside_dir.mkdir()

        monkeypatch.setenv("DOCPIPE_AUTH_ENABLED", "true")
        monkeypatch.setenv("DOCPIPE_INGEST_ALLOWED_PATHS", str(allowed_root))

        operator = IngestSourceOperator(
            {
                "provider": "filesystem",
                "provider_config": {"paths": [str(outside_dir)]},
            }
        )
        errors: list[str] = []
        operator.validate(errors=errors, warnings=[], available_features=[])
        assert len(errors) == 1
        assert "outside the allowed root directories" in errors[0]

        with pytest.raises(ValueError, match="outside the allowed root directories"):
            operator.transform(None)

    def test_filesystem_path_traversal_rejected_when_auth_enabled(self, monkeypatch, tmp_path):
        """Path traversal escaping the allowed root is rejected when auth is enabled."""
        allowed_root = tmp_path / "allowed"
        allowed_root.mkdir()
        (tmp_path / "outside").mkdir()
        traversal_path = f"{allowed_root}/../outside"

        monkeypatch.setenv("DOCPIPE_AUTH_ENABLED", "true")
        monkeypatch.setenv("DOCPIPE_INGEST_ALLOWED_PATHS", str(allowed_root))

        operator = IngestSourceOperator(
            {
                "provider": "filesystem",
                "provider_config": {"paths": [traversal_path]},
            }
        )
        errors: list[str] = []
        operator.validate(errors=errors, warnings=[], available_features=[])
        assert len(errors) == 1
        assert "outside the allowed root directories" in errors[0]

    @pytest.mark.parametrize("sep", [",", ";"])
    def test_filesystem_path_inside_allowed_roots_accepted_when_auth_enabled(self, monkeypatch, tmp_path, sep):
        """Filesystem paths inside comma- or semicolon-separated DOCPIPE_INGEST_ALLOWED_PATHS pass validation."""
        root_a = tmp_path / "root_a"
        root_b = tmp_path / "root_b"
        nested = root_b / "sub"
        root_a.mkdir()
        nested.mkdir(parents=True)

        monkeypatch.setenv("DOCPIPE_AUTH_ENABLED", "true")
        monkeypatch.setenv("DOCPIPE_INGEST_ALLOWED_PATHS", f"{root_a}{sep}{root_b}")

        operator = IngestSourceOperator(
            {
                "provider": "filesystem",
                "provider_config": {"paths": [str(nested)]},
            }
        )
        errors: list[str] = []
        operator.validate(errors=errors, warnings=[], available_features=[])
        assert errors == []

    def test_filesystem_path_defaults_to_data_path_when_auth_enabled(self, monkeypatch, tmp_path):
        """When DOCPIPE_INGEST_ALLOWED_PATHS is unset, get_data_path() is the default allowed root."""
        data_root = tmp_path / "data"
        inside = data_root / "docs"
        inside.mkdir(parents=True)
        outside = tmp_path / "other"
        outside.mkdir()

        monkeypatch.setenv("DOCPIPE_AUTH_ENABLED", "true")
        monkeypatch.delenv("DOCPIPE_INGEST_ALLOWED_PATHS", raising=False)
        monkeypatch.setenv("DOCPIPE_DATA_PATH", str(data_root))

        valid_op = IngestSourceOperator({"provider": "filesystem", "provider_config": {"paths": [str(inside)]}})
        errors: list[str] = []
        valid_op.validate(errors=errors, warnings=[], available_features=[])
        assert errors == []

        invalid_op = IngestSourceOperator({"provider": "filesystem", "provider_config": {"paths": [str(outside)]}})
        invalid_op.validate(errors=errors, warnings=[], available_features=[])
        assert len(errors) == 1
        assert "outside the allowed root directories" in errors[0]

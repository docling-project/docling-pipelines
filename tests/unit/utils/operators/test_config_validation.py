"""Unit tests for validate_config_from_metadata.

Covers:
- Required field missing or None
- Optional field absent
- Nested JSON/object recursion
- provider_config key validation against the providers schema
- Graceful no-op edge cases
"""

from docpipe.core.constants import AttributeDataTypes, OperatorConstants
from docpipe.utils.operators.config_validation import validate_config_from_metadata

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_provider_attributes(*, allow_extra_litellm: bool = True) -> dict:
    """Return ATTRIBUTES with a provider field and a provider_config field that
    carries a providers schema for watsonx (strict) and litellm (open if flag set).
    """
    return {
        OperatorConstants.Config.PROVIDER: {
            OperatorConstants.Misc.TYPE: AttributeDataTypes.STRING,
            OperatorConstants.Config.REQUIRED: False,
        },
        OperatorConstants.Config.PROVIDER_CONFIG: {
            OperatorConstants.Misc.TYPE: AttributeDataTypes.JSON,
            OperatorConstants.Config.REQUIRED: False,
            OperatorConstants.Config.PROVIDERS: {
                "watsonx": {
                    OperatorConstants.Config.PROPERTIES: {
                        "model_id": {OperatorConstants.Misc.TYPE: AttributeDataTypes.STRING},
                        "api_base": {OperatorConstants.Misc.TYPE: AttributeDataTypes.STRING},
                        "api_key": {OperatorConstants.Misc.TYPE: AttributeDataTypes.STRING},
                        "url": {OperatorConstants.Misc.TYPE: AttributeDataTypes.STRING},
                        "container_kind": {OperatorConstants.Misc.TYPE: AttributeDataTypes.STRING},
                        "container_id": {OperatorConstants.Misc.TYPE: AttributeDataTypes.STRING},
                    },
                },
                "litellm": {
                    **({OperatorConstants.Config.ALLOW_EXTRA_KEYS: True} if allow_extra_litellm else {}),
                    OperatorConstants.Config.PROPERTIES: {
                        "model_id": {OperatorConstants.Misc.TYPE: AttributeDataTypes.STRING},
                        "api_base": {OperatorConstants.Misc.TYPE: AttributeDataTypes.STRING},
                        "api_key": {OperatorConstants.Misc.TYPE: AttributeDataTypes.STRING},
                    },
                },
            },
        },
    }


# ---------------------------------------------------------------------------
# Required fields
# ---------------------------------------------------------------------------


class TestValidateConfigFromMetadataRequiredFields:
    """Tests for required field validation."""

    def test_required_field_missing_appends_error(self) -> None:
        """Missing required field produces an error."""
        attributes = {
            "model_id": {
                OperatorConstants.Misc.TYPE: AttributeDataTypes.STRING,
                OperatorConstants.Config.REQUIRED: True,
            }
        }
        errors: list[str] = []
        validate_config_from_metadata(config={}, attributes=attributes, errors=errors)
        assert errors == ["model_id is required"]

    def test_required_field_set_to_none_appends_error(self) -> None:
        """Required field explicitly set to None is treated as missing."""
        attributes = {
            "model_id": {
                OperatorConstants.Misc.TYPE: AttributeDataTypes.STRING,
                OperatorConstants.Config.REQUIRED: True,
            }
        }
        errors: list[str] = []
        validate_config_from_metadata(config={"model_id": None}, attributes=attributes, errors=errors)
        assert errors == ["model_id is required"]

    def test_required_field_present_no_error(self) -> None:
        """Required field with a value produces no error."""
        attributes = {
            "model_id": {
                OperatorConstants.Misc.TYPE: AttributeDataTypes.STRING,
                OperatorConstants.Config.REQUIRED: True,
            }
        }
        errors: list[str] = []
        validate_config_from_metadata(config={"model_id": "ibm/slate"}, attributes=attributes, errors=errors)
        assert errors == []

    def test_multiple_required_fields_missing_all_reported(self) -> None:
        """All missing required fields are reported, not just the first."""
        attributes = {
            "field_a": {
                OperatorConstants.Misc.TYPE: AttributeDataTypes.STRING,
                OperatorConstants.Config.REQUIRED: True,
            },
            "field_b": {
                OperatorConstants.Misc.TYPE: AttributeDataTypes.STRING,
                OperatorConstants.Config.REQUIRED: True,
            },
        }
        errors: list[str] = []
        validate_config_from_metadata(config={}, attributes=attributes, errors=errors)
        assert len(errors) == 2


# ---------------------------------------------------------------------------
# Optional fields
# ---------------------------------------------------------------------------


class TestValidateConfigFromMetadataOptionalFields:
    """Tests for optional field validation."""

    def test_optional_field_absent_no_error(self) -> None:
        """Optional field that is absent produces no error."""
        attributes = {
            "timeout": {
                OperatorConstants.Misc.TYPE: AttributeDataTypes.INTEGER,
                OperatorConstants.Config.REQUIRED: False,
            }
        }
        errors: list[str] = []
        validate_config_from_metadata(config={}, attributes=attributes, errors=errors)
        assert errors == []

    def test_optional_field_present_no_error(self) -> None:
        """Optional field that is present produces no error."""
        attributes = {
            "timeout": {
                OperatorConstants.Misc.TYPE: AttributeDataTypes.INTEGER,
                OperatorConstants.Config.REQUIRED: False,
            }
        }
        errors: list[str] = []
        validate_config_from_metadata(config={"timeout": 120}, attributes=attributes, errors=errors)
        assert errors == []


# ---------------------------------------------------------------------------
# Nested JSON/object recursion
# ---------------------------------------------------------------------------


class TestValidateConfigFromMetadataNestedRecursion:
    """Tests for nested JSON/object attribute recursion."""

    def test_nested_required_field_missing_appends_error(self) -> None:
        """Required field inside a nested JSON attribute is caught recursively."""
        attributes = {
            "connection": {
                OperatorConstants.Misc.TYPE: AttributeDataTypes.JSON,
                OperatorConstants.Config.REQUIRED: True,
                OperatorConstants.Config.PROPERTIES: {
                    "host": {
                        OperatorConstants.Misc.TYPE: AttributeDataTypes.STRING,
                        OperatorConstants.Config.REQUIRED: True,
                    }
                },
            }
        }
        errors: list[str] = []
        validate_config_from_metadata(config={"connection": {}}, attributes=attributes, errors=errors)
        assert errors == ["connection.host is required"]

    def test_nested_optional_field_absent_no_error(self) -> None:
        """Optional field inside a nested JSON attribute produces no error when absent."""
        attributes = {
            "connection": {
                OperatorConstants.Misc.TYPE: AttributeDataTypes.JSON,
                OperatorConstants.Config.REQUIRED: False,
                OperatorConstants.Config.PROPERTIES: {
                    "port": {
                        OperatorConstants.Misc.TYPE: AttributeDataTypes.INTEGER,
                        OperatorConstants.Config.REQUIRED: False,
                    }
                },
            }
        }
        errors: list[str] = []
        validate_config_from_metadata(config={"connection": {}}, attributes=attributes, errors=errors)
        assert errors == []

    def test_required_json_field_not_a_dict_appends_error(self) -> None:
        """Required JSON attribute whose value is not a dict is flagged."""
        attributes = {
            "connection": {
                OperatorConstants.Misc.TYPE: AttributeDataTypes.JSON,
                OperatorConstants.Config.REQUIRED: True,
                OperatorConstants.Config.PROPERTIES: {
                    "host": {
                        OperatorConstants.Misc.TYPE: AttributeDataTypes.STRING,
                        OperatorConstants.Config.REQUIRED: True,
                    }
                },
            }
        }
        errors: list[str] = []
        validate_config_from_metadata(config={"connection": "not-a-dict"}, attributes=attributes, errors=errors)
        assert any("must be a dictionary" in e for e in errors)


# ---------------------------------------------------------------------------
# Watsonx provider — strict unknown key detection
# ---------------------------------------------------------------------------


class TestValidateConfigFromMetadataWatsonxProvider:
    """Tests for watsonx provider_config key validation (strict — no extra keys allowed)."""

    def test_unknown_key_flagged_as_error(self) -> None:
        """A typo in a watsonx provider_config key produces a clear error."""
        errors: list[str] = []
        config = {
            "provider": "watsonx",
            "provider_config": {
                "mmodel_id": "ibm/slate-125m",  # typo — should be model_id
                "api_base": "https://example.com",
                "container_kind": "project",
            },
        }
        validate_config_from_metadata(config=config, attributes=_make_provider_attributes(), errors=errors)
        assert any("mmodel_id" in e for e in errors), f"Expected unknown key error, got: {errors}"

    def test_error_message_includes_valid_keys(self) -> None:
        """Error message for an unknown watsonx key lists the valid alternatives."""
        errors: list[str] = []
        config = {
            "provider": "watsonx",
            "provider_config": {"typo_key": "value"},
        }
        validate_config_from_metadata(config=config, attributes=_make_provider_attributes(), errors=errors)
        assert len(errors) == 1
        assert "Valid keys:" in errors[0]
        assert "typo_key" in errors[0]

    def test_multiple_unknown_keys_all_flagged(self) -> None:
        """Every unknown key in a watsonx provider_config is reported individually."""
        errors: list[str] = []
        config = {
            "provider": "watsonx",
            "provider_config": {
                "mmodel_id": "bad",
                "apii_base": "bad",
            },
        }
        validate_config_from_metadata(config=config, attributes=_make_provider_attributes(), errors=errors)
        assert len([e for e in errors if "unknown key" in e]) == 2

    def test_valid_config_no_errors(self) -> None:
        """A fully valid watsonx provider_config produces no errors."""
        errors: list[str] = []
        config = {
            "provider": "watsonx",
            "provider_config": {
                "model_id": "ibm/slate-125m",
                "api_base": "https://example.com",
                "container_kind": "project",
                "container_id": "my-project-id",
            },
        }
        validate_config_from_metadata(config=config, attributes=_make_provider_attributes(), errors=errors)
        assert errors == []


# ---------------------------------------------------------------------------
# LiteLLM provider — extra keys allowed (allow_extra_keys: True)
# ---------------------------------------------------------------------------


class TestValidateConfigFromMetadataLiteLLMProvider:
    """Tests for litellm provider_config key validation (open — extra keys allowed)."""

    def test_passthrough_keys_not_flagged(self) -> None:
        """LiteLLM accepts **kwargs passthrough — unknown keys must not be flagged."""
        errors: list[str] = []
        config = {
            "provider": "litellm",
            "provider_config": {
                "model_id": "openai/nomic-embed-text",
                "api_base": "http://localhost:11434/v1",
                "api_key": "ollama",  # pragma: allowlist secret
                "temperature": 0.2,  # valid LiteLLM passthrough key, not in schema
                "max_tokens": 512,  # valid LiteLLM passthrough key, not in schema
            },
        }
        validate_config_from_metadata(config=config, attributes=_make_provider_attributes(), errors=errors)
        assert errors == []

    def test_valid_known_keys_no_errors(self) -> None:
        """A standard litellm provider_config with only known keys produces no errors."""
        errors: list[str] = []
        config = {
            "provider": "litellm",
            "provider_config": {
                "model_id": "openai/nomic-embed-text",
                "api_base": "http://localhost:11434/v1",
                "api_key": "ollama",  # pragma: allowlist secret
            },
        }
        validate_config_from_metadata(config=config, attributes=_make_provider_attributes(), errors=errors)
        assert errors == []


# ---------------------------------------------------------------------------
# Edge cases — graceful no-op
# ---------------------------------------------------------------------------


class TestValidateConfigFromMetadataEdgeCases:
    """Tests for graceful handling of missing or unexpected inputs."""

    def test_no_provider_field_skips_provider_config_validation(self) -> None:
        """Absent sibling 'provider' key means provider_config validation is skipped."""
        errors: list[str] = []
        config = {"provider_config": {"mmodel_id": "bad-typo"}}
        validate_config_from_metadata(config=config, attributes=_make_provider_attributes(), errors=errors)
        assert errors == []

    def test_unknown_provider_name_skips_validation(self) -> None:
        """Provider value not present in the providers map is skipped gracefully."""
        errors: list[str] = []
        config = {
            "provider": "huggingface",  # not in the providers map
            "provider_config": {"some_key": "value"},
        }
        validate_config_from_metadata(config=config, attributes=_make_provider_attributes(), errors=errors)
        assert errors == []

    def test_provider_config_not_a_dict_skips_provider_validation(self) -> None:
        """Non-dict provider_config value does not crash the provider key check."""
        errors: list[str] = []
        config = {
            "provider": "watsonx",
            "provider_config": "not-a-dict",
        }
        validate_config_from_metadata(config=config, attributes=_make_provider_attributes(), errors=errors)
        assert errors == []

    def test_provider_config_absent_no_errors(self) -> None:
        """Absent optional provider_config produces no errors."""
        errors: list[str] = []
        config = {"provider": "watsonx"}
        validate_config_from_metadata(config=config, attributes=_make_provider_attributes(), errors=errors)
        assert errors == []


def _make_capability_provider_attributes() -> dict:
    """Return ATTRIBUTES with a 'pii_provider_config' selected by 'pii_provider' via PROVIDER_FIELD."""
    attributes = _make_provider_attributes(allow_extra_litellm=False)
    attributes["pii_provider_config"] = {
        **attributes[OperatorConstants.Config.PROVIDER_CONFIG],
        OperatorConstants.Config.PROVIDER_FIELD: "pii_provider",
    }
    return attributes


class TestValidateConfigFromMetadataProviderField:
    """PROVIDER_FIELD selects which sibling field names the active provider."""

    def test_capability_config_validated_against_capability_provider(self) -> None:
        errors: list[str] = []
        config = {
            "provider": "litellm",
            "pii_provider": "watsonx",
            "pii_provider_config": {"url": "https://x", "api_base": "http://y"},
        }
        validate_config_from_metadata(config=config, attributes=_make_capability_provider_attributes(), errors=errors)
        assert errors == []

    def test_capability_config_unknown_key_reported_for_capability_provider(self) -> None:
        errors: list[str] = []
        config = {"provider": "watsonx", "pii_provider": "litellm", "pii_provider_config": {"url": "https://x"}}
        validate_config_from_metadata(config=config, attributes=_make_capability_provider_attributes(), errors=errors)
        assert len(errors) == 1
        assert "pii_provider_config: unknown key 'url' for provider 'litellm'" in errors[0]

    def test_capability_config_falls_back_to_provider_when_field_unset(self) -> None:
        errors: list[str] = []
        config = {"provider": "litellm", "pii_provider_config": {"container_id": "c"}}
        validate_config_from_metadata(config=config, attributes=_make_capability_provider_attributes(), errors=errors)
        assert len(errors) == 1
        assert "for provider 'litellm'" in errors[0]

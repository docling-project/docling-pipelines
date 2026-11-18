# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Generic configuration validation utilities for operators.

This module provides metadata-driven validation functions that introspect
operator ATTRIBUTES structures to validate configurations.
"""

from docpipe.core.constants import AttributeDataTypes, OperatorConstants


def validate_provider_config_keys(
    *,
    provider_config: dict,
    provider_schemas: dict,
    active_provider: str,
    full_path: str,
    errors: list[str],
) -> None:
    """Validate keys in provider_config against the schema for the active provider.

    For providers with ``allow_extra_keys: True`` in their schema, unknown keys are
    silently skipped (e.g. litellm, which accepts **kwargs passthrough). For all
    other providers, any key not declared in the provider schema's ``properties``
    is flagged as an error.

    Args:
        provider_config: The provider_config dict from the operator config.
        provider_schemas: The ``providers`` map from the attribute metadata.
        active_provider: The provider name read from the sibling ``provider`` field.
        full_path: Dot-separated config path used in error messages.
        errors: List to append validation errors to.
    """
    schema = provider_schemas.get(active_provider)
    if not schema or not isinstance(schema, dict):
        return

    known_keys = set(schema.get(OperatorConstants.Config.PROPERTIES, {}).keys())
    allow_extra = schema.get(OperatorConstants.Config.ALLOW_EXTRA_KEYS, False)

    if not allow_extra:
        for key in provider_config:
            if key not in known_keys:
                errors.append(
                    f"{full_path}: unknown key '{key}' for provider '{active_provider}'. "
                    f"Valid keys: {sorted(known_keys)}"
                )


def validate_config_from_metadata(config: dict, attributes: dict, errors: list[str], path: str = "") -> None:
    """
    Generic validation function that introspects metadata ATTRIBUTES structure.

    Args:
        config: The configuration dictionary to validate
        attributes: The ATTRIBUTES metadata dictionary defining the schema
        errors: List to append validation errors to
        path: Current path in the config (for nested error messages)

    How it works:
    1. Iterates through each attribute in the ATTRIBUTES dictionary
    2. Checks if the attribute is marked as REQUIRED=True
    3. If required, validates the field exists in config
    4. For nested objects (TYPE="object" with PROPERTIES), recursively validates
    5. For provider_config fields (TYPE="json" with PROVIDERS), validates keys
       against the active provider's schema (selected by the sibling field named in
       PROVIDER_FIELD, or "provider" by default)
    """
    for attr_key, attr_metadata in attributes.items():
        # Build the full path for error messages
        full_path = f"{path}.{attr_key}" if path else attr_key

        # Check if this attribute is required
        is_required = attr_metadata.get(OperatorConstants.Config.REQUIRED, False)

        if is_required:
            # Validate that the required field exists in config
            if attr_key not in config or config[attr_key] is None:
                errors.append(f"{full_path} is required")
                continue

        # If field is not present and not required, skip further validation
        if attr_key not in config:
            continue

        # Get the attribute type and value
        attr_type = attr_metadata.get(OperatorConstants.Misc.TYPE)
        attr_value = config[attr_key]

        # For nested objects (TYPE="object"), recursively validate nested properties
        if attr_type == AttributeDataTypes.JSON or attr_type == "object":
            nested_properties = attr_metadata.get(OperatorConstants.Config.PROPERTIES)

            if nested_properties and isinstance(attr_value, dict):
                # Recursively validate nested structure
                validate_config_from_metadata(
                    config=attr_value, attributes=nested_properties, errors=errors, path=full_path
                )
            elif is_required and not isinstance(attr_value, dict):
                errors.append(f"{full_path} must be a dictionary")

            # Validate provider_config keys against the active provider's schema
            provider_schemas = attr_metadata.get(OperatorConstants.Config.PROVIDERS)
            if provider_schemas and isinstance(attr_value, dict):
                # The sibling field selecting the provider defaults to "provider"; an attribute
                # can name another one (e.g. "pii_provider") via PROVIDER_FIELD, falling back
                # to "provider" when that field is unset.
                provider_field = attr_metadata.get(OperatorConstants.Config.PROVIDER_FIELD)
                active_provider = (config.get(provider_field) if provider_field else None) or config.get(
                    OperatorConstants.Config.PROVIDER
                )
                if active_provider:
                    validate_provider_config_keys(
                        provider_config=attr_value,
                        provider_schemas=provider_schemas,
                        active_provider=active_provider,
                        full_path=full_path,
                        errors=errors,
                    )

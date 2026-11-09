# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Inventory test for secret-capable field declarations (task B.2, design D2).

Enumerates every registered operator and fails when a configuration key named
like a credential is neither declared secret-capable nor explicitly marked
``no_references``. Naming fields must never be declared.
"""

from collections.abc import Iterator, Mapping
from typing import Any, ClassVar

import pytest

from docpipe.core.operators.abstract_operator import AbstractOperator
from docpipe.core.operators.operator_registry import get_docpipe_operators
from docpipe.core.operators.secret_fields import (
    DECLARED_BY_PROVIDER_KEY,
    DECLARED_FIELDS_KEY,
    NAMING_FIELD_NAMES,
    NO_REFERENCES_KEY,
    effective_secret_fields,
    is_covered,
    is_credential_looking,
)

OPERATORS = sorted(get_docpipe_operators(), key=lambda cls: cls.short_name)

# Operators in the spec inventory that must declare at least one secret-capable field.
INVENTORY_OPERATORS = {
    "ingest_source",
    "storage_output",
    "vectordb",
    "embeddings",
    "document_classifier",
    "pii_and_hap",
    "extract_operator",
    "chunker",
    "acl_operator",
}

# Inventory table from the spec: operator -> provider -> required secret-capable keys
# (keys relative to the provider config object).
INVENTORY_PROVIDER_FIELDS: dict[str, dict[str, set[str]]] = {
    "ingest_source": {
        "s3": {"access_key", "secret_key", "endpoint_url", "bucket", "region"},
        "ibm_cos": {"access_key", "secret_key", "endpoint_url", "bucket", "region"},
        "sharepoint": {"client_id", "client_secret", "tenant_id", "document_library_id"},
        "onedrive": {"client_id", "client_secret", "tenant_id", "drive_id"},
        "google_drive": {
            "service_account_json",
            "service_account_json_path",
            "credentials_json",
            "credentials_path",
            "token_path",
        },
        "box_driver": {"credentials_json", "credentials_path", "credentials_json_path"},
        "dropbox": {"access_token", "refresh_token", "app_key", "app_secret"},
    },
    "storage_output": {
        "s3": {"access_key", "secret_key", "endpoint_url"},
        "ibm_cos": {"access_key", "secret_key", "endpoint_url"},
        "sharepoint": {"client_id", "client_secret", "tenant_id"},
        "onedrive": {"client_id", "client_secret", "tenant_id"},
        "box": {"credentials_path"},
        "google_drive": {"service_account_json_path", "credentials_path", "token_path"},
    },
    "vectordb": {
        "opensearch": {"host", "username", "password", "jwt_token", "aws_region"},
        "milvus": {"host", "uri", "token", "username", "password", "database"},
    },
    "embeddings": {"litellm": {"api_key", "api_base"}, "watsonx": {"api_key", "api_base", "url"}},
    "document_classifier": {"litellm": {"api_key", "api_base"}, "watsonx": {"api_key", "api_base", "url"}},
    "pii_and_hap": {"litellm": {"api_key", "api_base"}, "watsonx": {"api_key", "url"}},
}


def _walk(
    *, attributes: Mapping[str, Any], path: str = "", provider: str | None = None
) -> Iterator[tuple[str, str | None]]:
    """Yield ``(config_path, provider)`` for every attribute key.

    ``properties`` and ``providers.<name>`` wrappers are folded out so the path is the
    one a flow author writes. ``provider`` is set for keys inside a provider schema.
    """
    for key, spec in attributes.items():
        config_path = f"{path}.{key}" if path else key
        yield config_path, provider
        if not isinstance(spec, Mapping):
            continue
        nested = spec.get("properties")
        if isinstance(nested, Mapping):
            yield from _walk(attributes=nested, path=config_path, provider=provider)
        providers = spec.get("providers")
        if isinstance(providers, Mapping):
            for name, schema in providers.items():
                props = schema.get("properties") if isinstance(schema, Mapping) else None
                if isinstance(props, Mapping):
                    yield from _walk(attributes=props, path=config_path, provider=name)


def _covered(*, metadata: Mapping[str, Any], path: str, provider: str | None) -> bool:
    if is_covered(path=path, fields=list(effective_secret_fields(metadata=metadata))):
        return True
    if is_covered(path=path, fields=list(metadata.get(DECLARED_FIELDS_KEY, []))):
        return True
    if provider is not None:
        by_provider: Mapping[str, Mapping[str, list[str]]] = metadata.get(DECLARED_BY_PROVIDER_KEY, {})
        for providers in by_provider.values():
            if is_covered(path=path, fields=providers.get(provider, [])):
                return True
    return False


def _undeclared(*, metadata: Mapping[str, Any]) -> list[tuple[str, str | None]]:
    marked = set(metadata.get(NO_REFERENCES_KEY, []))
    return [
        (path, provider)
        for path, provider in _walk(attributes=metadata.get("attributes", {}))
        if is_credential_looking(name=path.rsplit(".", 1)[-1])
        and path not in marked
        and not _covered(metadata=metadata, path=path, provider=provider)
    ]


class TestInventoryDetection:
    """The inventory check must fail for an undeclared credential-looking field."""

    ATTRIBUTES: ClassVar[dict[str, Any]] = {
        "host": {"type": "string"},
        "db_password": {"type": "string"},
        "provider_config": {
            "type": "json",
            "providers": {"a": {"properties": {"api_secret": {"type": "string"}, "index_name": {"type": "string"}}}},
        },
    }

    def test_undeclared_credential_fields_are_reported(self) -> None:
        found = _undeclared(metadata={"attributes": self.ATTRIBUTES})
        assert ("db_password", None) in found
        assert ("provider_config.api_secret", "a") in found
        assert all("index_name" not in path for path, _ in found)

    def test_declaration_clears_the_finding(self) -> None:
        metadata = {
            "attributes": self.ATTRIBUTES,
            "secret_fields": ["db_password"],
            "secret_fields_by_provider": {"provider": {"a": ["provider_config.api_secret"]}},
        }
        assert _undeclared(metadata=metadata) == []

    def test_no_references_marker_clears_the_finding(self) -> None:
        metadata = {"attributes": self.ATTRIBUTES, "no_references": ["db_password", "provider_config.api_secret"]}
        assert _undeclared(metadata=metadata) == []

    def test_sensitive_floor_clears_the_finding(self) -> None:
        attributes = {"db_password": {"type": "string", "sensitive": True}}
        assert _undeclared(metadata={"attributes": attributes}) == []


@pytest.mark.parametrize("operator_cls", OPERATORS, ids=lambda cls: cls.short_name)
class TestSecretFieldInventory:
    def test_every_credential_looking_field_is_declared_or_marked(self, operator_cls: type[AbstractOperator]) -> None:
        undeclared = _undeclared(metadata=operator_cls.get_metadata())
        assert not undeclared, (
            f"{operator_cls.short_name}: credential-looking fields neither declared secret-capable "
            f"nor marked no_references: {undeclared}"
        )

    def test_naming_fields_are_never_declared(self, operator_cls: type[AbstractOperator]) -> None:
        metadata = operator_cls.get_metadata()
        declared = list(metadata.get(DECLARED_FIELDS_KEY, []))
        for providers in metadata.get(DECLARED_BY_PROVIDER_KEY, {}).values():
            for paths in providers.values():
                declared.extend(paths)
        declared.extend(effective_secret_fields(metadata=metadata))
        offenders = [p for p in declared if p.rsplit(".", 1)[-1] in NAMING_FIELD_NAMES]
        assert not offenders, f"{operator_cls.short_name}: naming fields declared secret-capable: {offenders}"

    def test_declaration_keys_have_expected_types(self, operator_cls: type[AbstractOperator]) -> None:
        metadata = operator_cls.get_metadata()
        assert isinstance(metadata.get(DECLARED_FIELDS_KEY, []), list)
        for selector, providers in metadata.get(DECLARED_BY_PROVIDER_KEY, {}).items():
            assert isinstance(selector, str)
            for provider, paths in providers.items():
                assert isinstance(provider, str)
                assert all(isinstance(p, str) for p in paths)

    def test_marked_fields_are_not_also_declared(self, operator_cls: type[AbstractOperator]) -> None:
        metadata = operator_cls.get_metadata()
        marked = set(metadata.get(NO_REFERENCES_KEY, []))
        declared = set(metadata.get(DECLARED_FIELDS_KEY, []))
        for providers in metadata.get(DECLARED_BY_PROVIDER_KEY, {}).values():
            for paths in providers.values():
                declared.update(paths)
        assert not (marked & declared)


class TestInventoryCoverage:
    def test_inventory_operators_are_registered(self) -> None:
        registered = {cls.short_name for cls in OPERATORS}
        assert INVENTORY_OPERATORS <= registered

    @pytest.mark.parametrize("short_name", sorted(INVENTORY_OPERATORS - {"acl_operator"}))
    def test_inventory_operator_declares_fields(self, short_name: str) -> None:
        metadata = next(cls for cls in OPERATORS if cls.short_name == short_name).get_metadata()
        assert metadata.get(DECLARED_FIELDS_KEY) or metadata.get(DECLARED_BY_PROVIDER_KEY)

    @pytest.mark.parametrize(
        ("short_name", "provider", "expected"),
        [
            (op, provider, fields)
            for op, providers in INVENTORY_PROVIDER_FIELDS.items()
            for provider, fields in providers.items()
        ],
    )
    def test_spec_inventory_fields_are_declared(self, short_name: str, provider: str, expected: set[str]) -> None:
        metadata = next(cls for cls in OPERATORS if cls.short_name == short_name).get_metadata()
        declared: set[str] = set()
        for providers in metadata[DECLARED_BY_PROVIDER_KEY].values():
            declared.update(path.rsplit(".", 1)[-1] for path in providers.get(provider, []))
        assert expected <= declared, f"{short_name}/{provider}: missing {sorted(expected - declared)}"

    def test_acl_credentials_object_is_declared(self) -> None:
        metadata = next(cls for cls in OPERATORS if cls.short_name == "acl_operator").get_metadata()
        assert "credentials.*" in metadata[DECLARED_FIELDS_KEY]

    def test_storage_credentials_object_is_declared(self) -> None:
        metadata = next(cls for cls in OPERATORS if cls.short_name == "storage_output").get_metadata()
        assert "destination_config.credentials.*" in metadata[DECLARED_FIELDS_KEY]

    def test_naming_fields_are_not_secret_capable_for_vectordb_and_storage(self) -> None:
        vectordb = next(cls for cls in OPERATORS if cls.short_name == "vectordb").get_metadata()
        paths = {
            p for providers in vectordb[DECLARED_BY_PROVIDER_KEY].values() for ps in providers.values() for p in ps
        }
        assert not {"provider_config.index_name", "provider_config.collection_name"} & paths
        storage = next(cls for cls in OPERATORS if cls.short_name == "storage_output").get_metadata()
        paths = {p for providers in storage[DECLARED_BY_PROVIDER_KEY].values() for ps in providers.values() for p in ps}
        assert not {p for p in paths if p.rsplit(".", 1)[-1] in {"key_prefix", "prefix", "root_path", "folder_path"}}

    def test_ingest_declarations_are_scoped_per_provider(self) -> None:
        metadata = next(cls for cls in OPERATORS if cls.short_name == "ingest_source").get_metadata()
        by_provider = metadata[DECLARED_BY_PROVIDER_KEY]["provider"]
        assert by_provider["web"] == []
        assert by_provider["filesystem"] == []
        assert "provider_config.secret_key" not in by_provider["dropbox"]
        assert "provider_config.secret_key" in by_provider["s3"]

    def test_operators_outside_inventory_accept_no_references(self) -> None:
        for short_name in ("doc_quality", "merge", "branching", "noop", "redaction", "ml_enrichment"):
            cls = next((c for c in OPERATORS if c.short_name == short_name), None)
            if cls is None:
                continue
            metadata = cls.get_metadata()
            assert effective_secret_fields(metadata=metadata) == []
            assert not metadata.get(DECLARED_BY_PROVIDER_KEY)

    def test_abstract_operator_default_declares_nothing(self) -> None:
        assert AbstractOperator.get_metadata()[DECLARED_FIELDS_KEY] == []

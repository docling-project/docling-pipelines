# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Unit tests for the secret-capable field declaration helpers (task B.2)."""

from typing import ClassVar

import pytest
from pydantic import BaseModel, Field

from docpipe.core.operators.secret_fields import (
    build_provider_secret_fields,
    effective_secret_fields,
    is_covered,
    is_credential_looking,
    provider_no_references,
    provider_secret_fields,
)


class _Config(BaseModel):
    SECRET_FIELDS: ClassVar[tuple[str, ...]] = ("host", "password")
    NO_REFERENCES: ClassVar[tuple[str, ...]] = ("legacy_token",)

    host: str = "localhost"
    password: str | None = None
    legacy_token: str | None = None
    api_key: str | None = Field(default=None, json_schema_extra={"sensitive": True})
    index_name: str = "idx"


_SCHEMA = {"properties": {"api_key": {"sensitive": True}, "legacy_token": {"sensitive": True}, "host": {}}}


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("password", True),
        ("secret_key", True),
        ("client_secret", True),
        ("jwt_token", True),
        ("access_token", True),
        ("credentials", True),
        ("credentials_json", True),
        ("api_key", True),
        ("token", True),
        ("index_name", False),
        ("max_tokens", False),
        ("docling_tokenizer", False),
        ("key_prefix", False),
        ("host", False),
    ],
)
def test_is_credential_looking(name: str, expected: bool) -> None:
    assert is_credential_looking(name=name) is expected


def test_provider_secret_fields_combines_declaration_and_sensitive_floor() -> None:
    paths = provider_secret_fields(config_cls=_Config, provider_schema=_SCHEMA, prefix="provider_config")
    # api_key comes from the sensitive floor, host and password from the declaration;
    # legacy_token is sensitive but marked no_references, so it is removed.
    assert paths == ["provider_config.api_key", "provider_config.host", "provider_config.password"]


def test_provider_no_references_returns_dotted_paths() -> None:
    assert provider_no_references(config_cls=_Config, prefix="provider_config") == ["provider_config.legacy_token"]


def test_unknown_declared_field_is_rejected() -> None:
    class Bad(BaseModel):
        SECRET_FIELDS: ClassVar[tuple[str, ...]] = ("missing",)
        present: str = ""

    with pytest.raises(ValueError, match="not a field"):
        provider_secret_fields(config_cls=Bad, provider_schema={}, prefix="p")


def test_naming_field_declaration_is_rejected() -> None:
    class Bad(BaseModel):
        SECRET_FIELDS: ClassVar[tuple[str, ...]] = ("index_name",)
        index_name: str = ""

    with pytest.raises(ValueError, match="naming field"):
        provider_secret_fields(config_cls=Bad, provider_schema={}, prefix="p")


def test_alias_names_are_accepted() -> None:
    class WithAlias(BaseModel):
        SECRET_FIELDS: ClassVar[tuple[str, ...]] = ("legacy_path",)
        SECRET_FIELD_ALIASES: ClassVar[tuple[str, ...]] = ("legacy_path",)
        real: str = ""

    assert provider_secret_fields(config_cls=WithAlias, provider_schema={}, prefix="p") == ["p.legacy_path"]


def test_nested_declared_path_is_validated_by_top_level_field() -> None:
    class Nested(BaseModel):
        SECRET_FIELDS: ClassVar[tuple[str, ...]] = ("vlm_pipeline.engine_options.api_key",)
        vlm_pipeline: dict | None = None

    assert provider_secret_fields(config_cls=Nested, provider_schema={}, prefix="p") == [
        "p.vlm_pipeline.engine_options.api_key"
    ]


def test_build_provider_secret_fields_scopes_by_provider() -> None:
    class A(BaseModel):
        SECRET_FIELDS: ClassVar[tuple[str, ...]] = ("secret_key",)
        secret_key: str = ""

    class B(BaseModel):
        name: str = ""

    result = build_provider_secret_fields(selector="provider", prefix="provider_config", classes={"a": A, "b": B})
    assert result == {"provider": {"a": ["provider_config.secret_key"], "b": []}}


def test_effective_secret_fields_unions_declarations_and_floor() -> None:
    metadata = {
        "secret_fields": ["credentials.*"],
        "secret_fields_by_provider": {"provider": {"s3": ["provider_config.secret_key"], "web": []}},
        "no_references": ["token"],
        "attributes": {
            "token": {"sensitive": True},
            "password": {"sensitive": True},
            "nested": {"properties": {"api_key": {"sensitive": True}}},
        },
    }
    assert effective_secret_fields(metadata=metadata, providers={"provider": "s3"}) == [
        "credentials.*",
        "nested.api_key",
        "password",
        "provider_config.secret_key",
    ]
    assert "provider_config.secret_key" not in effective_secret_fields(metadata=metadata, providers={"provider": "web"})
    assert "provider_config.secret_key" not in effective_secret_fields(metadata=metadata)


def test_effective_secret_fields_empty_when_nothing_declared() -> None:
    assert effective_secret_fields(metadata={}) == []
    assert effective_secret_fields(metadata={"secret_fields": [], "attributes": {"a": {"type": "string"}}}) == []


def test_is_covered_wildcard() -> None:
    assert is_covered(path="credentials.client_secret", fields=["credentials.*"])
    assert is_covered(path="credentials", fields=["credentials"])
    assert not is_covered(path="credentialsx.a", fields=["credentials.*"])
    assert not is_covered(path="other.a", fields=["credentials.*"])

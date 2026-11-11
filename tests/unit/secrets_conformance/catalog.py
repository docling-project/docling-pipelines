# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""The conformance catalog: one explicit entry for every declared secret-capable field (task E.1).

``declared_fields()`` reads the declarations from the operators' own metadata. ``ENTRIES`` is written by hand.
``missing_entries()`` is the gate: a declared field with no entry, or an entry for a field that is no longer
declared, is reported with the operator and the field.
"""

import copy
import enum
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from docpipe.core.operators.operator_registry import get_docpipe_operators
from docpipe.core.operators.secret_fields import (
    DECLARED_BY_PROVIDER_KEY,
    effective_secret_fields,
)

FieldKey = tuple[str, str | None, str | None, str]
"""``(operator, selector, provider, declared_path)``; selector and provider are None for operator-wide fields."""

WATSONX_BASE = {"container_kind": "project", "container_id": "00000000-0000-0000-0000-000000000000"}


class Kind(enum.Enum):
    """What the resolved value looks like, which decides the canary shape."""

    SECRET = "secret"  # pragma: allowlist secret
    DESTINATION = "destination"
    STRUCTURED = "structured"
    PLAIN = "plain"
    PATH = "path"


@dataclass(frozen=True)
class Case:
    """One ``(operator, selector, provider)`` and the fields declared for it.

    Attributes:
        base: Valid configuration without any declared field of ``prefix``.
        defaults: Literal values for the other declared fields, relative to ``prefix``. They are kept in the
            configuration unless they are the field under test, so the operator still constructs.
        fields: Declared field name relative to ``prefix`` and the kind of its value.
        env: Environment variables the operator constructor needs.
        companions: Extra literals, relative to ``prefix``, set only while one field is under test. For a field
            that is valid only next to another (a token path needs OAuth credentials), where ``defaults`` would
            conflict with the field's alternatives.
        row: Columns added to (or replacing) the default one-row input table, for operators that read more
            than ``id``, ``name`` and ``content``.
    """

    operator: str
    selector: str | None
    provider: str | None
    prefix: str
    base: Mapping[str, Any]
    fields: Mapping[str, Kind]
    defaults: Mapping[str, Any] = field(default_factory=dict)
    env: Mapping[str, str] = field(default_factory=dict)
    row: Mapping[str, Any] = field(default_factory=dict)
    companions: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)

    def key(self, *, name: str) -> FieldKey:
        """Return the catalog key of the field ``name``."""
        return (self.operator, self.selector, self.provider, f"{self.prefix}{name}")


@dataclass(frozen=True)
class Entry:
    """A case plus one field of it: the unit the scenarios run for."""

    case: Case
    name: str

    @property
    def key(self) -> FieldKey:
        """The catalog key."""
        return self.case.key(name=self.name)

    @property
    def concrete_path(self) -> str:
        """The config path to set; a trailing ``.*`` is made concrete with a canary key name."""
        return f"{self.case.prefix}{self.name}".replace("*", "canary_key")

    @property
    def operator(self) -> str:
        """The operator's ``short_name``."""
        return self.case.operator

    @property
    def kind(self) -> Kind:
        """The kind of the field's value."""
        return self.case.fields[self.name]

    @property
    def test_id(self) -> str:
        """A readable parametrization id."""
        operator, _, provider, path = self.key
        return f"{operator}:{provider or 'any'}:{path}"

    def build_config(self, *, reference: str) -> dict[str, Any]:
        """Return the node configuration with ``reference`` at the field under test."""
        config = copy.deepcopy(dict(self.case.base))
        for name, literal in {**self.case.defaults, **self.case.companions.get(self.name, {})}.items():
            if name != self.name:
                _set(config=config, path=f"{self.case.prefix}{name}", value=literal)
        _set(config=config, path=self.concrete_path, value=reference)
        return config


def _set(*, config: dict[str, Any], path: str, value: Any) -> None:
    node = config
    *parents, leaf = path.split(".")
    for segment in parents:
        child = node.get(segment)
        if not isinstance(child, dict):
            child = {}
            node[segment] = child
        node = child
    node[leaf] = value


_CLASSIFIER_ROW = {"name": "a.pdf"}
_DOC_ROW = {"path": "in.md", "name": "in.md", "content": None}

S, D, J, P, F = Kind.SECRET, Kind.DESTINATION, Kind.STRUCTURED, Kind.PLAIN, Kind.PATH

_PC = "provider_config."
_SUM = "summarization.provider_config."
_DEST = "destination_config.provider_config."
_S3_DEFAULTS = {
    "bucket": "b",
    "access_key": "ak",
    "secret_key": "sk",  # pragma: allowlist secret
    "region": "us-east-1",
}
_LLM_BASE = {"provider_config": {"model_name": "m"}}
_LLM_DEFAULTS = {"api_key": "k", "api_base": "http://h.example.test"}
_WX_DEFAULTS = {"api_key": "k", "url": "http://h.example.test", **WATSONX_BASE}
_WX_ENV = {"WATSONX_CONTAINER_ID": "00000000-0000-0000-0000-000000000000"}
_ACL_ROW = {"path": "a.txt", "source_id": "sid", "metadata": '{"provider": "sharepoint"}'}
_MODE = {"mode": "processed_content"}

CASES: tuple[Case, ...] = (
    # --- operator-wide declarations ---
    Case(
        "acl_operator",
        None,
        None,
        "",
        {},
        {"credentials": S, "credentials.*": S},
        defaults={"credentials.client_id": "c", "credentials.client_secret": "s", "credentials.tenant_id": "t"},
        row=_ACL_ROW,
    ),
    Case(
        "chunker",
        None,
        None,
        _PC,
        {"provider": "docling_serve"},
        {"api_base": D, "api_key": S},
        defaults={"api_base": "http://h.example.test", "api_key": "k"},
    ),
    Case(
        "storage_output",
        None,
        None,
        "destination_config.",
        {**_MODE, "destination_config": {"provider": "s3", "provider_config": {**_S3_DEFAULTS, "key_prefix": "p/"}}},
        {"credentials": S, "credentials.*": S},
    ),
    # --- ingest_source ---
    Case(
        "ingest_source",
        "provider",
        "s3",
        _PC,
        {"provider": "s3"},
        {"access_key": S, "secret_key": S, "bucket": P, "region": P, "endpoint_url": D},
        defaults={**_S3_DEFAULTS, "endpoint_url": "http://h.example.test"},
    ),
    Case(
        "ingest_source",
        "provider",
        "ibm_cos",
        _PC,
        {"provider": "ibm_cos"},
        {"access_key": S, "secret_key": S, "bucket": P, "region": P, "endpoint_url": D},
        defaults={**_S3_DEFAULTS, "endpoint_url": "https://h.example.test"},
    ),
    Case(
        "ingest_source",
        "provider",
        "google_drive",
        _PC,
        {"provider": "google_drive"},
        {
            "credentials_json": J,
            "credentials_path": F,
            "service_account_json": J,
            "service_account_json_path": F,
            "token_path": F,
        },
        companions={"token_path": {"credentials_path": "oauth_client.json"}},
    ),
    Case(
        "ingest_source",
        "provider",
        "onedrive",
        _PC,
        {"provider": "onedrive"},
        {"client_id": S, "client_secret": S, "drive_id": P, "tenant_id": P},
        defaults={"client_id": "c", "client_secret": "s", "drive_id": "d", "tenant_id": "t"},
    ),
    Case(
        "ingest_source",
        "provider",
        "sharepoint",
        _PC,
        {"provider": "sharepoint"},
        {"client_id": S, "client_secret": S, "document_library_id": P, "tenant_id": P},
        defaults={"client_id": "c", "client_secret": "s", "document_library_id": "d", "tenant_id": "t"},
    ),
    Case(
        "ingest_source",
        "provider",
        "box_driver",
        _PC,
        {"provider": "box_driver"},
        {"credentials_json": J, "credentials_json_path": F, "credentials_path": F},
    ),
    Case(
        "ingest_source",
        "provider",
        "dropbox",
        _PC,
        {"provider": "dropbox"},
        {"access_token": S, "app_key": S, "app_secret": S, "refresh_token": S},
        defaults={"app_key": "k", "app_secret": "s", "refresh_token": "r"},
    ),
    # --- storage_output ---
    Case(
        "storage_output",
        "destination_config.provider",
        "box",
        _DEST,
        {
            **_MODE,
            "destination_config": {
                "provider": "box",
                "provider_config": {"credentials_json_path": "box_config.json", "folder_id": "0"},
            },
        },
        {"credentials_path": F},
    ),
    Case(
        "storage_output",
        "destination_config.provider",
        "google_drive",
        _DEST,
        {**_MODE, "destination_config": {"provider": "google_drive", "provider_config": {"folder_id": "f"}}},
        {"credentials_path": F, "service_account_json_path": F, "token_path": F},
        companions={"token_path": {"credentials_path": "oauth_client.json"}},
    ),
    Case(
        "storage_output",
        "destination_config.provider",
        "s3",
        _DEST,
        {**_MODE, "destination_config": {"provider": "s3"}},
        {"access_key": S, "endpoint_url": D, "secret_key": S},
        defaults={
            "bucket": "b",
            "key_prefix": "p/",
            "access_key": "ak",
            "secret_key": "sk",  # pragma: allowlist secret
            "endpoint_url": "http://h.example.test",
        },
    ),
    Case(
        "storage_output",
        "destination_config.provider",
        "ibm_cos",
        _DEST,
        {**_MODE, "destination_config": {"provider": "ibm_cos"}},
        {"access_key": S, "endpoint_url": D, "secret_key": S},
        defaults={
            "bucket": "b",
            "key_prefix": "p/",
            "access_key": "ak",
            "secret_key": "sk",  # pragma: allowlist secret
            "endpoint_url": "https://h.example.test",
        },
    ),
    Case(
        "storage_output",
        "destination_config.provider",
        "sharepoint",
        _DEST,
        {**_MODE, "destination_config": {"provider": "sharepoint"}},
        {"client_id": S, "client_secret": S, "tenant_id": P},
        defaults={"client_id": "c", "client_secret": "s", "tenant_id": "t", "drive_id": "d"},
    ),
    Case(
        "storage_output",
        "destination_config.provider",
        "onedrive",
        _DEST,
        {**_MODE, "destination_config": {"provider": "onedrive"}},
        {"client_id": S, "client_secret": S, "tenant_id": P},
        defaults={"client_id": "c", "client_secret": "s", "tenant_id": "t", "drive_id": "d"},
    ),
    # --- vectordb ---
    Case(
        "vectordb",
        "provider",
        "opensearch",
        _PC,
        {"provider": "opensearch", "provider_config": {"index_name": "i"}, "add_sparse_vector": True},
        {"aws_region": P, "host": D, "jwt_token": S, "password": S, "username": P},
        defaults={"host": "http://h.example.test:9200"},
        companions={"password": {"username": "u"}, "username": {"password": "p"}},
        row={"doc_id_hash": "h"},
    ),
    Case(
        "vectordb",
        "provider",
        "milvus",
        _PC,
        {"provider": "milvus", "provider_config": {"collection_name": "c", "auth_type": "token"}},
        {"database": P, "host": D, "password": S, "token": S, "uri": D, "username": P},
        defaults={"uri": "http://h.example.test:19530", "username": "u", "token": "t"},
    ),
    # --- LLM-backed operators ---
    *(
        Case(
            operator,
            "provider",
            "litellm",
            _PC,
            {"provider": "litellm", **_LLM_BASE},
            {"api_base": D, "api_key": S},
            defaults=_LLM_DEFAULTS,
            row=_CLASSIFIER_ROW if operator == "document_classifier" else {},
        )
        for operator in ("embeddings", "document_classifier")
    ),
    *(
        Case(
            operator,
            "provider",
            "watsonx",
            _PC,
            {"provider": "watsonx", **_LLM_BASE},
            {"api_base": D, "api_key": S, "url": D},
            defaults=_WX_DEFAULTS,
            env=_WX_ENV,
            row=_CLASSIFIER_ROW if operator == "document_classifier" else {},
        )
        for operator in ("embeddings", "document_classifier")
    ),
    Case(
        "chunker",
        "summarization.provider",
        "litellm",
        _SUM,
        {"summarization": {"provider": "litellm", "provider_config": {"model_name": "m"}}},
        {"api_base": D, "api_key": S},
        defaults=_LLM_DEFAULTS,
    ),
    Case(
        "chunker",
        "summarization.provider",
        "watsonx",
        _SUM,
        {"summarization": {"provider": "watsonx", "provider_config": {"model_name": "m"}}},
        {"api_base": D, "api_key": S, "url": D},
        defaults=_WX_DEFAULTS,
        env=_WX_ENV,
    ),
    *(
        Case(
            "pii_and_hap",
            selector,
            "litellm",
            f"{prefix}_config.",
            {selector: "litellm", f"{prefix}_config": {"model_id": "m"}, "provider_config": {"model_id": "m"}},
            {"api_base": D, "api_key": S},
            defaults=_LLM_DEFAULTS,
        )
        for selector, prefix in (
            ("provider", "provider"),
            ("pii_provider", "pii_provider"),
            ("hap_provider", "hap_provider"),
        )
    ),
    *(
        Case(
            "pii_and_hap",
            selector,
            "watsonx",
            f"{prefix}_config.",
            {selector: "watsonx", f"{prefix}_config": {"model_id": "m"}, "provider_config": {"model_id": "m"}},
            {"api_key": S, "url": D},
            defaults=_WX_DEFAULTS,
            env=_WX_ENV,
        )
        for selector, prefix in (
            ("provider", "provider"),
            ("pii_provider", "pii_provider"),
            ("hap_provider", "hap_provider"),
        )
    ),
    # --- extract_operator ---
    Case(
        "extract_operator",
        "text_extraction.provider",
        "docling_library",
        "text_extraction.provider_config.vlm_pipeline.engine_options.",
        {"text_extraction": {"provider": "docling_library", "provider_config": {}}},
        {"api_base": D, "api_key": S},
        defaults={"api_base": "http://h.example.test", "api_key": "k"},
        row=_DOC_ROW,
    ),
    Case(
        "extract_operator",
        "text_extraction.provider",
        "docling_serve",
        "text_extraction.provider_config.",
        {"text_extraction": {"provider": "docling_serve", "provider_config": {}}},
        {"api_key": S, "base_url": D},
        defaults={"api_key": "k", "base_url": "http://h.example.test"},
        row=_DOC_ROW,
    ),
    *(
        Case(
            "extract_operator",
            "entity_extraction.provider",
            provider,
            "entity_extraction.provider_config.",
            {
                "text_extraction": {"provider": "docling_library", "provider_config": {}},
                "entity_extraction": {
                    "provider": provider,
                    "provider_config": {"model_id": "m"},
                    "custom_schema": {"title": "str"},
                },
            },
            fields,
            defaults=defaults,
            env=env,
            row=_DOC_ROW,
        )
        for provider, fields, defaults, env in (
            ("litellm", {"api_base": D, "api_key": S}, _LLM_DEFAULTS, {}),
            ("watsonx", {"api_base": D, "api_key": S, "url": D}, _WX_DEFAULTS, _WX_ENV),
        )
    ),
)


_GDRIVE = "ingest_source:google_drive:provider_config."
_PARENT = "A plain-string canary cannot become a mapping: the resolver rejects it, so only resolution is exercised."
_JSON_FORM = "build_config_from_operator_params ignores the inline JSON forms, so no client is built from them."
_FILE_CHECK = "The missing-file check fails before any faked client is constructed."
_NO_FAKE = "Reached only through a client the fakes do not cover."
_DOCLING_LIB = (
    "Docling parses a local file and no remote client is faked; the engine options are used only for remote VLM calls."
)

NOT_REACHED: dict[tuple[str, str], str] = {
    **{
        (test_id, scenario): _PARENT
        for test_id in ("acl_operator:any:credentials", "storage_output:any:destination_config.credentials")
        for scenario in ("client_failure", "mid_run_failure")
    },
    **{
        (f"{_GDRIVE}{name}", scenario): _JSON_FORM
        for name in ("credentials_json", "service_account_json")
        for scenario in ("client_failure", "mid_run_failure")
    },
    (f"{_GDRIVE}credentials_path", "client_failure"): _FILE_CHECK,
    (f"{_GDRIVE}service_account_json_path", "client_failure"): _FILE_CHECK,
    (f"{_GDRIVE}service_account_json_path", "mid_run_failure"): _NO_FAKE,
    (f"{_GDRIVE}token_path", "mid_run_failure"): _NO_FAKE,
    ("ingest_source:box_driver:provider_config.credentials_json_path", "client_failure"): _FILE_CHECK,
    ("ingest_source:box_driver:provider_config.credentials_path", "client_failure"): _FILE_CHECK,
    (
        "storage_output:google_drive:destination_config.provider_config.credentials_path",
        "client_failure",
    ): _FILE_CHECK,
    (
        "storage_output:google_drive:destination_config.provider_config.service_account_json_path",
        "client_failure",
    ): _FILE_CHECK,
    **{
        (f"extract_operator:docling_library:text_extraction.provider_config.vlm_pipeline.engine_options.{name}", s): (
            _DOCLING_LIB
        )
        for name in ("api_base", "api_key")
        for s in ("client_failure", "mid_run_failure")
    },
}
"""Scenario/field pairs whose client stage the fakes cannot reach, with the reason.

The test asserts every other pair does reach a faked client, and that a pair listed here still does not:
an entry that starts being reached must be removed, so the list cannot hide coverage that exists.
"""


SUCCESS_NEEDS_REAL_SERVER: dict[str, str] = {
    "acl_operator:any:credentials": _PARENT,
    "storage_output:any:destination_config.credentials": _PARENT,
    "extract_operator:docling_serve:text_extraction.provider_config.api_key": (
        "The do-nothing fake client returns no HTTP response, so the extraction legitimately fails."
    ),
    "extract_operator:docling_serve:text_extraction.provider_config.base_url": (
        "The do-nothing fake client returns no HTTP response, so the extraction legitimately fails."
    ),
}
"""Entries whose success scenario ends in a node failure the fakes cannot avoid; the sinks are scanned regardless."""


def entries() -> dict[FieldKey, Entry]:
    """Return every catalog entry by key."""
    return {case.key(name=name): Entry(case=case, name=name) for case in CASES for name in case.fields}


def declared_fields() -> set[FieldKey]:
    """Return every ``(operator, selector, provider, path)`` the operators declare as secret-capable."""
    declared: set[FieldKey] = set()
    for operator_class in get_docpipe_operators():
        metadata = operator_class.get_metadata()
        short_name = operator_class.short_name
        declared.update((short_name, None, None, path) for path in effective_secret_fields(metadata=metadata))
        by_provider: Mapping[str, Mapping[str, list[str]]] = metadata.get(DECLARED_BY_PROVIDER_KEY, {})
        for selector, providers in by_provider.items():
            for provider, paths in providers.items():
                declared.update((short_name, selector, provider, path) for path in paths)
    return declared


def missing_entries(*, declared: set[FieldKey], catalog: Mapping[FieldKey, Entry]) -> list[str]:
    """Return one message per declared field without an entry and per entry without a declaration."""
    problems: list[str] = []
    for operator, selector, provider, path in sorted(declared - set(catalog), key=str):
        scope = f" (provider {provider}, selected by {selector})" if provider else ""
        problems.append(f"{operator}: secret-capable field '{path}'{scope} has no conformance entry")
    for operator, _selector, provider, path in sorted(set(catalog) - declared, key=str):
        scope = f" (provider {provider})" if provider else ""
        problems.append(f"{operator}: conformance entry for '{path}'{scope} matches no declared secret-capable field")
    return problems

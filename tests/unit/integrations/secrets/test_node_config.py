# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Unit tests for per-node scoping of secret resolution (design D6, task B.4)."""

from typing import Any

import pytest

from docpipe.core.constants.constants import DocpipeConstants
from docpipe.core.operators.functional.noop import NOOPOperator
from docpipe.core.operators.ingest.ingest_source import IngestSourceOperator
from docpipe.integrations.secrets.node_config import (
    ResolvedNodeConfig,
    prepare_operator_config,
    resolve_operator_config,
    reveal_secret_values,
)
from docpipe.integrations.secrets.resolver import SecretResolutionError
from docpipe.integrations.secrets.secret_provider import clear_providers, register_provider
from docpipe.integrations.secrets.secret_value import SecretValue
from docpipe.utils.infrastructure.config_utils import DocpipeConfigLoader
from tests.unit.integrations.secrets.test_resolver import RecordingProvider

CANARY = "CANARY_NODE_SECRET_12345"  # pragma: allowlist secret
REFERENCE = "vault://fake/s3/creds#secret_key"  # pragma: allowlist secret


@pytest.fixture(autouse=True)
def _isolate():
    clear_providers()
    DocpipeConfigLoader.reset()
    yield
    clear_providers()
    DocpipeConfigLoader.reset()


@pytest.fixture
def provider() -> RecordingProvider:
    fake = RecordingProvider(secrets={"s3/creds": {"secret_key": CANARY}})
    register_provider(name="fake", provider=fake)
    return fake


def _allow_all() -> None:
    DocpipeConfigLoader._config = {"secrets": {"vault": {"allowed_paths": ["*:**"]}}}


def _ingest_config(*, secret_key: str = REFERENCE) -> dict[str, Any]:
    return {
        "name": "ingest_a",
        "provider": "s3",
        "provider_config": {"bucket": "b", "access_key": "AKIA", "secret_key": secret_key},
    }


class TestResolveOperatorConfig:
    def test_resolves_own_declared_field(self, provider: RecordingProvider) -> None:
        _allow_all()

        resolved = resolve_operator_config(operator_class=IngestSourceOperator, config=_ingest_config())

        secret = resolved["provider_config"]["secret_key"]
        assert isinstance(secret, SecretValue)
        assert secret.reveal() == CANARY
        assert provider.calls == [("s3/creds", "secret_key")]

    def test_config_without_references_costs_no_request(self, provider: RecordingProvider) -> None:
        config = _ingest_config(secret_key="plain-value")  # pragma: allowlist secret

        assert resolve_operator_config(operator_class=IngestSourceOperator, config=config) is config
        assert provider.calls == []

    def test_reference_in_shared_keys_is_neither_resolved_nor_rejected(self, provider: RecordingProvider) -> None:
        _allow_all()
        config = {
            "name": "noop_a",
            DocpipeConstants.FLOW_DEFINITION: {DocpipeConstants.DAG: [{"config": {"secret_key": REFERENCE}}]},
            "ingest_source": {"provider_config": {"secret_key": REFERENCE}},
        }

        assert resolve_operator_config(operator_class=NOOPOperator, config=config) is config
        assert provider.calls == []

    def test_reference_in_undeclared_own_field_is_rejected(self, provider: RecordingProvider) -> None:
        _allow_all()

        with pytest.raises(SecretResolutionError):
            resolve_operator_config(operator_class=NOOPOperator, config={"name": "noop_a", "token": REFERENCE})

        assert provider.calls == []

    def test_override_entry_for_another_node_is_skipped(self, provider: RecordingProvider) -> None:
        """A per-node override dict merged into every node belongs to the node it names."""
        _allow_all()
        config = {
            "name": "noop_a",
            DocpipeConstants.FLOW_DEFINITION: {
                DocpipeConstants.DAG: [{"id": "n1", "name": "ingest_a", "operator": "ingest_source"}],
            },
            "ingest_a": {"provider_config": {"secret_key": REFERENCE}},
        }

        assert resolve_operator_config(operator_class=NOOPOperator, config=config) is config
        assert provider.calls == []

    def test_deny_by_default_without_allowed_paths(self, provider: RecordingProvider) -> None:
        with pytest.raises(SecretResolutionError, match="not permitted"):
            resolve_operator_config(operator_class=IngestSourceOperator, config=_ingest_config())

        assert provider.calls == []

    def test_validating_flow_makes_no_request(self, provider: RecordingProvider) -> None:
        _allow_all()
        config = {**_ingest_config(), DocpipeConstants.VALIDATING_FLOW: True}

        assert resolve_operator_config(operator_class=IngestSourceOperator, config=config) is config
        assert provider.calls == []


class TestPrepareOperatorConfig:
    def test_returns_plain_values_marked_as_resolved(self, provider: RecordingProvider) -> None:
        _allow_all()

        prepared = prepare_operator_config(operator_class=IngestSourceOperator, config=_ingest_config())

        assert isinstance(prepared, ResolvedNodeConfig)
        assert prepared["provider_config"]["secret_key"] == CANARY
        assert type(prepared["provider_config"]["secret_key"]) is str

    def test_second_pass_makes_no_provider_call(self, provider: RecordingProvider) -> None:
        _allow_all()
        prepared = prepare_operator_config(operator_class=IngestSourceOperator, config=_ingest_config())

        again = prepare_operator_config(operator_class=IngestSourceOperator, config=prepared)

        assert again is prepared
        assert len(provider.calls) == 1

    def test_resolved_secret_containing_reference_text_is_not_resolved_again(self, provider: RecordingProvider) -> None:
        fake = RecordingProvider(secrets={"s3/creds": {"secret_key": "vault://other/path#key"}})
        clear_providers()
        register_provider(name="fake", provider=fake)
        _allow_all()

        prepared = prepare_operator_config(operator_class=IngestSourceOperator, config=_ingest_config())
        prepare_operator_config(operator_class=IngestSourceOperator, config=prepared)

        assert prepared["provider_config"]["secret_key"] == "vault://other/path#key"  # pragma: allowlist secret
        assert len(fake.calls) == 1

    def test_does_not_change_the_callers_config(self, provider: RecordingProvider) -> None:
        _allow_all()
        config = _ingest_config()

        prepare_operator_config(operator_class=IngestSourceOperator, config=config)

        assert config["provider_config"]["secret_key"] == REFERENCE

    def test_config_without_references_is_returned_as_is(self, provider: RecordingProvider) -> None:
        config = {"name": "noop_a"}

        assert prepare_operator_config(operator_class=NOOPOperator, config=config) is config


class TestRevealSecretValues:
    def test_reveals_nested_values_in_a_copy(self) -> None:
        config = {"a": SecretValue(value="one"), "b": {"c": [SecretValue(value="two"), "three"]}}

        revealed = reveal_secret_values(config=config)

        assert revealed == {"a": "one", "b": {"c": ["two", "three"]}}
        assert isinstance(config["a"], SecretValue)

    def test_config_without_secret_values_is_returned_as_is(self) -> None:
        config = {"a": "x"}

        assert reveal_secret_values(config=config) is config


class TestDirectConstruction:
    def test_direct_construction_receives_resolved_plain_values(self, provider: RecordingProvider) -> None:
        _allow_all()
        seen: dict[str, Any] = {}

        class Recording(NOOPOperator):
            short_name = "noop"

            def __init__(self, config: dict[str, Any]) -> None:
                seen.update(config)
                super().__init__(config)

        Recording.get_metadata = staticmethod(  # type: ignore[method-assign]
            lambda: {**NOOPOperator.get_metadata(), "secret_fields": ["token"]}
        )

        Recording(config={"name": "noop_a", "token": REFERENCE})

        assert seen["token"] == CANARY
        assert type(seen["token"]) is str
        assert len(provider.calls) == 1

    def test_direct_construction_is_denied_by_default(self, provider: RecordingProvider) -> None:
        with pytest.raises(SecretResolutionError, match="not permitted"):
            IngestSourceOperator(config=_ingest_config())

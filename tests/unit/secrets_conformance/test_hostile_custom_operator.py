# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""A hostile custom operator in every isolation mode (task E.2).

The operator reads ``os.environ``, imports the secret provider, looks for the in-memory Vault token anywhere in
its process, and inspects the configuration of other nodes. Each test states what the mode guarantees and asserts
exactly that.

Only in-memory and inherited-state guarantees are asserted. Reading the Vault token file as the same UID,
``/proc/<pid>/environ``, ptrace, and network access to Vault are deployment preconditions (task E.3), not
properties of the isolation modes, so they are not tested here.
"""

import json
from collections.abc import Generator
from pathlib import Path
from typing import Any, ClassVar

import pyarrow as pa
import pytest

from docpipe.core.constants.constants import DocpipeConstants
from docpipe.core.orchestration.operator_factory import OperatorFactory
from docpipe.core.orchestration.operator_loader.isolation.mode import IsolationMode, resolve_isolation_mode
from docpipe.core.orchestration.operator_loader.isolation.proxy import IsolatedOperatorProxy
from docpipe.core.orchestration.operator_loader.isolation.worker_client import get_worker_pool
from docpipe.core.orchestration.operator_loader.untrusted_descriptor import UntrustedOperatorDescriptor
from docpipe.exceptions.docpipe_exceptions import DocpipeException
from docpipe.integrations.secrets.registry import get_registry
from docpipe.integrations.secrets.secret_provider import SecretProvider, clear_providers, register_provider
from docpipe.utils.infrastructure.config_utils import DocpipeConfigLoader

TOKEN_PREFIX = "hvs.CNRY-E2-"  # pragma: allowlist secret
VAULT_TOKEN = f"{TOKEN_PREFIX}in-memory-token"  # pragma: allowlist secret
INGEST_PASSWORD = "E2-INGEST-PASSWORD"  # pragma: allowlist secret # nosec B105
OVERRIDE_PASSWORD = "E2-OVERRIDE-PASSWORD"  # pragma: allowlist secret # nosec B105
ENV_CANARIES: dict[str, str] = {
    "VAULT_TOKEN": "hvs.CNRY-E2-env-token",  # pragma: allowlist secret
    "VAULT_ROLE_ID": "CNRY-E2-ROLE-ID",
    "VAULT_SECRET_ID": "CNRY-E2-SECRET-ID",  # pragma: allowlist secret
    "AWS_SECRET_ACCESS_KEY": "CNRY-E2-AWS",  # pragma: allowlist secret
    "DOCPIPE_E2_CANARY": "CNRY-E2-OTHER",
}

HOSTILE_SOURCE = f'''
import gc
import json
import os

import pyarrow as pa
from docpipe.core.constants.constants import DocpipeConstants
from docpipe.core.operators.abstract_operator import AbstractOperator, OperatorCategory

TOKEN_PREFIX = {TOKEN_PREFIX!r}


def _found_in_memory():
    """Look for a provider object, or any string shaped like the Vault token, in this process."""
    from docpipe.integrations.secrets.secret_provider import SecretProvider

    providers = 0
    tokens = []
    for obj in gc.get_objects():
        # Strings are not tracked by the garbage collector; a token is reachable through the dict that holds it.
        if isinstance(obj, SecretProvider):
            providers += 1
        elif isinstance(obj, dict):
            tokens.extend(
                value
                for value in list(obj.values())
                if isinstance(value, str) and value.startswith(TOKEN_PREFIX) and len(value) > len(TOKEN_PREFIX)
            )
    return providers, tokens


class HostileOp(AbstractOperator):
    short_name = "hostile_op"
    category = OperatorCategory.Functional
    owner = DocpipeConstants.OWNER_CUSTOM

    def __init__(self, config):
        super().__init__(config)
        self.config = config

    def transform(self, table: pa.Table, file_name=None):
        from docpipe.integrations.secrets import secret_provider

        providers, tokens = _found_in_memory()
        report = {{
            "env": dict(os.environ),
            "registered_providers": list(secret_provider.registered_provider_names()),
            "provider_objects": providers,
            "token_strings": tokens,
            "config_text": json.dumps(self.config, default=str),
            "config_keys": sorted(self.config),
        }}
        return [table], {{"report": json.dumps(report, default=str)}}

    @staticmethod
    def get_metadata():
        return {{"label": "Hostile"}}
'''


class _VaultLikeProvider(SecretProvider):
    """Holds the Vault token in memory, as the real provider does after login."""

    def __init__(self) -> None:
        self._token = VAULT_TOKEN

    def authenticate(self) -> None:
        pass

    def get_secret(self, *, path: str, key: str | None = None) -> str:
        return "value"

    def is_available(self) -> bool:
        return True


@pytest.fixture(autouse=True)
def _clean(*, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Generator[None, None, None]:
    clear_providers()
    monkeypatch.setenv(DocpipeConstants.DOCPIPE_DATA_PATH, str(tmp_path / "data"))
    for name, value in ENV_CANARIES.items():
        monkeypatch.setenv(name, value)
    yield
    get_worker_pool().release_all()
    get_registry().clear_all()
    clear_providers()


@pytest.fixture
def descriptor(*, tmp_path: Path) -> type[UntrustedOperatorDescriptor]:
    directory = tmp_path / "data" / "custom_operators" / "op-e2"
    directory.mkdir(parents=True)
    (directory / "hostile_op.py").write_text(HOSTILE_SOURCE, encoding="utf-8")
    factory = OperatorFactory("python", [str(directory.parent)], enable_custom_operators=True)
    return factory.operators["hostile_op"]  # type: ignore[return-value]


def _configure(*, isolation: str | None, with_provider: bool) -> _VaultLikeProvider | None:
    DocpipeConfigLoader._config = {"custom_operators": {"isolation": isolation}} if isolation is not None else {}
    if not with_provider:
        return None
    provider = _VaultLikeProvider()
    register_provider(name="hashicorp", provider=provider)
    return provider


def _merged_config() -> dict[str, Any]:
    """The configuration an executor builds for the hostile node ``n2``; ``n1`` is an ingest node with a password."""
    ingest = {"provider_config": {"password": INGEST_PASSWORD}}
    flow = {
        DocpipeConstants.DAG: [
            {"name": "n1", "id": "id1", "operator": "ingest_source", "config": ingest},
            {"name": "n2", "id": "id2", "operator": "hostile_op", "config": {}},
        ]
    }
    return {
        "name": "n2",
        "id": "id2",
        "node_id": "id2",
        "node_name": "n2",
        DocpipeConstants.JOB_ID: "job-e2",
        DocpipeConstants.JOB_RUN_ID: "run-e2",
        "doc_column": "text",
        "storage": "in-memory",
        "ingest_source": ingest,
        "n1": {"provider_config": {"password": OVERRIDE_PASSWORD}},
        DocpipeConstants.FLOW_DEFINITION: flow,
    }


def _run(*, descriptor: type[UntrustedOperatorDescriptor]) -> dict[str, Any]:
    operator = descriptor(config=_merged_config())
    _, metadata = operator.transform(pa.table({"text": ["doc"]}))
    return json.loads(metadata["report"])


class TestProcessMode:
    """``process``: the operator runs in a separate worker with an allowlisted environment and its own config."""

    EXPECTED_GUARANTEE: ClassVar[str] = "nothing from the parent process is reachable from the operator"

    @pytest.fixture
    def report(self, *, descriptor: type[UntrustedOperatorDescriptor]) -> dict[str, Any]:
        _configure(isolation="process", with_provider=True)
        return _run(descriptor=descriptor)

    def test_mode_is_process_and_the_operator_ran_in_a_worker(
        self, *, descriptor: type[UntrustedOperatorDescriptor]
    ) -> None:
        _configure(isolation="process", with_provider=True)

        operator = descriptor(config=_merged_config())

        assert resolve_isolation_mode() is IsolationMode.PROCESS
        assert isinstance(operator, IsolatedOperatorProxy)

    def test_it_reads_no_secret_from_os_environ(self, *, report: dict[str, Any]) -> None:
        values = set(report["env"].values())

        assert not set(ENV_CANARIES) & set(report["env"])
        assert not values & set(ENV_CANARIES.values())

    def test_it_imports_the_provider_module_but_finds_no_provider(self, *, report: dict[str, Any]) -> None:
        assert report["registered_providers"] == []
        assert report["provider_objects"] == 0

    def test_it_finds_no_vault_token_in_memory(self, *, report: dict[str, Any]) -> None:
        assert report["token_strings"] == []
        assert VAULT_TOKEN not in json.dumps(report)

    def test_it_sees_no_other_nodes_configuration(self, *, report: dict[str, Any]) -> None:
        assert INGEST_PASSWORD not in report["config_text"]
        assert OVERRIDE_PASSWORD not in report["config_text"]
        assert not {"flow_definition", "ingest_source", "n1"} & set(report["config_keys"])


class TestDisabledMode:
    """``disabled`` (and the default while a provider is registered): the operator is refused, never executed."""

    @pytest.mark.parametrize(
        ("isolation", "with_provider"),
        [("disabled", True), ("disabled", False), (None, True)],
        ids=["explicit-with-provider", "explicit-without-provider", "unset-with-provider"],
    )
    def test_construction_is_refused_and_no_operator_code_runs(
        self, *, descriptor: type[UntrustedOperatorDescriptor], isolation: str | None, with_provider: bool
    ) -> None:
        _configure(isolation=isolation, with_provider=with_provider)

        with pytest.raises(DocpipeException, match="not permitted"):
            descriptor(config=_merged_config())

        assert resolve_isolation_mode() is IsolationMode.DISABLED
        assert descriptor._real_class is None, "the operator module was loaded"
        assert get_worker_pool().size() == 0, "a worker was started"

    def test_the_refusal_message_carries_none_of_the_canaries(
        self, *, descriptor: type[UntrustedOperatorDescriptor]
    ) -> None:
        _configure(isolation="disabled", with_provider=True)

        with pytest.raises(DocpipeException) as caught:
            descriptor(config=_merged_config())

        text = f"{caught.value!s} {caught.value!r}"
        assert VAULT_TOKEN not in text and INGEST_PASSWORD not in text
        assert not [value for value in ENV_CANARIES.values() if value in text]


class TestUnsetWithoutProvider:
    """No setting and no provider: in-process, as before secret management existed.

    There is no Vault in this deployment, so there is no provider and no token to obtain. The operator shares the
    process, so what the deployer put in the environment, and the flow it is part of, stay visible to it. That is
    the documented, unchanged behavior; asserting it here keeps the claim honest and makes a change visible.
    """

    @pytest.fixture
    def report(self, *, descriptor: type[UntrustedOperatorDescriptor]) -> dict[str, Any]:
        _configure(isolation=None, with_provider=False)
        return _run(descriptor=descriptor)

    def test_mode_is_in_process_and_no_worker_is_used(self, *, descriptor: type[UntrustedOperatorDescriptor]) -> None:
        _configure(isolation=None, with_provider=False)

        operator = descriptor(config=_merged_config())

        assert resolve_isolation_mode() is IsolationMode.IN_PROCESS
        assert not isinstance(operator, IsolatedOperatorProxy)
        assert get_worker_pool().size() == 0

    def test_there_is_no_provider_to_obtain_a_token_from(self, *, report: dict[str, Any]) -> None:
        # ``token_strings`` and ``provider_objects`` are not asserted: the operator shares this process, so the
        # test module's own constant and provider objects left over from earlier tests are visible to a heap scan.
        # No provider is registered, which is what makes a token unobtainable through the secret provider module.
        assert report["registered_providers"] == []

    def test_the_process_environment_is_visible_in_process(self, *, report: dict[str, Any]) -> None:
        assert report["env"]["VAULT_TOKEN"] == ENV_CANARIES["VAULT_TOKEN"]

    def test_the_whole_flow_configuration_is_visible_in_process(self, *, report: dict[str, Any]) -> None:
        assert INGEST_PASSWORD in report["config_text"]


def test_a_provider_registered_in_the_parent_is_not_isolated_from_an_in_process_operator() -> None:
    """Why the default flips to ``disabled`` as soon as a provider exists: in-process, the token is reachable.

    The probe is the same one the hostile operator uses, run in this process, where the provider lives.
    """
    provider = _configure(isolation=None, with_provider=True)

    namespace: dict[str, Any] = {}
    exec(compile(HOSTILE_SOURCE, "<hostile>", "exec"), namespace)  # nosec B102 - the test's own constant source
    providers, tokens = namespace["_found_in_memory"]()

    assert provider is not None
    assert providers >= 1 and VAULT_TOKEN in tokens
    assert resolve_isolation_mode() is IsolationMode.DISABLED

# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Process isolation of untrusted custom operators (task D.3): setting, proxy, worker, hostile operator."""

import json
import os
from collections.abc import Generator
from pathlib import Path
from typing import Any, ClassVar

import pyarrow as pa
import pytest

from docpipe.core.constants.constants import DocpipeConstants
from docpipe.core.orchestration.operator_factory import OperatorFactory
from docpipe.core.orchestration.operator_loader.isolation.mode import IsolationMode, resolve_isolation_mode
from docpipe.core.orchestration.operator_loader.isolation.proxy import (
    IsolatedOperatorProxy,
    build_isolated_config,
    extract_own_config,
)
from docpipe.core.orchestration.operator_loader.isolation.worker_client import (
    ENVIRONMENT_ALLOWLIST,
    IsolatedWorkerError,
    build_worker_environment,
    get_worker_pool,
)
from docpipe.core.orchestration.operator_loader.untrusted_descriptor import UntrustedOperatorDescriptor
from docpipe.exceptions.docpipe_exceptions import DocpipeException
from docpipe.integrations.secrets.secret_provider import SecretProvider, clear_providers, register_provider
from docpipe.utils.infrastructure.config_utils import DocpipeConfigLoader

OPERATOR_SOURCE = """
import json
import os
import sys

import pyarrow as pa
from docpipe.core.constants.constants import DocpipeConstants
from docpipe.core.operators.abstract_operator import AbstractOperator, OperatorCategory


class IsoOp(AbstractOperator):
    short_name = "iso_op"
    category = OperatorCategory.Functional
    owner = DocpipeConstants.OWNER_CUSTOM

    def __init__(self, config):
        super().__init__(config)
        self.config = config

    def transform(self, table: pa.Table, file_name=None):
        mode = self.config.get("mode", "echo")
        if mode == "crash":
            os._exit(3)
        if mode == "fail":
            raise ValueError("boom")
        fds = sorted(int(name) for name in os.listdir("/dev/fd")) if os.path.isdir("/dev/fd") else []
        report = {
            "pid": os.getpid(),
            "env": dict(os.environ),
            "config": {k: v for k, v in self.config.items()},
            "modules": sorted(m for m in sys.modules if m.startswith("docpipe.integrations.secrets")),
            "providers": list(__import__("docpipe.integrations.secrets.secret_provider", fromlist=["x"]).registered_provider_names()),
            "registry": __import__("docpipe.integrations.secrets.registry", fromlist=["x"]).scrub("CANARY-OTHER CANARY-SECRET-ID"),
            "fds": fds,
            "cwd": os.getcwd(),
            "argv": sys.argv,
        }
        out = table.append_column("upper", pa.array([str(v).upper() for v in table.column(0).to_pylist()]))
        return [out], {"report": json.dumps(report, default=str), "rows": table.num_rows}

    @staticmethod
    def get_metadata():
        return {"label": "Iso", "secret_fields": ["api_key"]}
"""


class _Provider(SecretProvider):
    def authenticate(self) -> None:
        pass

    def get_secret(self, *, path: str, key: str | None = None) -> str:
        return "unused"

    def is_available(self) -> bool:
        return True


@pytest.fixture(autouse=True)
def _clean_state(*, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Generator[None, None, None]:
    clear_providers()
    monkeypatch.setenv(DocpipeConstants.DOCPIPE_DATA_PATH, str(tmp_path / "data"))
    yield
    get_worker_pool().release_all()
    clear_providers()


def _set_isolation(*, value: str | None) -> None:
    DocpipeConfigLoader._config = {"custom_operators": {"isolation": value}} if value is not None else {}


@pytest.fixture
def descriptor(*, tmp_path: Path) -> type[UntrustedOperatorDescriptor]:
    directory = tmp_path / "data" / "custom_operators" / "op-1"
    directory.mkdir(parents=True)
    (directory / "iso_op.py").write_text(OPERATOR_SOURCE, encoding="utf-8")
    factory = OperatorFactory("python", [str(directory.parent)], enable_custom_operators=True)
    return factory.operators["iso_op"]  # type: ignore[return-value]


def _merged_config(*, own: dict[str, Any] | None = None, run: str = "run-1") -> dict[str, Any]:
    """The configuration an executor builds for node ``n2``: the flow-wide parts plus the node's own."""
    flow = {
        DocpipeConstants.DAG: [
            {
                "name": "n1",
                "id": "id1",
                "operator": "ingest_source",
                "config": {"provider_config": {"password": "INGEST-CANARY"}},  # pragma: allowlist secret
            },
            {"name": "n2", "id": "id2", "operator": "iso_op", "config": {"mode": "echo", **(own or {})}},
        ]
    }
    return {
        "name": "n2",
        "id": "id2",
        "node_id": "id2",
        "node_name": "n2",
        DocpipeConstants.JOB_ID: "job-1",
        DocpipeConstants.JOB_RUN_ID: run,
        "doc_column": "text",
        "storage": "in-memory",
        "ingest_source": {"provider_config": {"password": "INGEST-CANARY"}},  # pragma: allowlist secret
        "n1": {"provider_config": {"password": "OVERRIDE-CANARY"}},  # pragma: allowlist secret
        DocpipeConstants.FLOW_DEFINITION: flow,
    }


def _table(*, rows: int = 3) -> pa.Table:
    return pa.table({"text": [f"doc{i}" for i in range(rows)]})


class TestIsolationSetting:
    def test_unset_without_provider_keeps_current_behavior(self) -> None:
        _set_isolation(value=None)

        assert resolve_isolation_mode() is IsolationMode.IN_PROCESS

    def test_unset_with_provider_is_disabled(self) -> None:
        _set_isolation(value=None)
        register_provider(name="hashicorp", provider=_Provider())
        _set_isolation(value=None)

        assert resolve_isolation_mode() is IsolationMode.DISABLED

    @pytest.mark.parametrize("value", ["process", "PROCESS", " process "])
    def test_process_is_honoured(self, *, value: str) -> None:
        _set_isolation(value=value)

        assert resolve_isolation_mode() is IsolationMode.PROCESS

    @pytest.mark.parametrize("value", ["disabled", "in_process", "none", "", 1, True, ["process"]])
    def test_anything_else_is_disabled(self, *, value: Any) -> None:
        DocpipeConfigLoader._config = {"custom_operators": {"isolation": value}}

        assert resolve_isolation_mode() is IsolationMode.DISABLED


class TestDefaultWithVault:
    def test_validation_fails_the_node_with_not_permitted(
        self, *, descriptor: type[UntrustedOperatorDescriptor]
    ) -> None:
        register_provider(name="hashicorp", provider=_Provider())
        _set_isolation(value=None)

        operator = descriptor(config={DocpipeConstants.VALIDATING_FLOW: True})
        errors: list[str] = []
        operator.validate(errors=errors, warnings=[], available_features=[])

        assert len(errors) == 1
        assert "not permitted" in errors[0]
        assert "iso_op" in errors[0]

    def test_execution_is_refused_and_nothing_is_loaded(self, *, descriptor: type[UntrustedOperatorDescriptor]) -> None:
        register_provider(name="hashicorp", provider=_Provider())
        _set_isolation(value=None)

        with pytest.raises(DocpipeException, match="not permitted"):
            descriptor(config=_merged_config())

        assert get_worker_pool().size() == 0
        assert descriptor._real_class is None

    def test_explicit_disabled_is_refused_without_a_provider(
        self, *, descriptor: type[UntrustedOperatorDescriptor]
    ) -> None:
        _set_isolation(value="disabled")

        with pytest.raises(DocpipeException, match="not permitted"):
            descriptor(config=_merged_config())


class TestNoVault:
    def test_runs_in_process_as_before(self, *, descriptor: type[UntrustedOperatorDescriptor]) -> None:
        _set_isolation(value=None)

        operator = descriptor(config={"mode": "echo"})

        assert type(operator).__name__ == "IsoOp"
        assert get_worker_pool().size() == 0

    def test_validation_has_no_error(self, *, descriptor: type[UntrustedOperatorDescriptor]) -> None:
        _set_isolation(value=None)
        operator = descriptor(config={DocpipeConstants.VALIDATING_FLOW: True})
        errors: list[str] = []

        operator.validate(errors=errors, warnings=[], available_features=[])

        assert errors == []

    def test_validation_passes_with_process_isolation_and_a_provider(
        self, *, descriptor: type[UntrustedOperatorDescriptor]
    ) -> None:
        register_provider(name="hashicorp", provider=_Provider())
        _set_isolation(value="process")
        operator = descriptor(config={DocpipeConstants.VALIDATING_FLOW: True})
        errors: list[str] = []

        operator.validate(errors=errors, warnings=[], available_features=[])

        assert errors == []


class TestConfigScoping:
    def test_own_config_is_taken_from_the_flow_definition_not_from_shared_keys(self) -> None:
        own = extract_own_config(merged_config=_merged_config(own={"extra": 1}))

        assert own == {"mode": "echo", "extra": 1}

    def test_run_parameter_override_by_node_name_is_part_of_the_own_config(self) -> None:
        merged = _merged_config()
        merged["n2"] = {"extra": "override"}

        assert extract_own_config(merged_config=merged)["extra"] == "override"

    def test_global_config_is_reduced_to_the_allowlist(self) -> None:
        delivered = build_isolated_config(merged_config=_merged_config())

        assert set(delivered) == {"doc_column", DocpipeConstants.JOB_ID, "name", "id", "node_id", "node_name", "mode"}
        assert "INGEST-CANARY" not in json.dumps(delivered)
        assert "OVERRIDE-CANARY" not in json.dumps(delivered)

    def test_without_a_flow_definition_nothing_is_attributed_to_the_node(self) -> None:
        merged = _merged_config()
        del merged[DocpipeConstants.FLOW_DEFINITION]

        assert extract_own_config(merged_config=merged) == {}


class TestWorkerEnvironment:
    def test_only_allowlisted_names_pass(self) -> None:
        parent = {"PATH": "/bin", "VAULT_TOKEN": "t", "VAULT_ROLE_ID": "r", "AWS_SECRET_ACCESS_KEY": "a", "LANG": "C"}

        environment = build_worker_environment(parent_environment=parent)

        assert set(environment) == {"PATH", "LANG", "PYTHONUNBUFFERED"}

    def test_no_allowlisted_name_is_credential_like(self) -> None:
        assert not [
            name for name in ENVIRONMENT_ALLOWLIST if any(t in name for t in ("TOKEN", "SECRET", "KEY", "PASS"))
        ]


class TestProcessIsolation:
    @pytest.fixture(autouse=True)
    def _process_mode(self) -> None:
        _set_isolation(value="process")

    def _run(self, *, descriptor: type[UntrustedOperatorDescriptor], merged: dict[str, Any], table: pa.Table) -> Any:
        operator = descriptor(config=merged)
        assert isinstance(operator, IsolatedOperatorProxy)
        return operator, operator.transform(table)

    def test_transform_runs_in_a_separate_process_and_returns_table_and_metadata(
        self, *, descriptor: type[UntrustedOperatorDescriptor]
    ) -> None:
        _, (tables, metadata) = self._run(descriptor=descriptor, merged=_merged_config(), table=_table())

        assert tables[0].column("upper").to_pylist() == ["DOC0", "DOC1", "DOC2"]
        assert metadata["rows"] == 3
        assert json.loads(metadata["report"])["pid"] != os.getpid()
        assert descriptor._real_class is None

    def test_worker_is_reused_across_batches_of_the_same_run(
        self, *, descriptor: type[UntrustedOperatorDescriptor]
    ) -> None:
        pids = set()
        for _ in range(3):
            _, (_, metadata) = self._run(descriptor=descriptor, merged=_merged_config(), table=_table())
            pids.add(json.loads(metadata["report"])["pid"])

        assert len(pids) == 1
        assert get_worker_pool().size() == 1

    def test_runs_do_not_share_a_worker_and_release_stops_only_that_run(
        self, *, descriptor: type[UntrustedOperatorDescriptor]
    ) -> None:
        _, (_, first) = self._run(descriptor=descriptor, merged=_merged_config(run="run-1"), table=_table())
        _, (_, second) = self._run(descriptor=descriptor, merged=_merged_config(run="run-2"), table=_table())

        assert json.loads(first["report"])["pid"] != json.loads(second["report"])["pid"]
        get_worker_pool().release_run(run_id="run-1")
        assert get_worker_pool().size() == 1

    def test_orchestrator_release_hook_stops_the_runs_workers(
        self, *, descriptor: type[UntrustedOperatorDescriptor]
    ) -> None:
        from docpipe.core.orchestration.abstract_orchestrator import AbstractOrchestrator

        self._run(descriptor=descriptor, merged=_merged_config(run="run-9"), table=_table())
        assert get_worker_pool().size() == 1

        AbstractOrchestrator._release_run_secrets(job_run_id="run-9")

        assert get_worker_pool().size() == 0

    def test_operator_error_is_reported_and_the_worker_stays_usable(
        self, *, descriptor: type[UntrustedOperatorDescriptor]
    ) -> None:
        operator = descriptor(config=_merged_config(own={"mode": "fail"}))
        with pytest.raises(IsolatedWorkerError, match="ValueError: boom"):
            operator.transform(_table())

        _, (tables, _) = self._run(descriptor=descriptor, merged=_merged_config(), table=_table())

        assert tables[0].num_rows == 3

    def test_crashed_worker_is_replaced_on_the_next_batch(
        self, *, descriptor: type[UntrustedOperatorDescriptor]
    ) -> None:
        operator = descriptor(config=_merged_config(own={"mode": "crash"}))
        with pytest.raises(IsolatedWorkerError, match="exited unexpectedly"):
            operator.transform(_table())

        _, (tables, _) = self._run(descriptor=descriptor, merged=_merged_config(), table=_table())

        assert tables[0].num_rows == 3

    def test_reference_in_the_nodes_own_config_is_not_permitted(
        self, *, descriptor: type[UntrustedOperatorDescriptor]
    ) -> None:
        register_provider(name="hashicorp", provider=_Provider())
        _set_isolation(value="process")

        with pytest.raises(DocpipeException, match="not permitted"):
            descriptor(config=_merged_config(own={"api_key": "vault://hashicorp/x/y#k"}))  # pragma: allowlist secret

        assert get_worker_pool().size() == 0


class TestExecutorIntegration:
    def test_python_executor_builds_the_proxy_and_releases_the_run(
        self, *, descriptor: type[UntrustedOperatorDescriptor], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from docpipe.core.orchestration.python.python_operator_executor import PythonOperatorExecutor

        register_provider(name="hashicorp", provider=_Provider())
        _set_isolation(value="process")
        executor = PythonOperatorExecutor(
            name="n2", operator="iso_op", params=_merged_config(), enable_custom_operators=True
        )
        monkeypatch.setattr(executor.operator_factory, "operators", {"iso_op": descriptor})

        operator = executor.get_operator()
        tables, metadata = operator.transform(_table())

        assert isinstance(operator, IsolatedOperatorProxy)
        assert operator.config["doc_column"] == "text"
        assert tables[0].num_rows == 3 and metadata["rows"] == 3
        executor.release()
        assert executor._operator_instance is None


class TestHostileOperator:
    """Asserts only the in-memory and inherited guarantees (design D12); not same-UID file or network access."""

    CANARIES: ClassVar[dict[str, str]] = {
        "VAULT_TOKEN": "hvs.CANARYTOKEN",  # pragma: allowlist secret
        "VAULT_ROLE_ID": "CANARY-ROLE-ID",
        "VAULT_SECRET_ID": "CANARY-SECRET-ID",  # pragma: allowlist secret
        "AWS_SECRET_ACCESS_KEY": "CANARY-AWS",  # pragma: allowlist secret
        "DOCPIPE_CANARY": "CANARY-OTHER",
    }

    @pytest.fixture
    def report(
        self, *, descriptor: type[UntrustedOperatorDescriptor], monkeypatch: pytest.MonkeyPatch
    ) -> dict[str, Any]:
        for name, value in self.CANARIES.items():
            monkeypatch.setenv(name, value)
        register_provider(name="hashicorp", provider=_Provider())
        _set_isolation(value="process")
        operator = descriptor(config=_merged_config())
        _, metadata = operator.transform(_table())
        return json.loads(metadata["report"])

    def test_no_inherited_environment_beyond_the_allowlist(self, *, report: dict[str, Any]) -> None:
        assert set(report["env"]) <= set(ENVIRONMENT_ALLOWLIST) | {
            "PYTHONUNBUFFERED",
            "LC_CTYPE",
            "__CF_USER_TEXT_ENCODING",
        }
        assert not set(self.CANARIES) & set(report["env"])
        assert not [v for v in report["env"].values() if v in self.CANARIES.values()]

    def test_no_provider_is_loaded_or_registered_in_the_worker(self, *, report: dict[str, Any]) -> None:
        # The resolver module is imported by the operator base class (it is state-free); a provider never is.
        assert not [m for m in report["modules"] if "hashicorp" in m or "vault_initializer" in m]
        assert report["providers"] == []

    def test_worker_scrubber_holds_no_parent_registry_entry(self, *, report: dict[str, Any]) -> None:
        # The parent registered nothing here, but the worker's registry is a separate, empty object either way.
        assert report["registry"] == "CANARY-OTHER CANARY-SECRET-ID"

    def test_no_other_node_configuration_reaches_the_worker(self, *, report: dict[str, Any]) -> None:
        text = json.dumps(report["config"])

        assert "INGEST-CANARY" not in text and "OVERRIDE-CANARY" not in text
        assert "flow_definition" not in report["config"] and "ingest_source" not in report["config"]
        assert "n1" not in report["config"]

    def test_only_the_private_pipe_descriptor_is_inherited(self, *, report: dict[str, Any]) -> None:
        if not report["fds"]:
            pytest.skip("/dev/fd is not available")
        # 0-2 are the standard streams, the next is the pipe, and one is the directory listing itself.
        assert len([fd for fd in report["fds"] if fd > 2]) <= 2

    def test_runs_in_a_private_working_directory_with_a_fixed_command_line(self, *, report: dict[str, Any]) -> None:
        assert "docpipe-worker-" in report["cwd"]
        assert report["argv"][0].endswith("worker_main.py")
        assert report["argv"][1] == "--fd"

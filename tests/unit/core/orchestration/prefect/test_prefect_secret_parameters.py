# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Verification of task D.5: Prefect carries references only, never a resolved secret.

The secret-management capability requires that task parameters, flow parameters, cache
keys and persisted results of distributed orchestration hold references only, and that a
``SecretValue`` is never a task argument or a flow parameter (design D13).

This module does not fix anything: on ``main`` the parameters were already unresolved and
``persist_result=False`` and ``NO_CACHE`` were already set. It pins that state.

Two layers:

* ``TestTaskPersistenceSettings``: the tasks that receive per-node configuration are
  defined with ``persist_result=False`` and ``NO_CACHE``.
* ``TestCanaryFlowUnderPrefect``: one real flow run under Prefect's ephemeral server. A
  canary operator declares ``api_key`` as secret-capable and the flow supplies it as a
  ``vault://`` reference. The test first proves the canary WAS resolved (inside the task),
  then scans what the orchestrator recorded: the arguments of every flow and task call,
  and the parameters, task inputs and states stored by the Prefect API.
"""

from __future__ import annotations

import asyncio
import functools
import inspect
import json
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Callable
from unittest.mock import MagicMock, patch

import pyarrow as pa
import pytest

from docpipe.core.operators import operator_registry
from docpipe.core.operators.abstract_operator import AbstractOperator, OperatorCategory
from docpipe.core.orchestration.operator_factory import OperatorFactoryProvider
from docpipe.core.orchestration.prefect import prefect_engine
from docpipe.core.orchestration.prefect.prefect_engine import PrefectEngine
from docpipe.core.orchestration.python.python_orchestrator import PythonOrchestrator
from docpipe.integrations.secrets import SecretValue
from docpipe.integrations.secrets.secret_provider import SecretProvider, clear_providers, register_provider
from docpipe.utils.infrastructure.config_utils import DocpipeConfigLoader

CANARY = "CANARY_PREFECT_PARAMETER_9f3a61"  # pragma: allowlist secret
REFERENCE = "vault://fake/prefect/canary#api_key"  # pragma: allowlist secret
OPERATOR_NAME = "prefect_canary_operator"
NODE_NAME = "canary_node"


# ---------------------------------------------------------------------------
# Scanner
# ---------------------------------------------------------------------------


def find_secret_exposures(*, value: Any, path: str = "$", canary: str = CANARY) -> list[str]:
    """Return the paths in ``value`` that hold a ``SecretValue`` or the canary text.

    Walks dicts, lists, tuples and sets. Any other object is checked through ``repr``.
    """
    if isinstance(value, SecretValue):
        return [f"{path}: SecretValue"]
    if isinstance(value, dict):
        found: list[str] = []
        for key, item in value.items():
            found += find_secret_exposures(value=key, path=f"{path}.<key>", canary=canary)
            found += find_secret_exposures(value=item, path=f"{path}[{key!r}]", canary=canary)
        return found
    if isinstance(value, (list, tuple, set, frozenset)):
        found = []
        for index, item in enumerate(value):
            found += find_secret_exposures(value=item, path=f"{path}[{index}]", canary=canary)
        return found
    if isinstance(value, (str, bytes)):
        text = value if isinstance(value, str) else value.decode("utf-8", errors="replace")
        return [f"{path}: canary text"] if canary in text else []
    try:
        text = repr(value)
    except Exception:  # nosec B110 - an unrepresentable leaf holds no canary text
        return []
    return [f"{path}: canary text in repr"] if canary in text else []


class TestScannerSanity:
    """The scanner must flag what it claims to flag, or the negative checks prove nothing."""

    def test_flags_secret_value(self) -> None:
        assert find_secret_exposures(value={"a": [SecretValue(value=CANARY)]})

    def test_flags_canary_text_in_nested_values(self) -> None:
        assert find_secret_exposures(value={"a": ({"b": f"x{CANARY}y"},)})

    def test_flags_canary_in_a_dict_key(self) -> None:
        assert find_secret_exposures(value={CANARY: 1})

    def test_flags_canary_in_an_object_repr(self) -> None:
        class Holder:
            def __repr__(self) -> str:
                return f"Holder({CANARY})"

        assert find_secret_exposures(value=[Holder()])

    def test_passes_a_reference(self) -> None:
        assert find_secret_exposures(value={"api_key": REFERENCE, "n": 3, "t": pa.table({"a": [1]})}) == []


# ---------------------------------------------------------------------------
# Layer 1: task definition
# ---------------------------------------------------------------------------


def _bare_engine() -> PrefectEngine:
    with patch.object(PrefectEngine, "__init__", lambda self, **kwargs: None):
        engine = PrefectEngine()
    engine.orchestrator = MagicMock()
    engine.batch_manager = MagicMock()
    return engine


def _noop_task_body(op_def: Any = None, *args: Any, **kwargs: Any) -> None:
    return None


class TestTaskPersistenceSettings:
    """Tasks that receive node configuration neither persist results nor cache."""

    def test_default_prefect_settings_disable_persistence(self) -> None:
        settings = _bare_engine()._PrefectEngine__get_prefect_config()
        assert settings["persist_result"] is False

    def test_operator_task_persists_nothing_and_is_not_cached(self) -> None:
        engine = _bare_engine()
        settings = engine._PrefectEngine__get_prefect_config()
        operator_task = engine._PrefectEngine__create_task(
            task_func=_noop_task_body, retries=settings["task_retries"], persist_result=settings["persist_result"]
        )
        assert operator_task.persist_result is False
        assert operator_task.cache_policy == prefect_engine.NO_CACHE

    def test_operator_task_is_not_cached_even_when_defaults_are_used(self) -> None:
        operator_task = _bare_engine()._PrefectEngine__create_task(task_func=_noop_task_body)
        assert operator_task.persist_result is False
        assert operator_task.cache_policy == prefect_engine.NO_CACHE

    def test_non_execution_task_persists_nothing_and_is_not_cached(self) -> None:
        main_task = _bare_engine()._PrefectEngine__create_main_task(main_task=_noop_task_body)
        assert main_task.persist_result is False
        assert main_task.cache_policy == prefect_engine.NO_CACHE


# ---------------------------------------------------------------------------
# Layer 2: a real run
# ---------------------------------------------------------------------------

_seen_api_keys: list[Any] = []


class PrefectCanaryOperator(AbstractOperator):
    """Functional operator whose ``api_key`` may be a Vault reference."""

    short_name = OPERATOR_NAME
    category = OperatorCategory.Functional
    owner = "docpipe"

    def __init__(self, config: dict) -> None:
        super().__init__(config)
        _seen_api_keys.append(config.get("api_key"))

    def transform(self, table: pa.Table) -> tuple[list[pa.Table], dict]:
        return [table], self.create_base_metadata(total_docs_count=len(table))

    @staticmethod
    def get_metadata() -> dict:
        return {
            "short_name": OPERATOR_NAME,
            "description": "Canary for Prefect parameter verification",
            "owner": "docpipe",
            "category": "functional",
            "secret_fields": ["api_key"],
            "attributes": {
                "api_key": {"name": "API key", "type": "string", "required": False, "description": "Credential"}
            },
        }

    @staticmethod
    def is_available() -> bool:
        return True


class _CanaryProvider(SecretProvider):
    def __init__(self) -> None:
        self.calls = 0

    def authenticate(self) -> None:
        pass

    def get_secret(self, *, path: str, key: str | None = None) -> str:
        self.calls += 1
        return CANARY

    def is_available(self) -> bool:
        return True


class _RunRecord:
    """Everything one canary flow run left behind."""

    def __init__(self) -> None:
        self.provider = _CanaryProvider()
        self.flow_name = ""
        self.operator_task_calls: list[dict[str, Any]] = []
        self.flow_calls: list[dict[str, Any]] = []
        self.created_tasks: list[Any] = []
        self.flow_runs: list[Any] = []
        self.task_runs: list[Any] = []


async def _read_runs(*, flow_name: str) -> tuple[list[Any], list[Any]]:
    from prefect import get_client

    async with get_client() as client:
        flow_runs = [run for run in await client.read_flow_runs() if (run.name or "").startswith(flow_name)]
        ids = {run.id for run in flow_runs}
        task_runs = [run for run in await client.read_task_runs() if run.flow_run_id in ids]
    return flow_runs, task_runs


def _recording_task_factory(*, real_task: Callable[..., Any], created: list[Any]) -> Callable[..., Any]:
    def recording_task(*args: Any, **kwargs: Any) -> Callable[..., Any]:
        decorator = real_task(*args, **kwargs)

        def apply(func: Callable[..., Any]) -> Any:
            built = decorator(func)
            created.append(built)
            return built

        return apply

    return recording_task


@pytest.fixture(scope="module")
def canary_run(tmp_path_factory: pytest.TempPathFactory) -> Iterator[_RunRecord]:
    """Run one flow with a canary operator under Prefect and collect what was recorded."""
    record = _RunRecord()
    docs = tmp_path_factory.mktemp("prefect_canary_docs")
    (docs / "a.txt").write_text("hello", encoding="utf-8")
    record.flow_name = f"prefect-canary-{os.getpid()}-{docs.name}"

    # Run output (job data, incremental metadata) is written relative to the working directory.
    previous_cwd = Path.cwd()
    os.chdir(tmp_path_factory.mktemp("prefect_canary_cwd"))
    saved_providers = list(operator_registry._EXTERNAL_OPERATOR_PROVIDERS)
    saved_factories = dict(OperatorFactoryProvider.operator_factories)
    OperatorFactoryProvider.operator_factories.clear()
    operator_registry.register_operator_provider(lambda orchestrator=None: frozenset({PrefectCanaryOperator}))
    clear_providers()
    register_provider(name="fake", provider=record.provider)
    DocpipeConfigLoader._config = {"secrets": {"vault": {"allowed_paths": ["*:**"]}}}
    _seen_api_keys.clear()

    original_inner_task = PythonOrchestrator._inner_task
    original_build_flow = PrefectEngine._build_flow

    @functools.wraps(original_inner_task)
    def recording_inner_task(self: Any, *args: Any, **kwargs: Any) -> Any:
        bound = inspect.signature(original_inner_task).bind(self, *args, **kwargs)
        arguments = {name: value for name, value in bound.arguments.items() if name != "self"}
        record.operator_task_calls.append({"args": (), "kwargs": arguments})
        return original_inner_task(self, *args, **kwargs)

    def recording_build_flow(
        self: Any, *, name: str, flow_impl: Callable[..., Any], timeout_seconds: Any = None
    ) -> Any:
        @functools.wraps(flow_impl)
        def recording_flow_impl(*args: Any, **kwargs: Any) -> Any:
            record.flow_calls.append({"name": name, "args": args, "kwargs": kwargs})
            return flow_impl(*args, **kwargs)

        return original_build_flow(self, name=name, flow_impl=recording_flow_impl, timeout_seconds=timeout_seconds)

    flow_def = {
        "flow_name": record.flow_name,
        "global_config": {
            "doc_column": "content",
            "storage": "in-memory",
            "force_ingest": True,
            "enable_micro_batching": True,
            "micro_batch_size": 1,
        },
        "flow": [
            {
                "type": "ingest_source",
                "name": "ingest",
                "config": {
                    "provider": "filesystem",
                    "provider_config": {"paths": [str(docs)]},
                    "include_filter": "txt",
                    "force_ingest": True,
                },
            },
            {
                "type": OPERATOR_NAME,
                "name": NODE_NAME,
                "depends_on": ["ingest"],
                "config": {"api_key": REFERENCE},
            },
        ],
    }

    try:
        from docpipe.lib.docpipe_flow_manager import DocpipeFlowManager

        with (
            patch.object(PythonOrchestrator, "_inner_task", recording_inner_task),
            patch.object(PrefectEngine, "_build_flow", recording_build_flow),
            patch.object(
                prefect_engine,
                "task",
                _recording_task_factory(real_task=prefect_engine.task, created=record.created_tasks),
            ),
        ):
            DocpipeFlowManager(flow_def=flow_def, enable_execution_reporter=False, configure_logging=False).execute()
        record.flow_runs, record.task_runs = asyncio.run(_read_runs(flow_name=record.flow_name))
        yield record
    finally:
        os.chdir(previous_cwd)
        operator_registry._EXTERNAL_OPERATOR_PROVIDERS[:] = saved_providers
        OperatorFactoryProvider.operator_factories.clear()
        OperatorFactoryProvider.operator_factories.update(saved_factories)
        clear_providers()
        DocpipeConfigLoader.reset()
        _seen_api_keys.clear()


def _serialize(*, value: Any) -> str:
    return json.dumps(value, default=str, sort_keys=True)


class TestCanaryFlowUnderPrefect:
    """One flow run, many assertions: nothing resolved reaches what Prefect records."""

    def test_the_canary_was_resolved_inside_the_task(self, canary_run: _RunRecord) -> None:
        """Without this the absence checks below would prove nothing."""
        assert CANARY in _seen_api_keys or any(
            isinstance(key, SecretValue) and key.reveal() == CANARY for key in _seen_api_keys
        )
        assert canary_run.provider.calls >= 1

    def test_prefect_recorded_the_runs_that_are_scanned(self, canary_run: _RunRecord) -> None:
        names = {run.name for run in canary_run.flow_runs}
        assert canary_run.flow_name in names
        assert f"{canary_run.flow_name}_batch_0" in names
        task_names = {run.name for run in canary_run.task_runs}
        assert NODE_NAME in task_names
        assert canary_run.operator_task_calls
        assert {call["name"] for call in canary_run.flow_calls} >= {canary_run.flow_name, "batch_sub_flow"}

    def test_operator_task_arguments_hold_no_secret(self, canary_run: _RunRecord) -> None:
        for call in canary_run.operator_task_calls:
            assert find_secret_exposures(value=call["kwargs"], path="task.kwargs") == []
            assert find_secret_exposures(value=call["args"], path="task.args") == []

    def test_operator_task_arguments_carry_the_reference(self, canary_run: _RunRecord) -> None:
        node_calls = [call for call in canary_run.operator_task_calls if call["kwargs"]["op_def"]["name"] == NODE_NAME]
        assert node_calls
        for call in node_calls:
            assert call["kwargs"]["op_def"]["config"]["api_key"] == REFERENCE

    def test_flow_parameters_hold_no_secret(self, canary_run: _RunRecord) -> None:
        for call in canary_run.flow_calls:
            assert find_secret_exposures(value=call["kwargs"], path=f"flow[{call['name']}].kwargs") == []
            assert find_secret_exposures(value=call["args"], path=f"flow[{call['name']}].args") == []

    def test_global_config_carries_no_credential_field(self, canary_run: _RunRecord) -> None:
        configs = [call["kwargs"]["global_config"] for call in canary_run.operator_task_calls]
        assert configs
        for global_config in configs:
            ingest_facts = global_config.get("ingest_source", {})
            assert "api_key" not in _serialize(value=ingest_facts)
            assert REFERENCE not in _serialize(value=ingest_facts)

    def test_parameters_stored_by_the_prefect_api_hold_no_secret(self, canary_run: _RunRecord) -> None:
        assert canary_run.flow_runs
        for run in canary_run.flow_runs:
            assert find_secret_exposures(value=run.parameters, path=f"api.flow_run[{run.name}]") == []
            assert CANARY not in _serialize(value=run.parameters)
            assert "SecretValue" not in _serialize(value=run.parameters)

    def test_task_inputs_stored_by_the_prefect_api_hold_no_secret(self, canary_run: _RunRecord) -> None:
        assert canary_run.task_runs
        for run in canary_run.task_runs:
            assert CANARY not in _serialize(value=run.task_inputs)
            assert "SecretValue" not in _serialize(value=run.task_inputs)

    def test_the_api_parameters_hold_the_reference_not_a_value(self, canary_run: _RunRecord) -> None:
        stored = _serialize(value=[run.parameters for run in canary_run.flow_runs])
        assert REFERENCE in stored

    def test_no_run_state_carries_a_persisted_result(self, canary_run: _RunRecord) -> None:
        for run in [*canary_run.flow_runs, *canary_run.task_runs]:
            assert run.state is not None
            assert run.state.data is None, f"{run.name} persisted a result"

    def test_tasks_that_receive_node_configuration_are_not_cached(self, canary_run: _RunRecord) -> None:
        assert canary_run.created_tasks
        for built in canary_run.created_tasks:
            assert built.cache_policy == prefect_engine.NO_CACHE

    def test_operator_tasks_do_not_persist_results(self, canary_run: _RunRecord) -> None:
        operator_tasks = [built for built in canary_run.created_tasks if built.persist_result is not None]
        assert operator_tasks
        for built in operator_tasks:
            assert built.persist_result is False

    def test_the_canary_text_is_in_no_recorded_text(self, canary_run: _RunRecord) -> None:
        recorded = _serialize(
            value={
                "flow_calls": [{"n": c["name"], "a": c["args"], "k": c["kwargs"]} for c in canary_run.flow_calls],
                "task_calls": [{"a": c["args"], "k": c["kwargs"]} for c in canary_run.operator_task_calls],
                "api_flows": [run.parameters for run in canary_run.flow_runs],
                "api_tasks": [run.task_inputs for run in canary_run.task_runs],
            }
        )
        assert CANARY not in recorded

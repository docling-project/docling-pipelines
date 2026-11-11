# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Run one catalog entry through the in-process orchestrator seam and capture every sink (task E.1).

The seam is ``PythonOrchestrator._inner_task`` plus ``_finalize_dag_flow``: the real resolver, executor, operator
constructor, job tracker, lineage observer and file writers run. Prefect is not started (a full flow run costs
about 100 s). Prefect parameters are covered by ``test_prefect_secret_parameters.py`` (D.5, D.6); here the
parameters handed to the node are re-scanned after the run for an in-place write-back of a resolved value.
"""

import enum
import functools
import importlib
import json
import logging
import sys
import traceback
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pyarrow as pa
import pytest
from data_processing.data_access import DataAccessFactory

from docpipe.api.dto.mappers.job_stats_mapper import JobStatsMapper
from docpipe.api.middleware.error_handler import docpipe_exception_handler, generic_exception_handler
from docpipe.core.constants.constants import DocpipeConstants
from docpipe.core.job_management.adapters.services import JobTrackerService
from docpipe.core.job_management.adapters.stores import InMemoryJobStatsStore
from docpipe.core.job_management.application.services import NodeStatsAggregator
from docpipe.core.lineage.adapters.openlineage.observer import OpenLineageExecutionObserver
from docpipe.core.lineage.application.lineage_service import LineageService
from docpipe.core.lineage.domain.ports.lineage_publisher import LineagePublisherPort
from docpipe.core.models.session_info import create_session_info, get_session_info
from docpipe.core.orchestration.ports.flow_engine import ExecuteStepResults
from docpipe.core.orchestration.python.python_orchestrator import PythonOrchestrator
from docpipe.exceptions.docpipe_exceptions import DocpipeException
from docpipe.integrations.secrets.registry import get_registry
from docpipe.integrations.secrets.secret_provider import SecretProvider, clear_providers, register_provider
from docpipe.utils.infrastructure.config_utils import DocpipeConfigLoader
from docpipe.utils.infrastructure.logging import install_scrub_filter

from .catalog import Entry, Kind
from .sinks import Sinks, forms_of, make_canary, safe_repr, structured_leaves, table_text

NODE = "node1"
NODE_ID = "11111111-1111-4111-8111-111111111111"
JOB = "22222222-2222-4222-8222-222222222222"
RUN = "33333333-3333-4333-8333-333333333333"
REQUEST_TRACE = "12345678-1234-4234-8234-123456789012"


class Scenario(enum.Enum):
    """The five paths every field is run through."""

    SUCCESS = "success"
    RESOLUTION_FAILURE = "resolution_failure"
    ADAPTER_VALIDATION_FAILURE = "adapter_validation_failure"
    CLIENT_FAILURE = "client_failure"
    MID_RUN_FAILURE = "mid_run_failure"


# ---------------------------------------------------------------------------
# Fake provider
# ---------------------------------------------------------------------------


class CanaryProvider(SecretProvider):
    """Returns a fixed value, or raises a chosen exception."""

    def __init__(self, *, value: str, error: BaseException | None = None) -> None:
        self._value = value
        self._error = error
        self.calls = 0

    def authenticate(self) -> None:
        pass

    def get_secret(self, *, path: str, key: str | None = None) -> str:
        self.calls += 1
        if self._error is not None:
            raise self._error
        return self._value

    def is_available(self) -> bool:
        return True


# ---------------------------------------------------------------------------
# Fake clients
# ---------------------------------------------------------------------------


def leaky_text(*, canary: str) -> str:
    """Return error text that echoes the canary the way client libraries and servers do.

    The raw value, its percent-encoded form and its base64 form are all present, because each is a form a real
    request URL, header or response body carries. The registry is expected to mask all of them.
    """
    forms = forms_of(canary=canary)
    return f"request failed: value={forms['raw']} url=?k={forms['quote_plus']} header={forms['b64']}"


def library_exception(*, family: str, text: str) -> BaseException:
    """Return an exception of the real client library for ``family``, carrying ``text``."""
    if family == "boto":
        from botocore.exceptions import ClientError

        return ClientError({"Error": {"Code": "AuthFailure", "Message": text}}, "Operation")
    if family == "dropbox":
        from dropbox.exceptions import BadInputError

        return BadInputError("request-id", text)
    if family == "box":
        from box_sdk_gen import BoxSDKError

        return BoxSDKError(text)
    if family == "google":
        from google.auth.exceptions import RefreshError

        return RefreshError(text)
    if family == "milvus":
        from pymilvus.exceptions import MilvusException

        return MilvusException(message=text)
    if family == "opensearch":
        from opensearchpy.exceptions import AuthenticationException

        return AuthenticationException(401, text, {})
    if family == "litellm":
        from litellm.exceptions import AuthenticationError

        return AuthenticationError(message=text, llm_provider="p", model="m")
    if family == "requests":
        from requests.exceptions import ConnectionError as RequestsConnectionError

        return RequestsConnectionError(text)
    return ValueError(text)


@dataclass
class ClientStats:
    """What the fake clients saw, so a test can show the harness reached a client."""

    constructed: int = 0
    called: int = 0
    injected: list[BaseException] = field(default_factory=list)


class _Quiet:
    """A client that does nothing and returns nothing: every call returns itself, it is falsy and iterates empty.

    ``MagicMock`` is not used for the success path: a truthy ``has_more`` makes paging adapters loop forever.
    """

    def __getattr__(self, name: str) -> "_Quiet":
        if name.startswith("__"):
            raise AttributeError(name)
        return self

    def __call__(self, *args: Any, **kwargs: Any) -> "_Quiet":
        return self

    def __iter__(self) -> Iterator[Any]:
        return iter(())

    def __bool__(self) -> bool:
        return False

    def __len__(self) -> int:
        return 0

    def __getitem__(self, key: Any) -> "_Quiet":
        return self

    def __enter__(self) -> "_Quiet":
        return self

    def __exit__(self, *args: Any) -> None:
        return None


class _Raiser:
    """A client whose every method, context manager and iteration raises a wrapped library error."""

    def __init__(self, *, family: str, text: str, stats: ClientStats) -> None:
        self._family = family
        self._text = text
        self._stats = stats

    def _boom(self) -> BaseException:
        self._stats.called += 1
        inner = library_exception(family=self._family, text=self._text)
        self._stats.injected.append(inner)
        # The wrapper style adapters use: ``raise ValueError(f"... {e}") from e`` for a caught client error.
        wrapper = ValueError(f"operation failed: {inner}")
        wrapper.__cause__ = inner
        return wrapper

    def __getattr__(self, name: str) -> "_Raiser":
        # Nested clients (``client.indices.exists(...)``) are attributes first, calls last: every level is a
        # raiser, and whichever is called raises.
        if name.startswith("__"):
            raise AttributeError(name)
        return self

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        raise self._boom()

    def __enter__(self) -> "_Raiser":
        raise self._boom()

    def __iter__(self) -> Iterator[Any]:
        raise self._boom()


# Targets that are plain functions performing the request, not constructors of a client object: in the
# mid-run scenario the call itself raises.
FUNCTION_TARGETS: frozenset[str] = frozenset(
    {
        "litellm.embedding",
        "litellm.completion",
        "litellm.aembedding",
        "litellm.acompletion",
        "requests.get",
        "requests.post",
        "requests.request",
    }
)

# (module, attribute, exception family). Every constructor or module-level function that opens a client.
CLIENT_TARGETS: tuple[tuple[str, str, str], ...] = (
    ("boto3", "client", "boto"),
    ("boto3", "resource", "boto"),
    ("msal", "ConfidentialClientApplication", "requests"),
    ("dropbox", "Dropbox", "dropbox"),
    ("docpipe.core.operators.ingest.adapters.outbound.sources.dropbox.adapter", "Dropbox", "dropbox"),
    ("box_sdk_gen", "BoxClient", "box"),
    ("box_sdk_gen", "BoxJWTAuth", "box"),
    ("box_sdk_gen", "JWTConfig", "box"),
    ("docpipe.core.operators.ingest.adapters.outbound.sources.box.auth", "BoxClient", "box"),
    ("docpipe.core.operators.ingest.adapters.outbound.sources.box.auth", "BoxJWTAuth", "box"),
    ("docpipe.core.operators.ingest.adapters.outbound.sources.box.adapter", "BoxClient", "box"),
    ("docpipe.core.operators.storage.adapters.outbound.destinations.box.adapter", "BoxClient", "box"),
    ("docpipe.core.operators.storage.adapters.outbound.destinations.box.adapter", "BoxJWTAuth", "box"),
    ("googleapiclient.discovery", "build", "google"),
    ("google_auth_oauthlib.flow", "InstalledAppFlow", "google"),
    ("docpipe.core.operators.storage.adapters.outbound.destinations.google_drive.adapter", "_gdrive_build", "google"),
    ("docpipe.core.operators.ingest.adapters.outbound.sources.google_drive.adapter", "Credentials", "google"),
    (
        "docpipe.core.operators.ingest.adapters.outbound.sources.google_drive.adapter",
        "ServiceAccountCredentials",
        "google",
    ),
    ("pymilvus", "MilvusClient", "milvus"),
    ("docpipe.core.operators.vectordb.adapters.outbound.milvus.client", "PyMilvusClient", "milvus"),
    ("docpipe.core.operators.vectordb.adapters.outbound.milvus.adapter", "MilvusClient", "milvus"),
    ("docpipe.core.operators.vectordb.adapters.outbound.milvus.resource_metadata", "MilvusClient", "milvus"),
    ("docpipe.core.operators.vectordb.adapters.outbound.milvus.batch_processor", "MilvusClient", "milvus"),
    ("docpipe.core.operators.vectordb.adapters.outbound.milvus.index_manager", "MilvusClient", "milvus"),
    ("opensearchpy", "OpenSearch", "opensearch"),
    ("docpipe.core.operators.vectordb.adapters.outbound.opensearch.client", "OpenSearch", "opensearch"),
    ("docpipe.core.operators.vectordb.adapters.outbound.opensearch.index_manager", "OpenSearch", "opensearch"),
    ("docpipe.core.operators.vectordb.adapters.outbound.opensearch.batch_processor", "OpenSearch", "opensearch"),
    ("litellm", "embedding", "litellm"),
    ("litellm", "completion", "litellm"),
    ("litellm", "aembedding", "litellm"),
    ("litellm", "acompletion", "litellm"),
    ("requests", "get", "requests"),
    ("requests", "post", "requests"),
    ("requests", "request", "requests"),
    ("requests.sessions", "Session", "requests"),
)


class _Constructor:
    """A stand-in for a client class: calling it, or any of its class-level factories, builds the fake client."""

    def __init__(self, *, build: Callable[..., Any]) -> None:
        self._build = build

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        return self._build(*args, **kwargs)

    def __getattr__(self, name: str) -> Callable[..., Any]:
        if name.startswith("__"):
            raise AttributeError(name)
        return self._build


@dataclass
class FakeClients:
    """Replaces the client entry points of every integration for the length of one scenario."""

    mode: str
    text: str
    stats: ClientStats = field(default_factory=ClientStats)

    def factory(self, *, family: str, function: bool = False) -> Callable[..., Any]:
        """Return the replacement for one constructor (or request function), per the scenario mode."""

        def build(*args: Any, **kwargs: Any) -> Any:
            self.stats.constructed += 1
            if function and self.mode == "call":
                raise _Raiser(family=family, text=self.text, stats=self.stats)._boom()
            if self.mode == "construct":
                inner = library_exception(family=family, text=self.text)
                self.stats.injected.append(inner)
                raise inner
            if self.mode == "call":
                return _Raiser(family=family, text=self.text, stats=self.stats)
            return _Quiet()

        return _Constructor(build=build)

    def install(self, *, monkeypatch: pytest.MonkeyPatch) -> None:
        """Patch every target that exists in this environment."""
        for module_name, attribute, family in CLIENT_TARGETS:
            try:
                module = importlib.import_module(module_name)
            except ImportError:
                continue
            original = module.__dict__.get(attribute)
            if original is None:
                continue
            replacement = self.factory(family=family, function=f"{module_name}.{attribute}" in FUNCTION_TARGETS)
            # ``from lib import client`` copies the name: patch every module that already holds the original.
            for holder in list(sys.modules.values()):
                if holder is not None and getattr(holder, "__dict__", {}).get(attribute) is original:
                    monkeypatch.setattr(holder, attribute, replacement)


# ---------------------------------------------------------------------------
# Log capture
# ---------------------------------------------------------------------------


class _Capture(logging.Handler):
    """Collects the text of every record the way an application handler with the scrub filter would emit it."""

    def __init__(self) -> None:
        super().__init__(level=0)
        self.lines: list[str] = []
        self._formatter = logging.Formatter("%(levelname)s %(name)s %(message)s")
        install_scrub_filter(handler=self)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.lines.append(self._formatter.format(record))
        except Exception as exc:  # nosec B110 - a record that cannot be formatted is not a sink
            self.lines.append(f"<unformattable record: {type(exc).__name__}>")


@contextmanager
def capture_logs() -> Iterator[_Capture]:
    """Capture every ``docpipe`` record at DEBUG and above, through the production scrub filter."""
    handler = _Capture()
    root = logging.getLogger()
    saved_root_level = root.level
    saved_levels = {
        name: logger.level
        for name, logger in logging.root.manager.loggerDict.items()
        if name.startswith("docpipe") and isinstance(logger, logging.Logger)
    }
    root.addHandler(handler)
    root.setLevel(logging.DEBUG)
    for name in saved_levels:
        logging.getLogger(name).setLevel(logging.DEBUG)
    try:
        yield handler
    finally:
        root.removeHandler(handler)
        root.setLevel(saved_root_level)
        for name, level in saved_levels.items():
            logging.getLogger(name).setLevel(level)


# ---------------------------------------------------------------------------
# The run
# ---------------------------------------------------------------------------


@dataclass
class RunResult:
    """Everything one scenario produced."""

    sinks: Sinks
    canaries: list[str]
    provider: CanaryProvider
    clients: ClientStats
    job_status: str
    failed: bool
    docpipe_exceptions: list[BaseException]
    recorded: list[BaseException]
    collector_errors: list[str]


def canary_for(*, entry: Entry) -> tuple[str, list[str], str]:
    """Return ``(stored text, canaries to scan for, reference)`` for the entry."""
    url_like = entry.kind is Kind.DESTINATION
    canary = make_canary(parts=[str(part) for part in entry.key], url_like=url_like)
    reference = f"vault://fake/{make_canary(parts=['path', *map(str, entry.key)])[5:17]}#value"
    if entry.kind is Kind.STRUCTURED:
        structured = {
            "type": "service_account",
            "private_key": canary,
            "client_email": f"svc-{canary[5:17]}@example.test",
        }
        return (
            json.dumps(structured),
            [leaf for leaf in structured_leaves(value=structured) if leaf != "service_account"],
            reference,
        )
    return canary, [canary], reference


def _materialize_files(*, config: Mapping[str, Any], stored: str, entry: Entry, missing: bool) -> None:
    """Create every file the configuration points at (relative to the working directory), holding ``{}``.

    A path that does not exist is rejected before any client is built, which would leave the client and
    mid-run scenarios exercising nothing. The field under test, when it is a path, is created from its
    stored value, except when ``missing``: a file that cannot be found is how a path field fails at the client,
    and the error names the path.
    """
    names: list[str] = [stored] if entry.kind is Kind.PATH and not missing else []

    def walk(node: Any) -> None:
        if isinstance(node, Mapping):
            for item in node.values():
                walk(item)
        elif isinstance(node, str) and node.endswith(".json") and not node.startswith("vault://"):
            names.append(node)

    walk(config)
    for name in names:
        target = Path(name)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("{}", encoding="utf-8")


def _input_results(*, row: Mapping[str, Any]) -> ExecuteStepResults:
    factory = DataAccessFactory()
    factory.apply_input_params({"data_config": {"da_class": "data_processing.data_access.DataAccessMemory"}})
    data_access = factory.create_data_access()
    # A ``None`` in ``row`` removes a default column (extraction is skipped when ``content`` is already present).
    columns = {
        key: value
        for key, value in {"id": "a", "name": "a.txt", "content": "hello", **row}.items()
        if value is not None
    }
    table = pa.table({name: [value] for name, value in columns.items()})
    data_access.save_table(path="", table=table)
    return ExecuteStepResults([data_access], [table], {})


def _rest_text(*, exc: BaseException) -> str:
    request = MagicMock()
    request.state.transaction_id = REQUEST_TRACE
    request.path_params = {}
    response = (
        docpipe_exception_handler(request, exc)
        if isinstance(exc, DocpipeException)
        else generic_exception_handler(request, exc)
    )
    return bytes(response.body).decode("utf-8", errors="replace")


def run_entry(*, entry: Entry, scenario: Scenario, workdir: Path, monkeypatch: pytest.MonkeyPatch) -> RunResult:
    """Run ``entry`` through ``scenario`` and return the captured sinks."""
    from docpipe.core.orchestration import flow_execution_event_handler as handler_module

    stored, canaries, reference = canary_for(entry=entry)
    secret_text = leaky_text(canary=canaries[0])

    monkeypatch.setenv(DocpipeConstants.DOCPIPE_DATA_PATH, str(workdir / "data"))
    monkeypatch.chdir(workdir)
    for name, value in entry.case.env.items():
        monkeypatch.setenv(name, value)
    clear_providers()
    get_registry().clear_all()
    error = None
    if scenario is Scenario.RESOLUTION_FAILURE:
        error = library_exception(family="requests", text=secret_text)
    provider = CanaryProvider(value=stored, error=error)
    register_provider(name="fake", provider=provider)
    DocpipeConfigLoader._config = {
        "secrets": {"vault": {"allowed_paths": ["*:**"], "allowed_destinations": ["*.example.test"]}}
    }

    mode = {Scenario.CLIENT_FAILURE: "construct", Scenario.MID_RUN_FAILURE: "call"}.get(scenario, "ok")
    clients = FakeClients(mode=mode, text=secret_text)
    clients.install(monkeypatch=monkeypatch)

    class _Inline:
        @staticmethod
        def submit(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
            fn(*args, **kwargs)

    monkeypatch.setattr(handler_module, "thread_pool_executor", _Inline())

    if scenario is Scenario.ADAPTER_VALIDATION_FAILURE:
        _make_constructor_reject(entry=entry, monkeypatch=monkeypatch, canary=canaries[0])

    store = InMemoryJobStatsStore()
    tracker = JobTrackerService(job_stats_store=store, node_stats_aggregator=NodeStatsAggregator(job_stats_store=store))
    publisher = MagicMock(spec=LineagePublisherPort)
    observer = OpenLineageExecutionObserver(
        lineage_service=LineageService(publisher=publisher, namespace="ns", producer="https://p.example.test"),
        mode="operator",
    )
    orchestrator = PythonOrchestrator(job_stats_service=tracker, observer=observer)
    create_session_info(job_id=JOB, job_run_id=RUN, orchestrator=orchestrator, flow_id="flow1")
    orchestrator.initialize(job_id=JOB, job_run_id=RUN)

    config = entry.build_config(reference=reference)
    _materialize_files(config=config, stored=stored, entry=entry, missing=scenario is Scenario.CLIENT_FAILURE)
    for value in entry.case.row.values():
        if isinstance(value, str) and value.endswith((".md", ".pdf")):
            Path(value).write_text("# Title\n\nBody text.\n", encoding="utf-8")
    op_def = {"id": NODE_ID, "name": NODE, "operator": entry.operator, "config": config}
    flow_def = {"name": "conformance", "dag": [op_def]}
    global_config = {
        DocpipeConstants.JOB_ID: JOB,
        DocpipeConstants.JOB_RUN_ID: RUN,
        DocpipeConstants.FLOW_DEFINITION: flow_def,
    }

    recorded: list[BaseException] = []
    original_failure = PythonOrchestrator._handle_node_failure

    def spy(self: Any, *, e: BaseException, **kwargs: Any) -> Any:
        recorded.append(e)
        return original_failure(self, e=e, **kwargs)

    monkeypatch.setattr(PythonOrchestrator, "_handle_node_failure", spy)

    sinks = Sinks()
    collector_errors: list[str] = []
    with capture_logs() as log:
        try:
            orchestrator.flow_execution_event_handler.before_flow_execution_start(
                orchestrator=orchestrator, flow_def=flow_def
            )
            result = orchestrator._inner_task(
                op_def, global_config, _input_results(row=entry.case.row), get_session_info(), 0
            )
            orchestrator._finalize_dag_flow(op_flow=[op_def], global_config=global_config)
        finally:
            sinks.add_text(sink="logs", text="\n".join(log.lines))

    if result is not None:
        sinks.add_object(sink="run_metadata", value=result.internal_metadata)
        for table in result.tables:
            sinks.add_text(sink="table", text=table_text(table=table))
    sinks.add_text(sink="orchestrator_message", text=str(orchestrator.message or ""))
    sinks.add_object(sink="task_parameters", value={"op_def": op_def, "global_config": global_config})

    def collect(*, sink: str, produce: Callable[[], Any]) -> None:
        try:
            sinks.add_object(sink=sink, value=produce())
        except Exception as exc:  # nosec B110 - recorded and reported, not hidden
            collector_errors.append(f"{sink}: {type(exc).__name__}: {safe_repr(value=exc)[:300]}")

    collect(
        sink="job_record",
        produce=lambda: tracker.get_job(job_run_id=RUN, include_node_stats=True, include_batch_stats=True),
    )
    collect(sink="job_report", produce=lambda: tracker.get_formatted_job_stats(job_run_id=RUN, include_logs=True))
    collect(
        sink="rest_job_status",
        produce=lambda: JobStatsMapper.to_status_response(
            job_stats=tracker.get_job(job_run_id=RUN, include_node_stats=True, include_batch_stats=True),
            include_logs=True,
        ).model_dump(mode="json"),
    )
    for call in publisher.publish.call_args_list:
        sinks.add_object(sink="lineage", value=[call.args, call.kwargs])
    docpipe_exceptions = [exc for exc in recorded if type(exc).__module__.startswith("docpipe")]
    for exc in docpipe_exceptions:
        sinks.add_text(sink="docpipe_exception_text", text=f"{exc!s}\n{safe_repr(value=exc)}")
    for recorded_exc in recorded:
        collect(sink="rest_error_response", produce=functools.partial(_rest_text, exc=recorded_exc))
    sinks.add_file_tree(root=workdir)

    PythonOrchestrator._release_run_secrets(job_run_id=RUN)
    return RunResult(
        sinks=sinks,
        canaries=canaries,
        provider=provider,
        clients=clients.stats,
        job_status=str(orchestrator.job_status),
        failed=bool(recorded),
        docpipe_exceptions=docpipe_exceptions,
        recorded=recorded,
        collector_errors=collector_errors,
    )


def _make_constructor_reject(*, entry: Entry, monkeypatch: pytest.MonkeyPatch, canary: str) -> None:
    """Make the operator's constructor fail the way an adapter config model does: a Pydantic error echoing its input.

    Resolution is real. The error is raised from the operator constructor with the value the resolver handed
    over at the field under test as the rejected input, which is what Pydantic echoes in ``input_value``.
    """
    from pydantic import BaseModel, Field

    from docpipe.core.operators.operator_registry import get_docpipe_operators

    operator_class = next(cls for cls in get_docpipe_operators() if cls.short_name == entry.operator)
    path = entry.concrete_path.split(".")

    def reject(self: Any, config: dict[str, Any], *args: Any, **kwargs: Any) -> None:
        node: Any = config
        for segment in path:
            node = node.get(segment) if isinstance(node, dict) else None
        value = node.reveal() if hasattr(node, "reveal") else node

        class Model(BaseModel):
            field_under_test: str = Field(max_length=1)

        Model.model_validate({"field_under_test": value if isinstance(value, str) else json.dumps(value, default=str)})

    monkeypatch.setattr(operator_class, "__init__", reject)


def format_failure(*, entry: Entry, scenario: Scenario, leaks: list[str], result: RunResult) -> str:
    """Return the assertion message for a leak, naming the operator, field and scenario."""
    operator, _, provider, path = entry.key
    return (
        f"{operator}: field '{path}' (provider {provider}) leaked its canary in scenario {scenario.value}: "
        f"{leaks}; traceback of recorded docpipe exceptions: "
        + " | ".join(
            "".join(traceback.format_exception_only(type(e), e)).strip()[:200] for e in result.docpipe_exceptions
        )
    )

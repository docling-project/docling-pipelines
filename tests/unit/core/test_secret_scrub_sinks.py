# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""A registered secret value is scrubbed at every outbound sink, and adapter caches are HMAC keyed.

Covers the resolver registration point, the job tracker (job message, node stats, node error,
job log file), lineage event construction, the REST error handler (including the unhandled
exception path), the OpenLineage publisher warning, the run-end release, and the SharePoint and
OneDrive loader caches.
"""

import json
import logging
from collections.abc import Generator
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

from docpipe.api.middleware.error_handler import (
    create_error_response,
    generic_exception_handler,
    http_exception_handler,
)
from docpipe.core.constants.constants import ExecutionStatus
from docpipe.core.job_management.adapters.services.job_tracker_service import JobTrackerService
from docpipe.core.lineage.application.lineage_service import LineageService
from docpipe.core.lineage.domain.ports.lineage_publisher import LineagePublisherPort
from docpipe.core.operators.ingest.adapters.outbound.sources.onedrive.adapter import OneDriveSourceAdapter
from docpipe.core.operators.ingest.adapters.outbound.sources.sharepoint.adapter import SharePointSourceAdapter
from docpipe.core.orchestration.abstract_orchestrator import AbstractOrchestrator
from docpipe.core.orchestration.models.execution_event_context import NodeFailContext
from docpipe.integrations.secrets.registry import (
    MASK,
    SCRUB_FAILURE_PLACEHOLDER,
    cache_key_digest,
    get_registry,
    register_secret,
)
from docpipe.utils.infrastructure.logging import install_scrub_filter

# pragma: allowlist nextline secret
CANARY = "CANARY-pw-7f3a/9&x"
RUN = "run-sinks"


@pytest.fixture(autouse=True)
def _clean_registry() -> Generator[None, None, None]:
    get_registry().clear_all()
    yield
    get_registry().clear_all()


@pytest.fixture
def tracker_and_store() -> tuple[JobTrackerService, Mock]:
    store = Mock()
    return JobTrackerService(job_stats_store=store, node_stats_aggregator=Mock()), store


class TestResolverRegisters:
    def test_resolved_value_is_registered_with_the_run(self) -> None:
        from docpipe.integrations.secrets.resolver import resolve_node_config
        from docpipe.integrations.secrets.secret_provider import clear_providers, register_provider
        from docpipe.utils.infrastructure.config_utils import DocpipeConfigLoader
        from tests.unit.integrations.secrets.test_resolver import (  # type: ignore[import-not-found]
            FakeOperator,
            RecordingProvider,
        )

        clear_providers()
        DocpipeConfigLoader.reset()
        # pragma: allowlist nextline secret
        register_provider(name="hashicorp", provider=RecordingProvider(secrets={"db/creds": {"password": CANARY}}))
        DocpipeConfigLoader._config = {"secrets": {"vault": {"allowed_paths": ["hashicorp:db/*"]}}}
        try:
            resolve_node_config(
                node_name="n",
                operator_class=FakeOperator,
                config={"password": "vault://hashicorp/db/creds#password"},  # pragma: allowlist secret
            )
        finally:
            clear_providers()
            DocpipeConfigLoader.reset()
        from docpipe.integrations.secrets.registry import scrub

        assert scrub(f"line {CANARY}") == f"line {MASK}"


class TestJobTrackerSinks:
    def test_job_message_is_scrubbed(self, tracker_and_store) -> None:
        tracker, store = tracker_and_store
        job_stats = MagicMock()
        job_stats.start_time = 0
        store.get_job_stats.return_value = job_stats
        register_secret(value=CANARY, run_id=RUN)
        tracker.end_job(
            job_run_id="r", status=ExecutionStatus.FAILED.value, job_run_stats={"message": f"boom {CANARY}"}
        )
        assert CANARY not in job_stats.message
        assert MASK in job_stats.message

    def test_node_error_message_is_scrubbed(self, tracker_and_store) -> None:
        tracker, store = tracker_and_store
        store.get_node_stats_by_batch_and_node.return_value = None
        register_secret(value=CANARY, run_id=RUN)
        tracker.fail_node_execution(job_run_id="r", node_id="n", node_name="node", error=f"bad {CANARY}")
        stored = store.store_node_stats.call_args.kwargs["node_stats"]
        assert CANARY not in json.dumps(stored.model_dump(), default=str)

    def test_node_metadata_is_scrubbed(self, tracker_and_store) -> None:
        tracker, store = tracker_and_store
        from docpipe.core.job_management.domain.models.node_stats import NodeStats

        store.get_node_stats_by_batch_and_node.return_value = NodeStats(id="n", name="node", start_time=1)
        register_secret(value=CANARY, run_id=RUN)
        tracker.complete_node_execution(
            job_run_id="r",
            node_id="n",
            node_name="node",
            docs_completed=[],
            failed_docs=[],
            skipped_docs=[],
            col_names=[],
            node_status="Completed",
            node_metadata={"endpoint": f"https://u:{CANARY}@h"},
        )
        stored = store.store_node_stats.call_args.kwargs["node_stats"]
        assert CANARY not in json.dumps(stored.model_dump(), default=str)

    def test_job_log_file_is_scrubbed(self, tracker_and_store, tmp_path: Path) -> None:
        tracker, _ = tracker_and_store
        tracker.get_flow_definition = Mock(return_value=None)
        register_secret(value=CANARY, run_id=RUN)
        path = tmp_path / "job.json"
        tracker.write_job_logs(job_stats={"message": f"x {CANARY}", "node_stats": {}}, job_log_path=str(path))
        assert CANARY not in path.read_text()
        assert MASK in path.read_text()


class TestLineageSink:
    def test_error_facet_message_and_stack_trace_are_scrubbed(self) -> None:
        publisher = MagicMock(spec=LineagePublisherPort)
        service = LineageService(publisher=publisher, namespace="docpipe://t", producer="https://p")
        register_secret(value=CANARY, run_id=RUN)
        try:
            raise ValueError(f"cannot log in with {CANARY}")
        except ValueError as exc:
            service.emit_node_fail(
                context=NodeFailContext(
                    flow_id="f",
                    flow_name="flow",
                    job_run_id="r",
                    node_id="n",
                    node_name="node",
                    operator_type="chunker",
                    error_message=f"failed: {CANARY}",
                    exception=exc,
                )
            )
        kwargs = publisher.publish.call_args.kwargs
        text = json.dumps([kwargs["run"].facets, kwargs["job"].facets], default=str)
        assert CANARY not in text
        assert "stackTrace" in text

    def test_publisher_warning_does_not_log_the_raw_exception(self, caplog: pytest.LogCaptureFixture) -> None:
        pytest.importorskip("openlineage.client")
        from docpipe.core.lineage.adapters.openlineage.publisher import OpenLineagePublisherAdapter

        register_secret(value=CANARY, run_id=RUN)
        client = MagicMock()
        client.emit.side_effect = RuntimeError(f"transport rejected {CANARY}")
        adapter = OpenLineagePublisherAdapter.__new__(OpenLineagePublisherAdapter)
        adapter._client = client  # type: ignore[attr-defined]
        adapter._namespace = "ns"  # type: ignore[attr-defined]
        caplog.set_level(logging.WARNING)
        from docpipe.core.lineage.domain.models.event_type import LineageEventType
        from docpipe.core.lineage.domain.models.job import LineageJob
        from docpipe.core.lineage.domain.models.run import LineageRun

        adapter.publish(
            event_type=LineageEventType.START,
            run=LineageRun(run_id="11111111-1111-1111-1111-111111111111"),
            job=LineageJob(namespace="ns", name="j"),
        )
        assert CANARY not in caplog.text


class TestErrorHandlerSink:
    @pytest.fixture
    def request_stub(self) -> MagicMock:
        request = MagicMock()
        request.state.transaction_id = "12345678-1234-4234-8234-123456789012"
        request.path_params = {}
        return request

    def test_response_message_is_scrubbed(self) -> None:
        register_secret(value=CANARY, run_id=RUN)
        response = create_error_response(
            status_code=400,
            error_code="invalid_parameter",
            message=f"bad value {CANARY}",
            trace_id="12345678-1234-4234-8234-123456789012",
        )
        assert CANARY not in response.body.decode()
        assert MASK in response.body.decode()

    def test_value_error_response_is_scrubbed(self, request_stub) -> None:
        register_secret(value=CANARY, run_id=RUN)
        response = generic_exception_handler(request_stub, ValueError(f"nope {CANARY}"))
        assert CANARY not in response.body.decode()

    def test_http_exception_detail_is_scrubbed(self, request_stub) -> None:
        from starlette.exceptions import HTTPException

        register_secret(value=CANARY, run_id=RUN)
        response = http_exception_handler(request_stub, HTTPException(status_code=400, detail=f"x {CANARY}"))
        assert CANARY not in response.body.decode()

    def test_unhandled_exception_response_is_generic(self, request_stub, caplog: pytest.LogCaptureFixture) -> None:
        register_secret(value=CANARY, run_id=RUN)
        caplog.set_level(logging.DEBUG)

        class VendorError(RuntimeError):
            pass

        try:
            raise VendorError(f"vendor says password={CANARY}")
        except VendorError as exc:
            response = generic_exception_handler(request_stub, exc)
        assert response.status_code == 500
        assert CANARY not in response.body.decode()
        assert "VendorError" in caplog.text

    def test_unhandled_exception_is_scrubbed_by_the_handler_filter(self, request_stub) -> None:
        import io

        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        install_scrub_filter(handler=handler)
        handler_logger = logging.getLogger("docpipe.api.middleware.error_handler")
        handler_logger.addHandler(handler)
        register_secret(value=CANARY, run_id=RUN)
        try:
            raise RuntimeError(f"vendor says {CANARY}")
        except RuntimeError as exc:
            generic_exception_handler(request_stub, exc)
        handler_logger.removeHandler(handler)
        assert CANARY not in stream.getvalue()

    def test_placeholder_is_used_when_scrubbing_fails(self, monkeypatch: pytest.MonkeyPatch) -> None:
        register_secret(value=CANARY, run_id=RUN)

        def boom(*, text: str) -> str:
            raise RuntimeError("broken")

        monkeypatch.setattr(get_registry(), "scrub_text", boom)
        response = create_error_response(
            status_code=400,
            error_code="invalid_parameter",
            message=CANARY,
            trace_id="12345678-1234-4234-8234-123456789012",
        )
        assert CANARY not in response.body.decode()
        assert SCRUB_FAILURE_PLACEHOLDER in response.body.decode()


class TestRunRelease:
    def test_release_clears_the_registry_the_key_and_the_fetch_caches(self) -> None:
        register_secret(value=CANARY, run_id=RUN)
        first = cache_key_digest(namespace="t", parts=["s"], run_id=RUN)
        with patch("docpipe.utils.operators.binary_content_fetcher.clear_fetch_caches") as fetch_clear:
            AbstractOrchestrator._release_run_secrets(job_run_id=RUN)
        fetch_clear.assert_called_once()
        assert not get_registry().has_entries()
        assert cache_key_digest(namespace="t", parts=["s"], run_id=RUN) != first


class TestLoaderCaches:
    @pytest.mark.parametrize(
        ("adapter_cls", "module"),
        [
            (SharePointSourceAdapter, "sharepoint"),
            (OneDriveSourceAdapter, "onedrive"),
        ],
    )
    def test_loader_cache_key_is_an_hmac_without_the_secret(self, adapter_cls, module, caplog) -> None:
        caplog.set_level(logging.DEBUG)
        adapter = adapter_cls()
        loader_path = f"docpipe.core.operators.ingest.adapters.outbound.sources.{module}.adapter.MicrosoftGraphLoader"
        with patch(loader_path):
            adapter._get_loader(drive_id="d", client_id="c", client_secret=CANARY, tenant_id="t")
        (key,) = adapter._loader_cache
        secret_hash = key[3]
        assert len(secret_hash) == 64
        assert all(CANARY[i : i + 6] not in secret_hash for i in range(len(CANARY) - 5))
        assert secret_hash not in caplog.text
        import hashlib

        assert secret_hash != hashlib.sha256(CANARY.encode()).hexdigest()
        assert secret_hash != hashlib.sha256(CANARY.encode()).hexdigest()[:16]

    def test_loader_cache_key_differs_between_runs(self) -> None:
        from docpipe.core.models.session_info import create_session_info

        keys = []
        for run in ("run-a", "run-b"):
            create_session_info(job_run_id=run)
            adapter = SharePointSourceAdapter()
            with patch(
                "docpipe.core.operators.ingest.adapters.outbound.sources.sharepoint.adapter.MicrosoftGraphLoader"
            ):
                adapter._get_loader(drive_id="d", client_id="c", client_secret=CANARY, tenant_id="t")
            keys.append(next(iter(adapter._loader_cache))[3])
        assert keys[0] != keys[1]

    def test_loader_is_reused_within_a_run_and_rebuilt_for_a_rotated_secret(self) -> None:
        from docpipe.core.models.session_info import create_session_info

        create_session_info(job_run_id="run-c")
        adapter = SharePointSourceAdapter()
        with patch(
            "docpipe.core.operators.ingest.adapters.outbound.sources.sharepoint.adapter.MicrosoftGraphLoader"
        ) as loader:
            adapter._get_loader(drive_id="d", client_id="c", client_secret="one", tenant_id="t")
            adapter._get_loader(drive_id="d", client_id="c", client_secret="one", tenant_id="t")
            adapter._get_loader(drive_id="d", client_id="c", client_secret="two", tenant_id="t")
        assert loader.call_count == 2

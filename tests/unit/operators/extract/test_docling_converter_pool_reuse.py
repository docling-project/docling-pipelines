"""End-to-end reuse of pooled Docling converters through the real text-extraction path.

A stub ``DocumentConverter`` replaces Docling's (no models are downloaded). Each
micro-batch builds a NEW ``DoclingAdapter`` (as a new operator instance per batch
does) whose ``transform()`` runs its own short-lived worker thread pool.
"""

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from typing import ClassVar

import pyarrow as pa
import pytest

from docpipe.core.constants.constants import EnvironmentVariables, Metrics
from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.core.operators.abstract_operator import AbstractOperator
from docpipe.core.operators.extract.adapters.outbound.text_extraction.docling_adapter import DoclingAdapter
from docpipe.integrations.docling.converter_pool import get_docling_pool, reset_docling_pool

BATCHES = 5
WORKERS = 8
DOCS_PER_BATCH = 40


class _StubDocument:
    pages: ClassVar[dict] = {1: None}

    @staticmethod
    def export_to_markdown() -> str:
        return "# stub"


class _StubConverter:
    """Counts constructions/live instances and flags any concurrent use of one instance."""

    lock = threading.Lock()
    constructed = 0
    live = 0
    peak_live = 0
    violations = 0
    format_options: ClassVar[list] = []

    def __init__(self, format_options=None) -> None:
        with _StubConverter.lock:
            _StubConverter.constructed += 1
            _StubConverter.live += 1
            _StubConverter.peak_live = max(_StubConverter.peak_live, _StubConverter.live)
            _StubConverter.format_options.append(format_options)
        self._users = 0

    def __del__(self) -> None:
        with _StubConverter.lock:
            _StubConverter.live -= 1

    def convert(self, source):
        with _StubConverter.lock:
            self._users += 1
            if self._users > 1:
                _StubConverter.violations += 1
        try:
            time.sleep(0.002)
            return SimpleNamespace(document=_StubDocument())
        finally:
            with _StubConverter.lock:
                self._users -= 1


@pytest.fixture
def stub_converter(monkeypatch):
    import docling.document_converter as docling_converter_module

    _StubConverter.constructed = 0
    _StubConverter.live = 0
    _StubConverter.peak_live = 0
    _StubConverter.violations = 0
    _StubConverter.format_options = []
    monkeypatch.setattr(docling_converter_module, "DocumentConverter", _StubConverter)
    monkeypatch.setenv(EnvironmentVariables.DOCPIPE_DOCLING_CONVERTER_POOL_SIZE, str(WORKERS))
    reset_docling_pool()
    yield _StubConverter
    reset_docling_pool()


def _batch_table(batch: int) -> pa.Table:
    return pa.table(
        {
            "id": [f"b{batch}-{i}" for i in range(DOCS_PER_BATCH)],
            "name": [f"b{batch}-{i}.pdf" for i in range(DOCS_PER_BATCH)],
            "binary_content": [b"%PDF-1.4 stub" for _ in range(DOCS_PER_BATCH)],
        }
    )


def _run_batch(batch: int, extra_config: dict | None = None, workers: int = WORKERS) -> pa.Table:
    config = {"max_workers": workers, "use_processes": False, "doc_column": "content", **(extra_config or {})}
    adapter = DoclingAdapter(config=config)  # new "operator instance" per batch
    metadata = AbstractOperator.create_base_metadata(total_docs_count=DOCS_PER_BATCH)
    tables, metadata = adapter.transform(table=_batch_table(batch), metadata=metadata)
    assert metadata[Metrics.External.FAILED_DOCS_COUNT] == 0
    return tables[0]


def test_converter_built_once_per_worker_across_sequential_batches(stub_converter):
    """5 batches x 8 workers: at most 8 converters in total, not 8 per batch."""
    outputs = [_run_batch(batch) for batch in range(BATCHES)]

    assert all(table.num_rows == DOCS_PER_BATCH for table in outputs)
    assert all(set(table.column("content").to_pylist()) == {"# stub"} for table in outputs)
    assert 1 <= stub_converter.constructed <= WORKERS
    assert stub_converter.violations == 0


def test_concurrent_batches_share_bounded_converters(stub_converter):
    """5 concurrent batches x 8 workers (40 threads) never exceed the pool cap or share a converter."""
    with ThreadPoolExecutor(max_workers=BATCHES) as outer:
        outputs = list(outer.map(_run_batch, range(BATCHES)))

    assert all(table.num_rows == DOCS_PER_BATCH for table in outputs)
    assert stub_converter.constructed <= WORKERS
    assert stub_converter.peak_live <= WORKERS
    assert get_docling_pool().stats()["live"] <= WORKERS
    assert stub_converter.violations == 0


def test_converter_reused_after_batch_threads_exit(stub_converter):
    """Later batches (fresh threads, fresh adapters) reuse converters built by an earlier batch."""
    _run_batch(0, workers=1)
    assert stub_converter.constructed == 1
    for batch in range(1, BATCHES):
        _run_batch(batch, workers=1)
    assert stub_converter.constructed == 1


def test_different_ocr_settings_get_separate_converters(stub_converter):
    """OCR config with the same option class but different values must not share converters."""
    _run_batch(0, {OperatorConstants.Config.OCR_BLOCK: {"enabled": False}})
    built_no_ocr = stub_converter.constructed
    _run_batch(1, {OperatorConstants.Config.OCR_BLOCK: {"enabled": True, "engine": "easyocr"}})
    assert stub_converter.constructed > built_no_ocr

    pdf_options = [opts for opts in stub_converter.format_options if opts]
    do_ocr_values = {next(iter(opts.values())).pipeline_options.do_ocr for opts in pdf_options}
    assert do_ocr_values == {False, True}

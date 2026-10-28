"""EmbeddingsOperator edge cases: configuration validation, input formats and file-backed chunks.

The embedding provider is replaced by a small deterministic port double; everything else
(chunk parsing, DocLang conversion, doc-id hashing, memmap files) runs for real.
"""

import copy
import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pyarrow as pa
import pytest

from docpipe.core.constants.constants import DocpipeConstants, Metrics
from docpipe.core.operators.functional.embeddings import EmbeddingsOperator
from docpipe.core.ports.llm_embedding_port import LLMEmbeddingPort
from docpipe.utils.core.memmap_file_utils import load_embeddings_from_memmap_file, write_chunks_to_file

_ADAPTER_FACTORY_PATH = "docpipe.core.adapters.llm_adapter_factory.LLMAdapterFactory.create_embedding_adapter"
_FEATURES = ["id", "name", "content", "chunked_content"]


class _EchoAdapter(LLMEmbeddingPort):
    """Returns a 3-d vector per text and records every text it was asked to embed."""

    def __init__(self) -> None:
        self.texts: list[str] = []

    def generate_embeddings(self, *, text: str) -> list[float]:
        return self.generate_embeddings_batch(texts=[text])[0]

    def generate_embeddings_batch(self, *, texts: list[str]) -> list[list[float]]:
        self.texts.extend(texts)
        return [[float(len(text)), 1.0, 0.0] for text in texts]

    def get_embedding_dimension(self) -> int:
        return 3

    def get_embedding_batch_size(self) -> int:
        return 32

    def get_max_concurrent_requests(self) -> int:
        return 1


def _operator(*, adapter: LLMEmbeddingPort | None = None, **config: Any) -> EmbeddingsOperator:
    base: dict[str, Any] = {
        "provider": "litellm",
        "provider_config": {"model_id": "openai/text-embedding-3-small"},
    }
    base.update(config)
    with patch(_ADAPTER_FACTORY_PATH, return_value=adapter or _EchoAdapter()):
        return EmbeddingsOperator(base)


def _validate(operator: EmbeddingsOperator) -> list[str]:
    errors: list[str] = []
    operator.validate(errors, [], available_features=_FEATURES)
    return errors


def _table(**columns: list[Any]) -> pa.Table:
    count = len(next(iter(columns.values())))
    data: dict[str, Any] = {"id": [f"doc{i}" for i in range(count)], "name": [f"Doc {i}" for i in range(count)]}
    data.update(columns)
    return pa.table(data)


def _failure_reasons(metadata: dict[str, Any]) -> list[str]:
    return [doc["reason"] for doc in metadata[Metrics.External.FAILED_DOCS]]


_WRONGLY_TYPED: dict[str, Any] = {
    "token_limit": "8192",
    "provider_config": {
        "model_id": "openai/text-embedding-3-small",
        "max_concurrent_requests": "4",
        "batch_size": "8",
    },
}


class TestConfigValidation:
    """Rules that validate() applies on top of the attribute schema."""

    def test_rules_reject_wrongly_typed_values(self):
        errors = _validate(_operator(**copy.deepcopy(_WRONGLY_TYPED)))

        assert "token_limit must be an integer, got <class 'str'>" in errors
        assert "provider_config.max_concurrent_requests must be an integer, got str" in errors
        assert "provider_config.batch_size must be an integer, got str" in errors

    def test_rules_are_deferred_while_validating_the_flow(self):
        errors = _validate(_operator(validating_flow=True, **copy.deepcopy(_WRONGLY_TYPED)))

        assert not [e for e in errors if "must be an integer" in e]

    def test_positive_request_shaping_values_are_accepted(self):
        operator = _operator(
            provider_config={
                "model_id": "openai/text-embedding-3-small",
                "max_concurrent_requests": 4,
                "batch_size": 8,
            }
        )

        assert _validate(operator) == []


class TestChunkedContentFormats:
    """chunked_content as JSON string, list, memmap file reference, or something else."""

    def test_invalid_json_fails_the_document(self):
        tables, metadata = _operator().transform(_table(content=["c"], chunked_content=["[not json"]))

        assert tables[0].num_rows == 0
        assert _failure_reasons(metadata)[0].startswith("Embedding failure: Invalid chunked_content JSON format:")

    def test_unexpected_type_fails_the_document(self):
        _, metadata = _operator().transform(_table(content=["c"], chunked_content=[7]))

        assert _failure_reasons(metadata) == ["Embedding failure: Unexpected chunked_content type: int"]

    def test_blank_and_non_text_chunks_are_skipped(self):
        adapter = _EchoAdapter()
        chunks = json.dumps(["", 5, "kept chunk"])

        tables, _ = _operator(adapter=adapter).transform(_table(content=["c"], chunked_content=[chunks]))

        assert adapter.texts == ["kept chunk"]
        assert tables[0].column("embeddings").to_pylist() == [[[10.0, 1.0, 0.0]]]

    @pytest.mark.parametrize("with_ids", [True, False], ids=["named-by-doc-id", "random-name"])
    def test_file_backed_chunks_produce_file_backed_embeddings(self, tmp_path, monkeypatch, with_ids):
        monkeypatch.setenv(DocpipeConstants.DOCPIPE_DATA_PATH, str(tmp_path / "data"))
        references = []
        for doc, chunks in enumerate([["first chunk", "second"], ["third"]]):
            chunks_file = tmp_path / f"chunks{doc}.bin"
            write_chunks_to_file(chunks_list=[{"chunk": c} for c in chunks], filepath=str(chunks_file))
            references.append({DocpipeConstants.CHUNKS_MEMMAP_FILE: str(chunks_file)})
        table = _table(content=["c0", "c1"], chunked_content=references)
        if not with_ids:
            table = table.drop_columns(["id"])
        adapter = _EchoAdapter()

        tables, _ = _operator(adapter=adapter).transform(table)

        assert adapter.texts == ["first chunk", "second", "third"]
        files = [
            Path(ref[DocpipeConstants.EMBEDDINGS_MEMMAP_FILE]) for ref in tables[0].column("embeddings").to_pylist()
        ]
        assert files[0].parent == files[1].parent
        assert files[0].is_relative_to(tmp_path / "data")
        assert ([f.name for f in files] == ["doc0_embeddings.bin", "doc1_embeddings.bin"]) is with_ids
        assert [list(v) for v in load_embeddings_from_memmap_file(filepath=str(files[0]))] == [
            [11.0, 1.0, 0.0],
            [6.0, 1.0, 0.0],
        ]


class TestDocumentContent:
    """Unchunked documents embed the content column."""

    def test_empty_content_fails_the_document(self):
        _, metadata = _operator().transform(_table(content=["", "text"]))

        assert _failure_reasons(metadata) == [
            "Embedding failure: Document content column 'content' is empty or missing"
        ]

    def test_doclang_content_is_embedded_as_markdown(self):
        adapter = _EchoAdapter()
        doclang = "<doctag><text>Hello world</text></doctag>"

        _operator(adapter=adapter, doc_format="doclang").transform(_table(content=[doclang]))

        assert len(adapter.texts) == 1
        assert "Hello world" in adapter.texts[0]
        assert "<text>" not in adapter.texts[0]

    def test_non_text_content_fails_only_that_document(self):
        adapter = _EchoAdapter()
        table = _table(content=["fine"], size=[42]).append_column("body", pa.array([7]))

        tables, metadata = _operator(adapter=adapter, doc_column="body").transform(table)

        assert tables[0].num_rows == 0
        assert len(_failure_reasons(metadata)) == 1
        assert adapter.texts == []

    def test_doc_id_hash_generation_failure_fails_the_batch(self):
        table = pa.table({"id": ["doc0"], "name": ["Doc 0"], "content": pa.array([b"binary"])})

        tables, metadata = _operator().transform(table)

        assert tables[0].num_rows == 0
        assert metadata[Metrics.External.FAILED_DOCS_COUNT] == 1
        assert "not JSON serializable" in _failure_reasons(metadata)[0]

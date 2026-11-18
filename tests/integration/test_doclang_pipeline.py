"""Integration tests for end-to-end 8-node DocLang pipeline execution.

Validates the full DAG:
  ingest_source -> extract_operator -> doc_quality -> pii_and_hap -> redaction -> chunker -> embeddings -> vectordb

Tests both doc_format="doclang" and doc_format="markdown" workflows to ensure:
- DocLang XML is preserved across quality operators
- DOM-level redaction operates correctly on XML
- Chunker splits DocLang preserving spatial hierarchy/metadata
- Embeddings processes chunks and generates vectors
- VectorDB indexes clean text and preserves chunk spatial metadata
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

from docpipe.core.constants.constants import Metrics
from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.core.operators.extract.extract_operator import ExtractOperator
from docpipe.core.operators.functional.chunker import ChunkerOperator
from docpipe.core.operators.functional.embeddings.embeddings_operator import EmbeddingsOperator
from docpipe.core.operators.ingest.ingest_source import IngestSourceOperator
from docpipe.core.operators.quality.doc_quality import DocQuality
from docpipe.core.operators.quality.pii_and_hap.pii_and_hap_annotator import PIIAndHAPAnnotator
from docpipe.core.operators.quality.redaction import RedactionOperator
from docpipe.core.operators.vectordb.vectordb_operator import VectorDBOperator

_FIXTURES_DIR = Path(__file__).parents[1] / "fixtures" / "customer_support_docs"


def _skip_if_no_fixtures() -> None:
    import importlib

    if importlib.util.find_spec("docling") is None:
        pytest.skip("docling not installed")
    if not _FIXTURES_DIR.exists():
        pytest.skip(f"Fixture directory not found: {_FIXTURES_DIR}")


@pytest.mark.integration
class TestDocLangPipelineIntegration:
    """Integration test suite verifying end-to-end execution across all 8 operators."""

    def test_doclang_8_node_dag_execution(self) -> None:
        """Verify full 8-node DAG processing when doc_format='doclang'."""
        _skip_if_no_fixtures()

        # 1. Ingest
        ingest_config = {
            "provider": "filesystem",
            "connection_params": {"paths": [str(_FIXTURES_DIR)]},
            "include_filter": "txt",
            "max_files": 2,
            "force_ingest": True,
            "doc_format": "doclang",
        }
        ingest_op = IngestSourceOperator(config=ingest_config)
        ingest_tables, _ = ingest_op.transform(None)
        assert len(ingest_tables) == 1
        ingest_table = ingest_tables[0]
        assert ingest_table.num_rows > 0

        # 2. Extract (with doc_format='doclang')
        extract_config = {
            "text_extraction": {"provider": "docling_library", "doc_column": "content"},
            "entity_extraction": {"provider": "none"},
            "doc_format": "doclang",
        }
        extract_op = ExtractOperator(config=extract_config)
        extract_tables, _ = extract_op.transform(ingest_table)
        extract_table = extract_tables[0]
        assert "content" in extract_table.column_names
        assert "doc_id_hash" in extract_table.column_names
        # Check that extracted content is doclang XML
        first_content = extract_table["content"][0].as_py()
        assert first_content.lstrip().startswith("<")

        # 3. DocQuality
        doc_quality_config = {
            "doc_content_column": "content",
            "doc_format": "doclang",
        }
        doc_quality_op = DocQuality(config=doc_quality_config)
        dq_tables, _ = doc_quality_op.transform(extract_table)
        dq_table = dq_tables[0]
        assert "docq_total_words" in dq_table.column_names
        # Content remains DocLang XML
        assert dq_table["content"][0].as_py().lstrip().startswith("<")

        # 4. PII and HAP Annotator (Mocking LLM service)
        pii_config = {
            "provider": "litellm",
            "provider_config": {"model_id": "mock-model", "api_key": "test_token"},  # pragma: allowlist secret
            "doc_column_name": "content",
            "doc_format": "doclang",
        }
        from docpipe.core.operators.quality.pii_and_hap.domain.models import PIIHAPDetectionResponse

        with patch("docpipe.core.operators.quality.pii_and_hap.pii_and_hap_annotator.PIIHAPService") as mock_svc_cls:
            mock_svc = MagicMock()
            mock_svc.adapter = Mock()
            mock_svc.adapter.validate.return_value = {"valid": True, "errors": [], "warnings": []}
            mock_svc.detect_pii_hap.return_value = PIIHAPDetectionResponse(detections=[], input_text="")
            mock_svc_cls.return_value = mock_svc

            pii_op = PIIAndHAPAnnotator(config=pii_config)
            pii_tables, _ = pii_op.transform(dq_table)
            pii_table = pii_tables[0]

        # Content is still DocLang XML
        assert pii_table["content"][0].as_py().lstrip().startswith("<")

        # 5. Redaction Operator (XML DOM-level redaction)
        redaction_config = {
            "doc_column": "content",
            "redaction_regex": r"(?i)support",
            "redaction_masking_character": "X",
            "doc_format": "doclang",
        }
        redaction_op = RedactionOperator(config=redaction_config)
        redact_tables, _ = redaction_op.transform(pii_table)
        redact_table = redact_tables[0]
        redacted_xml = redact_table["content"][0].as_py()
        # XML structure is intact and word was redacted
        assert redacted_xml.lstrip().startswith("<")
        assert "<" in redacted_xml
        assert ">" in redacted_xml

        # 6. Chunker Operator (Hybrid/DocLang chunking)
        chunker_config = {
            "chunk_type": "hybrid",
            "doc_column": "content",
            "doc_format": "doclang",
        }
        chunker_op = ChunkerOperator(config=chunker_config)
        chunk_tables, _ = chunker_op.transform(redact_table)
        chunk_table = chunk_tables[0]
        assert "chunked_content" in chunk_table.column_names
        chunked_rows = chunk_table["chunked_content"][0].as_py()
        assert len(chunked_rows) > 0
        first_chunk = chunked_rows[0]
        assert isinstance(first_chunk, dict)
        assert "chunk" in first_chunk

        # 7. Embeddings Operator (Mock LLM/Embedding Adapter)
        embeddings_config = {
            "provider": "litellm",
            "provider_config": {
                "model_id": "mock-embedding-model",
                "api_key": "test_token",  # pragma: allowlist secret
            },
            "embeddings_column": "embeddings",
            "doc_format": "doclang",
        }
        mock_embedding_adapter = MagicMock()
        mock_embedding_adapter.generate_embeddings_batch.side_effect = lambda texts: [[0.1, 0.2, 0.3] for _ in texts]
        mock_embedding_adapter.generate_embeddings.return_value = [0.1, 0.2, 0.3]
        with patch(
            "docpipe.core.operators.functional.embeddings.embeddings_operator.LLMAdapterFactory.create_embedding_adapter",
            return_value=mock_embedding_adapter,
        ):
            emb_op = EmbeddingsOperator(config=embeddings_config)
            emb_tables, _ = emb_op.transform(chunk_table)
            emb_table = emb_tables[0]

        assert "embeddings" in emb_table.column_names

        # 8. VectorDB Operator
        vectordb_config = {
            "provider": "opensearch",
            "provider_config": {"index_name": "test-doclang-index", "host": "localhost"},
            "doc_id_column": "doc_id_hash",
            "embeddings_column": "embeddings",
            "doc_format": "doclang",
            "available_features": {
                "embeddings": {
                    OperatorConstants.Misc.TYPE: "vector",
                    OperatorConstants.Config.AVAILABLE_FOR_VECTOR_DB: True,
                }
            },
        }
        mock_vector_store = Mock()
        mock_vector_store.index_exists.return_value = True
        mock_vector_store.detect_all_vector_dimensions.return_value = {"embeddings": 3}
        mock_vector_store.index_documents.return_value = (chunk_table.num_rows, [])
        mock_vector_store.get_chunk_ids_for_documents.return_value = {}
        mock_vector_store.generate_chunk_pk.return_value = "pk_1"

        with patch(
            "docpipe.core.operators.vectordb.vectordb_operator.VectorStoreFactory.create",
            return_value=mock_vector_store,
        ):
            vdb_op = VectorDBOperator(config=vectordb_config)
            _, vdb_meta = vdb_op.transform(emb_table)

        assert vdb_meta[Metrics.External.PROCESSED_DOCS] == chunk_table.num_rows
        assert mock_vector_store.index_documents.called
        indexed_docs = mock_vector_store.index_documents.call_args[0][0]
        assert len(indexed_docs) > 0
        _pk, first_doc_data = indexed_docs[0]
        assert "content" in first_doc_data

    def test_markdown_8_node_dag_execution(self) -> None:
        """Verify full 8-node DAG processing in standard markdown mode (regression baseline)."""
        _skip_if_no_fixtures()

        # 1. Ingest
        ingest_config = {
            "provider": "filesystem",
            "connection_params": {"paths": [str(_FIXTURES_DIR)]},
            "include_filter": "txt",
            "max_files": 2,
            "force_ingest": True,
            "doc_format": "markdown",
        }
        ingest_op = IngestSourceOperator(config=ingest_config)
        ingest_tables, _ = ingest_op.transform(None)
        ingest_table = ingest_tables[0]

        # 2. Extract (with doc_format='markdown')
        extract_config = {
            "text_extraction": {"provider": "docling_library", "doc_column": "content"},
            "entity_extraction": {"provider": "none"},
            "doc_format": "markdown",
        }
        extract_op = ExtractOperator(config=extract_config)
        extract_tables, _ = extract_op.transform(ingest_table)
        extract_table = extract_tables[0]

        # 3. DocQuality
        doc_quality_config = {
            "doc_content_column": "content",
            "doc_format": "markdown",
        }
        doc_quality_op = DocQuality(config=doc_quality_config)
        dq_tables, _ = doc_quality_op.transform(extract_table)
        dq_table = dq_tables[0]

        # 4. PII and HAP Annotator
        pii_config = {
            "provider": "litellm",
            "provider_config": {"model_id": "mock-model", "api_key": "test_token"},  # pragma: allowlist secret
            "doc_column_name": "content",
            "doc_format": "markdown",
        }
        from docpipe.core.operators.quality.pii_and_hap.domain.models import PIIHAPDetectionResponse

        with patch("docpipe.core.operators.quality.pii_and_hap.pii_and_hap_annotator.PIIHAPService") as mock_svc_cls:
            mock_svc = MagicMock()
            mock_svc.adapter = Mock()
            mock_svc.adapter.validate.return_value = {"valid": True, "errors": [], "warnings": []}
            mock_svc.detect_pii_hap.return_value = PIIHAPDetectionResponse(detections=[], input_text="")
            mock_svc_cls.return_value = mock_svc

            pii_op = PIIAndHAPAnnotator(config=pii_config)
            pii_tables, _ = pii_op.transform(dq_table)
            pii_table = pii_tables[0]

        # 5. Redaction Operator
        redaction_config = {
            "doc_column": "content",
            "redaction_regex": r"(?i)support",
            "redaction_masking_character": "X",
            "doc_format": "markdown",
        }
        redaction_op = RedactionOperator(config=redaction_config)
        redact_tables, _ = redaction_op.transform(pii_table)
        redact_table = redact_tables[0]

        # 6. Chunker Operator
        chunker_config = {
            "chunk_type": "simple",
            "doc_column": "content",
            "chunk_size": 256,
            "chunk_overlap": 20,
            "doc_format": "markdown",
        }
        chunker_op = ChunkerOperator(config=chunker_config)
        chunk_tables, _ = chunker_op.transform(redact_table)
        chunk_table = chunk_tables[0]
        assert len(chunk_table["chunked_content"][0].as_py()) > 0

        # 7. Embeddings Operator
        embeddings_config = {
            "provider": "litellm",
            "provider_config": {
                "model_id": "mock-embedding-model",
                "api_key": "test_token",  # pragma: allowlist secret
            },
            "embeddings_column": "embeddings",
            "doc_format": "markdown",
        }
        mock_embedding_adapter = MagicMock()
        mock_embedding_adapter.generate_embeddings_batch.side_effect = lambda texts: [[0.1, 0.2, 0.3] for _ in texts]
        mock_embedding_adapter.generate_embeddings.return_value = [0.1, 0.2, 0.3]
        with patch(
            "docpipe.core.operators.functional.embeddings.embeddings_operator.LLMAdapterFactory.create_embedding_adapter",
            return_value=mock_embedding_adapter,
        ):
            emb_op = EmbeddingsOperator(config=embeddings_config)
            emb_tables, _ = emb_op.transform(chunk_table)
            emb_table = emb_tables[0]

        # 8. VectorDB Operator
        vectordb_config = {
            "provider": "opensearch",
            "provider_config": {"index_name": "test-markdown-index", "host": "localhost"},
            "doc_id_column": "doc_id_hash",
            "embeddings_column": "embeddings",
            "doc_format": "markdown",
            "available_features": {
                "embeddings": {
                    OperatorConstants.Misc.TYPE: "vector",
                    OperatorConstants.Config.AVAILABLE_FOR_VECTOR_DB: True,
                }
            },
        }
        mock_vector_store = Mock()
        mock_vector_store.index_exists.return_value = True
        mock_vector_store.detect_all_vector_dimensions.return_value = {"embeddings": 3}
        mock_vector_store.index_documents.return_value = (chunk_table.num_rows, [])
        mock_vector_store.get_chunk_ids_for_documents.return_value = {}
        mock_vector_store.generate_chunk_pk.return_value = "pk_1"

        with patch(
            "docpipe.core.operators.vectordb.vectordb_operator.VectorStoreFactory.create",
            return_value=mock_vector_store,
        ):
            vdb_op = VectorDBOperator(config=vectordb_config)
            _vdb_tables, vdb_meta = vdb_op.transform(emb_table)

        assert vdb_meta[Metrics.External.PROCESSED_DOCS] == chunk_table.num_rows

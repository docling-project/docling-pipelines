# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Unit tests for Weaviate vector store adapter."""

import copy
import logging
import subprocess
import sys
from typing import Any
from unittest.mock import MagicMock, patch

import pyarrow as pa
import pytest

from docpipe.core.constants.constants import DocpipeConstants
from docpipe.core.operators.vectordb.adapters.outbound.factories.vector_store_factory import (
    VectorStoreFactory,
)
from docpipe.core.operators.vectordb.adapters.outbound.weaviate.adapter import WeaviateAdapter
from docpipe.core.operators.vectordb.adapters.outbound.weaviate.config import WeaviateConfig
from docpipe.core.orchestration.flow_validator import FlowValidator
from docpipe.exceptions.docpipe_exceptions import DocpipeException, FlowValidationException
from docpipe.utils.operators.vectordb_utils import generate_positional_pk

CONNECT_PATH = "docpipe.core.operators.vectordb.adapters.outbound.weaviate.client.WeaviateClient.connect"
CONNECT_TO_CUSTOM_PATH = "docpipe.core.operators.vectordb.adapters.outbound.weaviate.client.weaviate.connect_to_custom"


@pytest.fixture(autouse=True)
def _capture_docpipe_logs(caplog):
    """Attach caplog to the docpipe logger, which may not propagate once setup_logging has run."""
    docpipe_logger = logging.getLogger(DocpipeConstants.LOGGER_NAME)
    docpipe_logger.addHandler(caplog.handler)
    yield
    docpipe_logger.removeHandler(caplog.handler)


def make_validator() -> FlowValidator:
    """Create a FlowValidator backed by the real python orchestrator."""
    from docpipe.core.orchestration.orchestrator_factory import OrchestratorFactory

    return FlowValidator(orchestrator=OrchestratorFactory.create_orchestrator(orchestrator_name="python"))


def vectordb_flow(*, provider_config: dict[str, Any]) -> dict[str, Any]:
    """Build a minimal ingest -> vectordb DAG for a weaviate node."""
    return {
        "dag": [
            {
                "id": "ingest-1",
                "name": "ingest",
                "operator": "ingest_source",
                "config": {"provider": "filesystem", "provider_config": {"paths": ["/tmp"]}},
                "input_edges": [],
                "output_edges": [{"node_id_ref": "vectordb-1"}],
            },
            {
                "id": "vectordb-1",
                "name": "vectordb",
                "operator": "vectordb",
                "config": {"provider": "weaviate", "provider_config": provider_config},
                "input_edges": [{"node_id_ref": "ingest-1"}],
                "output_edges": [],
            },
        ]
    }


def validation_error_text(*, flow: dict[str, Any]) -> str:
    """Run DAG validation and return all error messages joined (empty when valid)."""
    try:
        make_validator().validate_dag(flow_def=flow, global_config={})
    except FlowValidationException as exc:
        return " ".join(str(getattr(err, "message", err)) for err in exc.errors)
    return ""


@pytest.fixture
def base_adapter_config() -> dict[str, Any]:
    return {
        "connection_type": "on-prem",
        "host": "localhost",
        "port": 8080,
        "grpc_port": 50051,
        "collection_name": "TestCollection",
        "auth_type": "none",
        "available_features": {
            "doc_id_hash": "string",
            "chunk_index": "int64",
            "content": "string",
            "embeddings": "list<float32>",
        },
        "feature_mappings": [
            {"feature_name": "doc_id_hash", "mapped_column_name": "pk"},
            {"feature_name": "content", "mapped_column_name": "text"},
            {"feature_name": "embeddings", "mapped_column_name": "embeddings"},
        ],
    }


def test_vector_store_factory_registration():
    """VectorStoreFactory.list_adapters() includes weaviate and create works."""
    adapters = VectorStoreFactory.list_adapters()
    assert "weaviate" in adapters

    with patch(CONNECT_PATH) as mock_conn:
        mock_client = MagicMock()
        mock_conn.return_value = mock_client
        adapter = VectorStoreFactory.create(
            "weaviate",
            connection_type="on-prem",
            host="localhost",
            port=8080,
            grpc_port=50051,
            collection_name="TestCollection",
            auth_type="none",
        )
        assert isinstance(adapter, WeaviateAdapter)
        mock_conn.assert_called_once()


def test_get_config_schema():
    """WeaviateAdapter.get_config_schema() returns WeaviateConfig."""
    assert WeaviateAdapter.get_config_schema() is WeaviateConfig


def test_rejections_before_connect_and_error_message(base_adapter_config):
    """Rejection formats error message and ensures connect was not called."""
    # Missing collection_name
    cfg = dict(base_adapter_config)
    del cfg["collection_name"]
    with patch(CONNECT_PATH) as mock_conn:
        with pytest.raises(DocpipeException) as exc_info:
            VectorStoreFactory.create("weaviate", **cfg)
        mock_conn.assert_not_called()
        assert "collection_name is not provided" in str(exc_info.value)

    # Cloud without cluster_url
    cfg = dict(base_adapter_config)
    cfg["connection_type"] = "cloud"
    with patch(CONNECT_PATH) as mock_conn:
        with pytest.raises(DocpipeException) as exc_info:
            VectorStoreFactory.create("weaviate", **cfg)
        mock_conn.assert_not_called()
        assert "cluster_url is required when connection_type is 'cloud'" in str(exc_info.value)


def test_flow_validator_error_reporting():
    """FlowValidator includes the exact validation error message for a vectordb node."""
    flow = vectordb_flow(provider_config={"connection_type": "on-prem", "host": "localhost"})
    with patch(CONNECT_PATH) as mock_conn:
        error_text = validation_error_text(flow=flow)
    mock_conn.assert_not_called()
    assert "collection_name is not provided" in error_text


def _validate_hook(adapter: WeaviateAdapter) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    adapter.validate_configuration(errors=errors, warnings=warnings)
    return errors, warnings


def test_construction_does_not_validate_mappings(base_adapter_config):
    """Mapping problems do not stop construction; validate_configuration reports them (OpenSearch/Milvus pattern)."""
    cfg = dict(base_adapter_config)
    cfg["feature_mappings"] = [
        {"feature_name": "doc_id_hash", "mapped_column_name": "id_col"},
        {"feature_name": "content", "mapped_column_name": "vector"},
    ]
    with patch(CONNECT_PATH, return_value=MagicMock()) as mock_conn:
        adapter = WeaviateAdapter(**cfg)
    mock_conn.assert_called_once()
    errors, _ = _validate_hook(adapter)
    assert len(errors) == 2


def test_sparse_mode_requires_content_mapping(base_adapter_config):
    """Sparse mode without content mapping is reported by validate_configuration, and accepted with the mapping."""
    cfg = dict(base_adapter_config)
    cfg["add_sparse_vector"] = True
    cfg["feature_mappings"] = [
        {"feature_name": "doc_id_hash", "mapped_column_name": "pk"},
        {"feature_name": "embeddings", "mapped_column_name": "embeddings"},
    ]
    with patch(CONNECT_PATH, return_value=MagicMock()):
        adapter = WeaviateAdapter(**cfg)
    errors, _ = _validate_hook(adapter)
    assert errors == ["A mapping for the content feature is required when add_sparse_vector is true"]

    cfg["feature_mappings"] = [*cfg["feature_mappings"], {"feature_name": "content", "mapped_column_name": "text"}]
    with patch(CONNECT_PATH, return_value=MagicMock()):
        adapter = WeaviateAdapter(**cfg)
    assert _validate_hook(adapter) == ([], [])


def test_invalid_property_names_and_primary_key_rules(base_adapter_config):
    """Reserved property name, primary key mapped away from pk, or another feature mapped to pk are reported."""
    cases = [
        (
            [
                {"feature_name": "doc_id_hash", "mapped_column_name": "pk"},
                {"feature_name": "content", "mapped_column_name": "vector"},
            ],
            "reserved",
        ),
        (
            [
                {"feature_name": "doc_id_hash", "mapped_column_name": "id_col"},
                {"feature_name": "content", "mapped_column_name": "text"},
            ],
            "Primary feature 'doc_id_hash' must be mapped to column 'pk'",
        ),
        (
            [
                {"feature_name": "doc_id_hash", "mapped_column_name": "pk"},
                {"feature_name": "content", "mapped_column_name": "pk"},
            ],
            "Only the primary feature 'doc_id_hash' can be mapped to column 'pk'",
        ),
    ]
    for mappings, expected in cases:
        cfg = dict(base_adapter_config)
        cfg["feature_mappings"] = mappings
        with patch(CONNECT_PATH, return_value=MagicMock()):
            adapter = WeaviateAdapter(**cfg)
        errors, _ = _validate_hook(adapter)
        assert any(expected in err for err in errors), (expected, errors)


def test_mapping_errors_block_writes_when_validation_was_skipped(base_adapter_config):
    """create_index and validate_existing_schema raise a 400 DocpipeException before touching the server."""
    cfg = dict(base_adapter_config)
    cfg["feature_mappings"] = [{"feature_name": "doc_id_hash", "mapped_column_name": "id_col"}]
    with patch(CONNECT_PATH, return_value=MagicMock()):
        adapter = WeaviateAdapter(**cfg)
    adapter.index_manager = MagicMock()
    for call in (adapter.create_index, adapter.validate_existing_schema):
        with pytest.raises(DocpipeException, match="must be mapped to column 'pk'") as exc_info:
            call(dimension_mapping={"embeddings": 3})
        assert exc_info.value.status_code == 400
    adapter.index_manager.create_collection.assert_not_called()
    adapter.index_manager.validate_existing_collection.assert_not_called()


def test_validate_configuration_reports_every_problem(base_adapter_config):
    """All problems are collected in one pass rather than stopping at the first."""
    cfg = dict(base_adapter_config)
    cfg["add_sparse_vector"] = True
    cfg["feature_mappings"] = [
        {"feature_name": "doc_id_hash", "mapped_column_name": "id_col"},
        {"feature_name": "embeddings", "mapped_column_name": "embeddings"},
    ]
    with patch(CONNECT_PATH, return_value=MagicMock()):
        adapter = WeaviateAdapter(**cfg)
    errors, _ = _validate_hook(adapter)
    assert len(errors) == 2
    assert any("content feature" in err for err in errors)
    assert any("'pk'" in err for err in errors)


def test_schema_template_path_warning(base_adapter_config, caplog):
    """schema_template_path emits a warning and does not read file or fail."""
    cfg = dict(base_adapter_config)
    cfg["schema_template_path"] = "/nonexistent/template.json"
    with patch(CONNECT_PATH) as mock_conn:
        mock_conn.return_value = MagicMock()
        with caplog.at_level(logging.WARNING):
            adapter = WeaviateAdapter(**cfg)
        assert "schema_template_path is OpenSearch-specific" in caplog.text
        assert adapter is not None
    _, warnings = _validate_hook(adapter)
    assert any("schema_template_path" in warning for warning in warnings)


def test_acl_handling_and_warnings(base_adapter_config, caplog):
    """allowed_users mapped is dropped with warning; upstream allowed_users unmapped warns."""
    # 1. Mapped allowed_users is dropped
    cfg = copy.deepcopy(base_adapter_config)
    cfg["available_features"]["allowed_users"] = "list<string>"
    cfg["feature_mappings"].append({"feature_name": "allowed_users", "mapped_column_name": "allowed_users"})

    with patch(CONNECT_PATH) as mock_conn:
        mock_conn.return_value = MagicMock()
        with caplog.at_level(logging.WARNING):
            adapter = WeaviateAdapter(**cfg)
        assert "the allowed_users mapping has been dropped" in caplog.text
        assert adapter.index_manager.feature_mappings == [
            {"feature_name": "doc_id_hash", "mapped_column_name": "pk"},
            {"feature_name": "content", "mapped_column_name": "text"},
            {"feature_name": "embeddings", "mapped_column_name": "embeddings"},
        ]

    # 2. Upstream allowed_users unmapped
    caplog.clear()
    cfg2 = copy.deepcopy(base_adapter_config)
    cfg2["available_features"]["allowed_users"] = "list<string>"
    with patch(CONNECT_PATH) as mock_conn:
        mock_conn.return_value = MagicMock()
        with caplog.at_level(logging.WARNING):
            adapter2 = WeaviateAdapter(**cfg2)
        assert "available upstream but is not supported by Weaviate" in caplog.text
        assert adapter2 is not None
    assert any("not supported by Weaviate" in warning for warning in _validate_hook(adapter2)[1])


def test_isolated_import_dependencies():
    """Importing the adapter package in a subprocess loads no acl or api modules."""
    code = (
        "import sys\n"
        "import docpipe.core.operators.vectordb.adapters.outbound.weaviate.adapter\n"
        "loaded = [m for m in sys.modules if 'docpipe.core.operators.acl' in m or 'docpipe.api' in m]\n"
        "assert not loaded, f'Unwanted modules loaded: {loaded}'\n"
        "print('OK')\n"
    )
    res = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=False)
    assert res.returncode == 0, f"Subprocess failed: {res.stderr}"
    assert "OK" in res.stdout


def test_delegations_and_helpers(base_adapter_config):
    """Adapter delegates methods correctly and generates positional primary keys."""
    mock_client = MagicMock()
    with patch(CONNECT_TO_CUSTOM_PATH, return_value=mock_client):
        adapter = WeaviateAdapter(**base_adapter_config)

        # generate_chunk_pk
        pk = adapter.generate_chunk_pk(file_id="doc1", chunk_index=0, chunk_content="text")
        assert pk == generate_positional_pk(file_id="doc1", chunk_index=0)

        # detect_vector_dimension
        table = pa.table({"embeddings": [[0.1, 0.2, 0.3]]})
        dim = adapter.detect_vector_dimension(table=table)
        assert dim == 3

        # detect_all_vector_dimensions
        dims = adapter.detect_all_vector_dimensions(table, vector_columns=["embeddings"])
        assert dims == {"embeddings": 3}

        # index_exists
        with patch.object(adapter.index_manager, "collection_exists", return_value=True) as mock_exists:
            assert adapter.index_exists() is True
            mock_exists.assert_called_once()

        # create_index
        with patch.object(adapter.index_manager, "create_collection") as mock_create:
            adapter.create_index(dimension_mapping={"embeddings": 3})
            mock_create.assert_called_once_with(dimension_mapping={"embeddings": 3})

        # validate_existing_schema
        with patch.object(adapter.index_manager, "validate_existing_collection") as mock_val:
            adapter.validate_existing_schema(dimension_mapping={"embeddings": 3})
            mock_val.assert_called_once_with(dimension_mapping={"embeddings": 3})

        # index_documents
        with patch.object(adapter.batch_processor, "create_batches", return_value=[[]]) as mock_cb:
            with patch.object(adapter.batch_processor, "process_batches", return_value=(1, [])) as mock_pb:
                docs = [("pk1", {"content": "hello"})]
                indexed_count, failed = adapter.index_documents(docs)
                assert indexed_count == 1
                assert failed == []
                mock_cb.assert_called_once_with(documents=docs)
                mock_pb.assert_called_once_with(batches=[[]])

        # delete_documents_by_ids
        with patch.object(adapter.batch_processor, "delete_documents_by_ids", return_value=(5, 0)) as mock_del:
            succ, _ = adapter.delete_documents_by_ids(["pk1", "pk2"])
            assert succ == 5
            mock_del.assert_called_once_with(chunk_pks=["pk1", "pk2"])

        # get_document_count
        with patch.object(adapter.batch_processor, "get_document_count", return_value=42) as mock_count:
            assert adapter.get_document_count() == 42
            mock_count.assert_called_once()

        # get_chunk_ids_for_documents
        with patch.object(
            adapter.batch_processor, "get_chunk_ids_for_documents", return_value={"doc1": ["doc1_0", "doc1_1"]}
        ) as mock_chunks:
            res = adapter.get_chunk_ids_for_documents(["doc1"])
            assert res == {"doc1": {"doc1_0", "doc1_1"}}
            mock_chunks.assert_called_once_with(file_ids=["doc1"])

        # query_by_doc_names
        with patch.object(adapter.batch_processor, "query_by_doc_names", return_value=[{"pk": "doc1_0"}]) as mock_query:
            res = adapter.query_by_doc_names(["doc1.pdf"])
            assert res == [{"pk": "doc1_0"}]
            mock_query.assert_called_once_with(doc_names=["doc1.pdf"], fields=None)

        # refresh_index
        adapter.refresh_index()

        # close is idempotent
        adapter.close()
        adapter.close()
        assert mock_client.close.call_count == 1


def test_exception_after_connect_closes_client(base_adapter_config):
    """Exception raised during index manager or batch processor construction closes client."""
    mock_client = MagicMock()
    with patch(CONNECT_TO_CUSTOM_PATH, return_value=mock_client):
        with patch(
            "docpipe.core.operators.vectordb.adapters.outbound.weaviate.adapter.WeaviateIndexManager",
            side_effect=RuntimeError("IndexManager failed"),
        ):
            with pytest.raises(RuntimeError, match="IndexManager failed"):
                WeaviateAdapter(**base_adapter_config)
            mock_client.close.assert_called_once()


def test_vault_placeholder_flow_validation(base_adapter_config):
    """Vault placeholder credentials with validating_flow defer connection."""
    cfg = dict(base_adapter_config)
    cfg["auth_type"] = "api_key"
    cfg["secure"] = True
    cfg["grpc_secure"] = True
    cfg["api_key"] = DocpipeConstants.VAULT_PLACEHOLDER
    cfg[DocpipeConstants.VALIDATING_FLOW] = True

    with patch(CONNECT_PATH) as mock_conn:
        adapter = WeaviateAdapter(**cfg)
        mock_conn.assert_not_called()
        assert adapter.client_manager is None
        assert adapter.index_manager is None
        assert adapter.batch_processor is None
        assert adapter.index_exists() is False
        assert adapter.get_document_count() == 0
        assert adapter.get_chunk_ids_for_documents(["doc1"]) == {}
        # close is a no-op
        adapter.close()

    # The same placeholder credential without validating_flow calls connect
    cfg[DocpipeConstants.VALIDATING_FLOW] = False
    with patch(CONNECT_PATH) as mock_conn:
        mock_conn.return_value = MagicMock()
        adapter = WeaviateAdapter(**cfg)
        mock_conn.assert_called_once()

    # Plaintext with a Vault placeholder: no connection during flow validation (validate() reports the TLS rule) ...
    cfg_plain = dict(cfg)
    cfg_plain["secure"] = False
    cfg_plain["grpc_secure"] = False
    cfg_plain[DocpipeConstants.VALIDATING_FLOW] = True
    with patch(CONNECT_PATH) as mock_conn:
        adapter = WeaviateAdapter(**cfg_plain)
        mock_conn.assert_not_called()
    assert adapter.client_manager is None

    # ... but a real run fails fast with a 400 DocpipeException
    cfg_plain[DocpipeConstants.VALIDATING_FLOW] = False
    with pytest.raises(DocpipeException) as exc_info:
        WeaviateAdapter(**cfg_plain)
    assert "secure and grpc_secure must both be true" in str(exc_info.value)
    assert exc_info.value.status_code == 400


def test_invalid_config_during_flow_validation_opens_no_connection(base_adapter_config):
    """An unparsable provider_config is deferred to validate() while validating a flow."""
    cfg = dict(base_adapter_config)
    del cfg["collection_name"]
    cfg[DocpipeConstants.VALIDATING_FLOW] = True
    with patch(CONNECT_PATH) as mock_conn:
        adapter = WeaviateAdapter(**cfg)
    mock_conn.assert_not_called()
    assert adapter.client_manager is None
    adapter.close()


def test_docpipe_exception_from_adapter_is_not_rewrapped(base_adapter_config):
    """Factory and operator re-raise the adapter's DocpipeException unchanged (400, original message)."""
    from docpipe.core.operators.vectordb.vectordb_operator import VectorDBOperator

    cfg = {k: v for k, v in base_adapter_config.items() if k not in ("available_features", "feature_mappings")}
    cfg["collection_name"] = "lowercase"
    with patch(CONNECT_PATH) as mock_conn:
        with pytest.raises(DocpipeException) as exc_info:
            VectorStoreFactory.create("weaviate", **cfg)
        assert exc_info.value.status_code == 400
        assert "Failed to create vector store adapter" not in str(exc_info.value)
        with pytest.raises(DocpipeException) as op_exc:
            VectorDBOperator(config={"provider": "weaviate", "provider_config": cfg})
        assert op_exc.value.status_code == 400
        assert "Failed to initialize vector database adapter" not in str(op_exc.value)
        assert "uppercase ASCII letter" in str(op_exc.value)
    mock_conn.assert_not_called()


def test_flow_validator_with_vault_api_key():
    """FlowValidator defers connection for a Vault API key; plaintext fails the TLS rule."""
    provider_config = {
        "connection_type": "on-prem",
        "host": "localhost",
        "port": 8080,
        "secure": True,
        "grpc_secure": True,
        "collection_name": "TestCollection",
        "auth_type": "api_key",
        "api_key": "vault://hashicorp/weaviate/api_key",  # pragma: allowlist secret
    }
    with patch(CONNECT_PATH) as mock_conn:
        error_text = validation_error_text(flow=vectordb_flow(provider_config=provider_config))
    assert error_text == ""
    mock_conn.assert_not_called()

    plaintext = provider_config | {"secure": False, "grpc_secure": False}
    with patch(CONNECT_PATH) as mock_conn:
        error_text = validation_error_text(flow=vectordb_flow(provider_config=plaintext))
    assert "secure and grpc_secure must both be true" in error_text
    mock_conn.assert_not_called()


def test_secret_safety_across_adapter_paths(monkeypatch, caplog):
    """Secret values never appear in raised messages or caplog."""
    monkeypatch.setenv("WEAVIATE_SECRET_KEY", "super-secret-token-12345")
    cfg = {
        "connection_type": "on-prem",
        "host": "localhost",
        "port": 8080,
        "secure": True,
        "grpc_secure": True,
        "collection_name": "TestCollection",
        "auth_type": "api_key",
        "api_key": "$WEAVIATE_SECRET_KEY",
    }
    with patch(CONNECT_TO_CUSTOM_PATH) as mock_conn:
        mock_conn.side_effect = RuntimeError("Failed with super-secret-token-12345")
        with caplog.at_level(logging.DEBUG):
            with pytest.raises(DocpipeException) as exc_info:
                WeaviateAdapter(**cfg)
        assert "super-secret-token-12345" not in str(exc_info.value)
        assert "super-secret-token-12345" not in caplog.text
        assert "[REDACTED]" in str(exc_info.value) or "Failed with" in str(exc_info.value)


def test_managers_receive_resolved_credentials_for_redaction(monkeypatch):
    """Environment-referenced credentials are masked in manager errors by their resolved value."""
    resolved = "resolved-" + "credential-value"
    monkeypatch.setenv("WEAVIATE_REDACTION_KEY", resolved)
    cfg = {
        "connection_type": "on-prem",
        "host": "localhost",
        "port": 8080,
        "secure": True,
        "grpc_secure": True,
        "collection_name": "TestCollection",
        "auth_type": "api_key",
        "api_key": "${WEAVIATE_REDACTION_KEY}",
    }
    with patch(CONNECT_TO_CUSTOM_PATH, return_value=MagicMock()):
        adapter = WeaviateAdapter(**cfg)

    assert resolved in adapter.batch_processor.secrets
    assert "${WEAVIATE_REDACTION_KEY}" not in adapter.batch_processor.secrets
    assert adapter.index_manager._redact(f"echoed {resolved}") == "echoed ***"

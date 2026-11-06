# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Weaviate vector store adapter.

This adapter implements the VectorStorePort interface for Weaviate.
"""

from typing import Any

import pyarrow as pa
from pydantic import BaseModel, ValidationError

from docpipe.core.constants.constants import DocpipeConstants
from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.core.operators.vectordb.adapters.outbound.factories.vector_store_factory import register_vector_store
from docpipe.core.operators.vectordb.adapters.outbound.weaviate.batch_processor import WeaviateBatchProcessor
from docpipe.core.operators.vectordb.adapters.outbound.weaviate.client import WeaviateClient
from docpipe.core.operators.vectordb.adapters.outbound.weaviate.config import (
    ADAPTER_NAME,
    WeaviateConfig,
    format_config_errors,
)
from docpipe.core.operators.vectordb.adapters.outbound.weaviate.index_manager import (
    WeaviateIndexManager,
    validate_primary_key_mapping,
    validate_property_names,
)
from docpipe.core.operators.vectordb.ports.outbound.vector_store import VectorStorePort
from docpipe.exceptions.docpipe_exceptions import DocpipeException
from docpipe.exceptions.error_codes import ErrorCode
from docpipe.utils.infrastructure.logging import get_logger
from docpipe.utils.operators.vectordb_utils import (
    detect_all_vector_dimensions,
    detect_vector_dimension,
    generate_positional_pk,
)

logger = get_logger()


@register_vector_store
class WeaviateAdapter(VectorStorePort):
    """Adapter for Weaviate vector database.

    Wraps WeaviateClient, WeaviateIndexManager, and WeaviateBatchProcessor to satisfy VectorStorePort.
    """

    ADAPTER_NAME = ADAPTER_NAME
    ADAPTER_DISPLAY_NAME = "Weaviate"

    def __init__(self, **adapter_config: Any) -> None:
        # 1. Validate provider_config using WeaviateConfig model
        try:
            config_model = WeaviateConfig.model_validate(adapter_config)
        except ValidationError as exc:
            formatted_errors = format_config_errors(exc)
            raise DocpipeException(
                message="; ".join(formatted_errors),
                status_code=400,
                error_code=ErrorCode.OPERATOR_CONFIGURATION_INVALID,
            ) from None

        self.collection_name = config_model.collection_name
        self.embeddings_column = adapter_config.get(
            OperatorConstants.Columns.EMBEDDINGS_COLUMN,
            OperatorConstants.Columns.EMBEDDINGS_COLUMN_DEFAULT,
        )
        self.add_sparse_vector = adapter_config.get(
            OperatorConstants.VectorDB.ADD_SPARSE_VECTOR,
            OperatorConstants.VectorDB.ADD_SPARSE_VECTOR_DEFAULT,
        )

        available_features: dict[str, Any] = adapter_config.get(OperatorConstants.Config.AVAILABLE_FEATURES, {})
        feature_mappings: list[dict[str, str]] = adapter_config.get(OperatorConstants.Config.FEATURE_MAPPINGS, [])

        # 2. If add_sparse_vector is True, require a mapping for the content feature
        if self.add_sparse_vector:
            has_content_mapping = any(
                WeaviateIndexManager.is_content_mapping(
                    feature_name=entry.get(OperatorConstants.Misc.FEATURE_NAME, entry.get("feature_name")) or "",
                    column_name=entry.get(
                        OperatorConstants.Misc.MAPPED_COLUMN_NAME,
                        entry.get("collection_column", entry.get("mapped_column_name")),
                    )
                    or "",
                )
                for entry in feature_mappings
            )
            if not has_content_mapping:
                raise DocpipeException(
                    message="A mapping for the content feature is required when add_sparse_vector is true",
                    status_code=400,
                    error_code=ErrorCode.OPERATOR_CONFIGURATION_INVALID,
                )

        # 3. Warn once on schema_template_path without reading it
        if adapter_config.get("schema_template_path"):
            logger.warning(
                "schema_template_path is OpenSearch-specific and is not supported by Weaviate; it will be ignored"
            )

        # 4. Drop any allowed_users mapping with one warning, and warn once if allowed_users is upstream but unmapped
        filtered_mappings: list[dict[str, str]] = []
        has_mapped_acl = False
        for entry in feature_mappings:
            fn = entry.get(OperatorConstants.Misc.FEATURE_NAME, entry.get("feature_name"))
            if fn == "allowed_users":
                has_mapped_acl = True
                continue
            filtered_mappings.append(entry)

        if has_mapped_acl:
            logger.warning(
                "Access control (allowed_users) is not supported by Weaviate; the allowed_users mapping has been dropped"
            )
        elif "allowed_users" in available_features:
            logger.warning(
                "Access control (allowed_users) is available upstream but is not supported by Weaviate; ACL checks will not be enforced"
            )

        # 5. Run validate_primary_key_mapping and validate_property_names on filtered mappings
        validate_primary_key_mapping(
            feature_mappings=filtered_mappings,
            available_features=available_features,
        )

        property_names_to_validate: list[str] = []
        for entry in filtered_mappings:
            col_name = entry.get(
                OperatorConstants.Misc.MAPPED_COLUMN_NAME,
                entry.get("collection_column", entry.get("mapped_column_name")),
            )
            feat_name = entry.get(OperatorConstants.Misc.FEATURE_NAME, entry.get("feature_name"))
            if col_name and col_name != "pk" and feat_name != "sparse_embeddings":
                property_names_to_validate.append(col_name)

        validate_property_names(property_names_to_validate)

        # 6. Deferral check for flow validation with Vault placeholder credentials
        validating_flow = bool(adapter_config.get(DocpipeConstants.VALIDATING_FLOW, False))
        credentials_in_use = [config_model.api_key, config_model.bearer_token, config_model.password]
        has_vault_placeholder = any(cred == DocpipeConstants.VAULT_PLACEHOLDER for cred in credentials_in_use if cred)

        if validating_flow and has_vault_placeholder:
            logger.info("Deferring Weaviate connection during flow validation due to Vault credential placeholder")
            self.client_manager: WeaviateClient | None = None
            self.index_manager: WeaviateIndexManager | None = None
            self.batch_processor: WeaviateBatchProcessor | None = None
            return

        # 7. Connect WeaviateClient and construct managers
        self.client_manager = WeaviateClient(
            connection_type=config_model.connection_type,
            host=config_model.host,
            port=config_model.port,
            secure=config_model.secure,
            grpc_host=config_model.grpc_host,
            grpc_port=config_model.grpc_port,
            grpc_secure=config_model.grpc_secure,
            cluster_url=config_model.cluster_url,
            auth_type=config_model.auth_type,
            api_key=config_model.api_key,
            bearer_token=config_model.bearer_token,
            username=config_model.username,
            password=config_model.password,
            timeout_init=config_model.timeout_init,
            timeout_query=config_model.timeout_query,
            timeout_insert=config_model.timeout_insert,
            skip_init_checks=config_model.skip_init_checks,
        )

        client = self.client_manager.connect()

        try:
            secrets = self.client_manager.resolved_secrets
            self.index_manager = WeaviateIndexManager(
                client=client,
                collection_name=config_model.collection_name,
                index_type=config_model.index_type,
                distance_metric=config_model.distance_metric,
                index_parameters=config_model.index_parameters,
                add_sparse_vector=self.add_sparse_vector,
                feature_mappings=filtered_mappings,
                available_features=available_features,
                secrets=secrets,
            )
            self.batch_processor = WeaviateBatchProcessor(
                client=client,
                collection_name=config_model.collection_name,
                batch_size=config_model.batch_size,
                available_features=available_features,
                feature_mappings=filtered_mappings,
                primary_key_field="pk",
                embeddings_column=self.embeddings_column,
                add_sparse_vector=self.add_sparse_vector,
                secrets=secrets,
            )
        except Exception:
            if self.client_manager is not None:
                self.client_manager.close()
            raise

    @staticmethod
    def get_config_schema() -> type[BaseModel]:
        """Return the Pydantic config model class for Weaviate."""
        return WeaviateConfig

    def create_index(self, *, dimension_mapping: dict[str, int]) -> None:
        """Create the Weaviate collection."""
        if self.index_manager:
            self.index_manager.create_collection(dimension_mapping=dimension_mapping)

    def validate_existing_schema(self, *, dimension_mapping: dict[str, int]) -> None:
        """Validate existing Weaviate collection against runtime schema."""
        if self.index_manager:
            self.index_manager.validate_existing_collection(dimension_mapping=dimension_mapping)

    def index_exists(self) -> bool:
        """Check if the Weaviate collection exists."""
        return self.index_manager.collection_exists() if self.index_manager else False

    def index_documents(
        self,
        documents: list[tuple[str, dict[str, Any]]],
    ) -> tuple[int, list[dict[str, Any]]]:
        """Insert a batch of documents into the Weaviate collection."""
        if not self.batch_processor:
            return 0, []
        batches = self.batch_processor.create_batches(documents=documents)
        return self.batch_processor.process_batches(batches=batches)

    def delete_documents_by_ids(self, doc_ids: list[str]) -> tuple[int, int]:
        """Delete documents by their primary keys."""
        return self.batch_processor.delete_documents_by_ids(chunk_pks=doc_ids) if self.batch_processor else (0, 0)

    def get_document_count(self) -> int:
        """Get total object count in the Weaviate collection."""
        return self.batch_processor.get_document_count() if self.batch_processor else 0

    def get_chunk_ids_for_documents(self, doc_ids: list[str]) -> dict[str, set[str]]:
        """Retrieve chunk primary keys for given document file IDs using keyset paging."""
        if not self.batch_processor:
            return {}
        res = self.batch_processor.get_chunk_ids_for_documents(file_ids=doc_ids)
        return {k: set(v) for k, v in res.items()}

    def query_by_doc_names(
        self,
        doc_names: list[str],
        fields: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Query document properties by document names."""
        return (
            self.batch_processor.query_by_doc_names(doc_names=doc_names, fields=fields) if self.batch_processor else []
        )

    def detect_vector_dimension(
        self,
        *,
        table: pa.Table,
        column_name: str | None = None,
    ) -> int | None:
        """Detect vector dimension from embeddings table column."""
        col = column_name or self.embeddings_column
        return detect_vector_dimension(table=table, embeddings_column=col)

    def detect_all_vector_dimensions(
        self,
        table: pa.Table,
        *,
        vector_columns: list[str],
    ) -> dict[str, int]:
        """Detect dimensions for all specified vector columns."""
        return detect_all_vector_dimensions(table=table, vector_columns=vector_columns)

    def generate_chunk_pk(self, *, file_id: str, chunk_index: int, chunk_content: str) -> str:
        """Generate positional primary key from file identity and chunk index (content is unused)."""
        return generate_positional_pk(file_id=file_id, chunk_index=chunk_index)

    def refresh_index(self) -> None:
        """Refresh index (no-op in Weaviate)."""
        logger.debug("Weaviate writes are visible immediately; refresh_index is a no-op")

    def close(self) -> None:
        """Close connection to Weaviate idempotently."""
        if self.client_manager is not None:
            self.client_manager.close()

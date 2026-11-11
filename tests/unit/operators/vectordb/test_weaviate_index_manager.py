# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Unit tests for WeaviateIndexManager."""

from unittest.mock import MagicMock

import httpx
import pytest
from weaviate.classes.config import DataType, Tokenization
from weaviate.exceptions import UnexpectedStatusCodeError, WeaviateConnectionError

from docpipe.core.operators.vectordb.adapters.outbound.weaviate.index_manager import (
    WeaviateIndexManager,
    map_feature_type,
    tokenization_for,
    validate_primary_key_mapping,
    validate_property_names,
)
from docpipe.exceptions.docpipe_exceptions import DocpipeException


class TestWeaviateIndexManagerStaticRules:
    """Test suite for static schema mapping, naming rules, and PK validation."""

    @pytest.mark.parametrize(
        ("feat_type", "expected_data_type"),
        [
            ("text", DataType.TEXT),
            ("string", DataType.TEXT),
            ("keyword", DataType.TEXT),
            ("date", DataType.TEXT),
            ("int8", DataType.INT),
            ("int16", DataType.INT),
            ("int32", DataType.INT),
            ("int64", DataType.INT),
            ("integer", DataType.INT),
            ("long", DataType.INT),
            ("short", DataType.INT),
            ("byte", DataType.INT),
            ("float", DataType.NUMBER),
            ("double", DataType.NUMBER),
            ("number", DataType.NUMBER),
            ("bool", DataType.BOOL),
            ("boolean", DataType.BOOL),
            ("json", DataType.TEXT),
            ("object", DataType.TEXT),
            ("nested", DataType.TEXT),
            ("unknown_custom_type", DataType.TEXT),
            (None, DataType.TEXT),
        ],
    )
    def test_map_feature_type(self, *, feat_type: str | None, expected_data_type: DataType) -> None:
        """Verify feature type to DataType mapping table."""
        assert map_feature_type(feat_type) == expected_data_type

    @pytest.mark.parametrize(
        ("feat_name", "col_name", "feat_type", "expected_tokenization"),
        [
            ("doc_id_hash", "pk", "keyword", Tokenization.FIELD),
            ("id", "doc_id", "text", Tokenization.FIELD),
            ("doc_id", "doc_id", "text", Tokenization.FIELD),
            ("name", "doc_name", "text", Tokenization.FIELD),
            ("doc_name", "doc_name", "text", Tokenization.FIELD),
            ("tag", "tag", "keyword", Tokenization.FIELD),
            ("content", "content", "text", Tokenization.WORD),
            ("text", "text", "text", Tokenization.WORD),
            ("description", "desc", "text", Tokenization.WORD),
        ],
    )
    def test_tokenization_for(
        self,
        *,
        feat_name: str,
        col_name: str,
        feat_type: str | None,
        expected_tokenization: Tokenization,
    ) -> None:
        """Verify identity vs content tokenization rule."""
        assert tokenization_for(feat_name, col_name, feat_type) == expected_tokenization

    @pytest.mark.parametrize(
        "name",
        ["pk", "content", "doc_name", "chunk_index", "embedding_model", "a_1_b"],
    )
    def test_validate_property_names_valid(self, *, name: str) -> None:
        """Verify valid property names pass validation."""
        validate_property_names([name])

    def test_validate_property_names_uppercase_start_rejected(self) -> None:
        """Verify property names starting with uppercase are rejected with suggestion."""
        with pytest.raises(DocpipeException) as exc_info:
            validate_property_names(["Title", "valid_prop"])
        assert exc_info.value.status_code == 400
        assert "starts with an uppercase letter; please use 'title' instead" in str(exc_info.value)

    @pytest.mark.parametrize(
        "reserved_name",
        ["id", "_id", "vector", "_vector", "_creationTimeUnix", "_additional"],
    )
    def test_validate_property_names_reserved_rejected(self, *, reserved_name: str) -> None:
        """Verify reserved property names are rejected."""
        with pytest.raises(DocpipeException) as exc_info:
            validate_property_names([reserved_name])
        assert exc_info.value.status_code == 400
        assert "is reserved in Weaviate" in str(exc_info.value)

    @pytest.mark.parametrize(
        "suffix_name",
        [
            "field_searchable",
            "field_rangeable",
            "item_temp",
            "doc__meta_count",
            "text_propertyLength",
            "val_nullState",
        ],
    )
    def test_validate_property_names_reserved_suffix_rejected(self, *, suffix_name: str) -> None:
        """Verify property names with reserved suffixes are rejected."""
        with pytest.raises(DocpipeException) as exc_info:
            validate_property_names([suffix_name])
        assert exc_info.value.status_code == 400
        assert "ends with reserved suffix" in str(exc_info.value)

    def test_validate_property_names_case_folded_duplicates_rejected(self) -> None:
        """Verify case-folded duplicates are rejected."""
        with pytest.raises(DocpipeException) as exc_info:
            validate_property_names(["my_field", "my_Field"])  # "my_Field" also fails uppercase or duplicate
        assert exc_info.value.status_code == 400

    def test_validate_primary_key_mapping_valid(self) -> None:
        """Verify primary feature mapped to 'pk' passes validation."""
        available_features = {
            "doc_id_hash": {"type": "keyword", "is_primary": True},
            "content": {"type": "text"},
        }
        feature_mappings = [
            {"feature_name": "doc_id_hash", "collection_column": "pk"},
            {"feature_name": "content", "collection_column": "content"},
        ]
        validate_primary_key_mapping(
            feature_mappings=feature_mappings,
            available_features=available_features,
        )

    def test_validate_primary_key_mapping_primary_mapped_to_non_pk_rejected(self) -> None:
        """Verify primary feature mapped to non-pk column is rejected."""
        available_features = {
            "doc_id_hash": {"type": "keyword", "is_primary": True},
        }
        feature_mappings = [
            {"feature_name": "doc_id_hash", "collection_column": "document_pk"},
        ]
        with pytest.raises(DocpipeException) as exc_info:
            validate_primary_key_mapping(
                feature_mappings=feature_mappings,
                available_features=available_features,
            )
        assert exc_info.value.status_code == 400
        assert "Primary feature 'doc_id_hash' must be mapped to column 'pk'" in str(exc_info.value)

    def test_validate_primary_key_mapping_non_primary_mapped_to_pk_rejected(self) -> None:
        """Verify non-primary feature mapped to pk is rejected."""
        available_features = {
            "doc_id_hash": {"type": "keyword", "is_primary": True},
            "other_id": {"type": "string"},
        }
        feature_mappings = [
            {"feature_name": "doc_id_hash", "collection_column": "pk"},
            {"feature_name": "other_id", "collection_column": "pk"},
        ]
        with pytest.raises(DocpipeException) as exc_info:
            validate_primary_key_mapping(
                feature_mappings=feature_mappings,
                available_features=available_features,
            )
        assert exc_info.value.status_code == 400
        assert "Only the primary feature 'doc_id_hash' can be mapped to column 'pk'" in str(exc_info.value)


class TestWeaviateIndexManagerCollectionOperations:
    """Test suite for collection creation, validation against existing schema, and deletion."""

    @pytest.fixture
    def mock_client(self) -> MagicMock:
        """Create mock Weaviate client."""
        return MagicMock()

    def test_collection_exists_and_drop(self, *, mock_client: MagicMock) -> None:
        """Verify collection_exists and drop_collection methods."""
        mock_client.collections.exists.return_value = True
        manager = WeaviateIndexManager(
            client=mock_client,
            collection_name="TestDocs",
        )
        assert manager.collection_exists() is True
        mock_client.collections.exists.assert_called_with("TestDocs")

        assert manager.drop_collection() is True
        mock_client.collections.delete.assert_called_with("TestDocs")

    def test_create_collection_already_exists_raises_409(self, *, mock_client: MagicMock) -> None:
        """Verify create_collection raises 409 if collection already exists."""
        mock_client.collections.exists.return_value = True
        manager = WeaviateIndexManager(
            client=mock_client,
            collection_name="TestDocs",
        )
        with pytest.raises(DocpipeException) as exc_info:
            manager.create_collection(dimension_mapping={"embeddings": 384})
        assert exc_info.value.status_code == 409
        assert "already exists" in str(exc_info.value)

    def test_create_collection_dense_single_vector(self, *, mock_client: MagicMock) -> None:
        """Verify create_collection with single dense vector."""
        mock_client.collections.exists.return_value = False
        manager = WeaviateIndexManager(
            client=mock_client,
            collection_name="TestDocs",
            index_type="hnsw",
            distance_metric="cosine",
            feature_mappings=[
                {"feature_name": "doc_id_hash", "collection_column": "pk"},
                {"feature_name": "content", "collection_column": "content"},
                {"feature_name": "embeddings", "collection_column": "embeddings"},
            ],
            available_features={
                "doc_id_hash": {"type": "keyword", "is_primary": True},
                "content": {"type": "text"},
                "embeddings": {"type": "vector", "dimension": 384},
            },
        )
        manager.create_collection(dimension_mapping={"embeddings": 384})
        mock_client.collections.create.assert_called_once()
        kwargs = mock_client.collections.create.call_args.kwargs
        assert kwargs["name"] == "TestDocs"
        assert len(kwargs["vector_config"]) == 1
        assert kwargs["vector_config"][0].name == "embeddings"

    def test_create_collection_names_vector_after_mapped_column(self, *, mock_client: MagicMock) -> None:
        """The named vector uses the mapped column, not the source feature name."""
        mock_client.collections.exists.return_value = False
        manager = WeaviateIndexManager(
            client=mock_client,
            collection_name="TestDocs",
            feature_mappings=[
                {"feature_name": "doc_id_hash", "mapped_column_name": "pk"},
                {"feature_name": "embeddings", "mapped_column_name": "vector_embeddings"},
                {"feature_name": "embeddings_alt", "mapped_column_name": "vector_embeddings_alt"},
            ],
            available_features={"doc_id_hash": {"type": "keyword", "is_primary": True}},
        )
        manager.create_collection(dimension_mapping={"embeddings": 8, "embeddings_alt": 4})
        names = [v.name for v in mock_client.collections.create.call_args.kwargs["vector_config"]]
        assert names == ["vector_embeddings", "vector_embeddings_alt"]

    def test_validate_existing_collection_resolves_mapped_vector_name(self, *, mock_client: MagicMock) -> None:
        """Existing-collection validation looks the vector up by its mapped column."""
        mock_client.collections.exists.return_value = True
        indexed = MagicMock()
        indexed.vector_index_config.skip = False
        cfg = MagicMock()
        cfg.vector_config = {"vector_embeddings": indexed}
        cfg.properties = []
        collection = mock_client.collections.get.return_value
        collection.config.get.return_value = cfg
        collection.aggregate.over_all.return_value.total_count = 0
        manager = WeaviateIndexManager(
            client=mock_client,
            collection_name="TestDocs",
            feature_mappings=[
                {"feature_name": "doc_id_hash", "mapped_column_name": "pk"},
                {"feature_name": "embeddings", "mapped_column_name": "vector_embeddings"},
            ],
            available_features={"doc_id_hash": {"type": "keyword", "is_primary": True}},
        )
        manager.validate_existing_collection(dimension_mapping={"embeddings": 8})

    @staticmethod
    def _existing_collection(*, mock_client: MagicMock, content_property: str, tokenization: Tokenization) -> None:
        """Mock an existing collection with a pk, an indexed vector, and one content property."""
        mock_client.collections.exists.return_value = True
        indexed = MagicMock()
        indexed.vector_index_config.skip = False

        def prop(*, name: str, tok: Tokenization, searchable: bool) -> MagicMock:
            p = MagicMock()
            p.name = name
            p.data_type = DataType.TEXT
            p.tokenization = tok
            p.index_filterable = True
            p.index_searchable = searchable
            return p

        cfg = MagicMock()
        cfg.vector_config = {"vector_embeddings": indexed}
        cfg.properties = [
            prop(name="pk", tok=Tokenization.FIELD, searchable=True),
            prop(name=content_property, tok=tokenization, searchable=True),
        ]
        collection = mock_client.collections.get.return_value
        collection.config.get.return_value = cfg
        collection.aggregate.over_all.return_value.total_count = 0

    @pytest.mark.parametrize("column", ["body", "content", "text"])
    def test_validate_existing_collection_rejects_field_tokenized_content_in_any_column(
        self, *, mock_client: MagicMock, column: str
    ) -> None:
        """A content feature mapped to any column must be word-tokenized, not only 'content' or 'text'."""
        self._existing_collection(mock_client=mock_client, content_property=column, tokenization=Tokenization.FIELD)
        manager = WeaviateIndexManager(
            client=mock_client,
            collection_name="TestDocs",
            feature_mappings=[
                {"feature_name": "doc_id_hash", "mapped_column_name": "pk"},
                {"feature_name": "content", "mapped_column_name": column},
                {"feature_name": "embeddings", "mapped_column_name": "vector_embeddings"},
            ],
            available_features={
                "doc_id_hash": {"type": "keyword", "is_primary": True},
                "content": {"type": "text"},
            },
        )
        with pytest.raises(DocpipeException) as exc_info:
            manager.validate_existing_collection(dimension_mapping={"embeddings": 8})
        assert f"Content property '{column}'" in str(exc_info.value)

    def test_validate_existing_collection_accepts_word_tokenized_content_in_custom_column(
        self, *, mock_client: MagicMock
    ) -> None:
        self._existing_collection(mock_client=mock_client, content_property="body", tokenization=Tokenization.WORD)
        manager = WeaviateIndexManager(
            client=mock_client,
            collection_name="TestDocs",
            feature_mappings=[
                {"feature_name": "doc_id_hash", "mapped_column_name": "pk"},
                {"feature_name": "content", "mapped_column_name": "body"},
                {"feature_name": "embeddings", "mapped_column_name": "vector_embeddings"},
            ],
            available_features={
                "doc_id_hash": {"type": "keyword", "is_primary": True},
                "content": {"type": "text"},
            },
        )
        manager.validate_existing_collection(dimension_mapping={"embeddings": 8})

    @pytest.mark.parametrize(
        ("content_mapped", "content_available", "expected_content"),
        [
            (True, True, "body"),
            (True, False, "body"),
            (False, True, "text"),
            (False, False, "text"),
        ],
    )
    def test_create_collection_always_declares_a_word_tokenized_content_property(
        self, *, mock_client: MagicMock, content_mapped: bool, content_available: bool, expected_content: str
    ) -> None:
        """The mapped content name is declared, else 'text', whether or not content exists upstream."""
        mock_client.collections.exists.return_value = False
        mappings = [{"feature_name": "doc_id_hash", "mapped_column_name": "pk"}]
        if content_mapped:
            mappings.append({"feature_name": "content", "mapped_column_name": "body"})
        features: dict[str, dict] = {"doc_id_hash": {"type": "keyword", "is_primary": True}}
        if content_available:
            features["content"] = {"type": "text"}
        manager = WeaviateIndexManager(
            client=mock_client, collection_name="TestDocs", feature_mappings=mappings, available_features=features
        )
        manager.create_collection(dimension_mapping={})
        properties = {p.name: p for p in mock_client.collections.create.call_args.kwargs["properties"]}
        assert set(properties) == {"pk", expected_content}
        assert properties[expected_content].tokenization == Tokenization.WORD
        assert properties[expected_content].indexSearchable is True

    def test_validate_existing_collection_canonical_property_name_keeps_interior_case(
        self, *, mock_client: MagicMock
    ) -> None:
        """A property stored with a lower-cased first character is found; interior case is preserved."""
        self._existing_collection(mock_client=mock_client, content_property="text", tokenization=Tokenization.WORD)
        collection = mock_client.collections.get.return_value
        extra = MagicMock()
        extra.name = "Department"  # reported with the first letter as created
        extra.data_type = DataType.TEXT
        extra.tokenization = Tokenization.WORD
        extra.index_filterable = True
        extra.index_searchable = True
        collection.config.get.return_value.properties.append(extra)
        manager = WeaviateIndexManager(
            client=mock_client,
            collection_name="TestDocs",
            feature_mappings=[
                {"feature_name": "doc_id_hash", "mapped_column_name": "pk"},
                {"feature_name": "dept", "mapped_column_name": "department"},
                {"feature_name": "embeddings", "mapped_column_name": "vector_embeddings"},
            ],
            available_features={"doc_id_hash": {"type": "keyword", "is_primary": True}, "dept": {"type": "text"}},
        )
        manager.validate_existing_collection(dimension_mapping={"embeddings": 8})
        collection.config.add_property.assert_not_called()

    def test_validate_existing_collection_rejects_case_only_spelling_conflict(self, *, mock_client: MagicMock) -> None:
        """Mapping 'fileName' onto an existing 'filename' is rejected and nothing is added."""
        self._existing_collection(mock_client=mock_client, content_property="text", tokenization=Tokenization.WORD)
        collection = mock_client.collections.get.return_value
        existing = MagicMock()
        existing.name = "filename"
        existing.data_type = DataType.TEXT
        existing.tokenization = Tokenization.WORD
        existing.index_filterable = True
        existing.index_searchable = True
        collection.config.get.return_value.properties.append(existing)
        manager = WeaviateIndexManager(
            client=mock_client,
            collection_name="TestDocs",
            feature_mappings=[
                {"feature_name": "doc_id_hash", "mapped_column_name": "pk"},
                {"feature_name": "file", "mapped_column_name": "fileName"},
                {"feature_name": "other", "mapped_column_name": "other_prop"},
            ],
            available_features={
                "doc_id_hash": {"type": "keyword", "is_primary": True},
                "file": {"type": "text"},
                "other": {"type": "text"},
            },
        )
        with pytest.raises(DocpipeException) as exc_info:
            manager.validate_existing_collection(dimension_mapping={"embeddings": 8})
        message = str(exc_info.value)
        assert "'fileName'" in message
        assert "'filename'" in message
        assert "letter case" in message
        collection.config.add_property.assert_not_called()

    def test_create_collection_word_tokenizes_content_in_custom_column(self, *, mock_client: MagicMock) -> None:
        mock_client.collections.exists.return_value = False
        manager = WeaviateIndexManager(
            client=mock_client,
            collection_name="TestDocs",
            feature_mappings=[
                {"feature_name": "doc_id_hash", "mapped_column_name": "pk"},
                {"feature_name": "content", "mapped_column_name": "body"},
            ],
            available_features={"doc_id_hash": {"type": "keyword", "is_primary": True}, "content": {"type": "text"}},
        )
        manager.create_collection(dimension_mapping={})
        properties = {p.name: p for p in mock_client.collections.create.call_args.kwargs["properties"]}
        assert properties["body"].tokenization == Tokenization.WORD

    def test_create_collection_redacts_credentials_in_failure(self, *, mock_client: MagicMock) -> None:
        """An SDK error that echoes a resolved credential is masked in the raised message."""
        secret = "resolved-" + "credential-value"  # pragma: allowlist secret
        mock_client.collections.exists.return_value = False
        mock_client.collections.create.side_effect = RuntimeError(f"upstream rejected key {secret}")
        manager = WeaviateIndexManager(client=mock_client, collection_name="TestDocs", secrets=[secret])
        with pytest.raises(DocpipeException) as exc_info:
            manager.create_collection(dimension_mapping={"embeddings": 8})
        assert secret not in str(exc_info.value)
        assert "***" in str(exc_info.value)

    def test_create_collection_sparse_only(self, *, mock_client: MagicMock) -> None:
        """Verify create_collection in sparse-only mode passes non-indexed keyword_only vector."""
        mock_client.collections.exists.return_value = False
        manager = WeaviateIndexManager(
            client=mock_client,
            collection_name="TestDocs",
            add_sparse_vector=True,
            feature_mappings=[
                {"feature_name": "doc_id_hash", "collection_column": "pk"},
                {"feature_name": "content", "collection_column": "content"},
                {"feature_name": "sparse_embeddings", "collection_column": "sparse_embeddings"},
            ],
            available_features={
                "doc_id_hash": {"type": "keyword", "is_primary": True},
                "content": {"type": "text"},
            },
        )
        manager.create_collection(dimension_mapping={})
        mock_client.collections.create.assert_called_once()
        kwargs = mock_client.collections.create.call_args.kwargs
        assert len(kwargs["vector_config"]) == 1
        assert kwargs["vector_config"][0].name == "keyword_only"
        assert kwargs["inverted_index_config"] is not None

    def test_create_collection_invalid_index_parameters_raises_400(self, *, mock_client: MagicMock) -> None:
        """Verify invalid index_parameters raises 400 DocpipeException."""
        mock_client.collections.exists.return_value = False
        manager = WeaviateIndexManager(
            client=mock_client,
            collection_name="TestDocs",
            index_type="hnsw",
            index_parameters={"invalid_unsupported_param": 123},
        )
        with pytest.raises(DocpipeException) as exc_info:
            manager.create_collection(dimension_mapping={"embeddings": 384})
        assert exc_info.value.status_code == 400
        assert "Invalid index_parameters" in str(exc_info.value)

    @staticmethod
    def _status_error(*, status: int, text: str = "refused") -> UnexpectedStatusCodeError:
        return UnexpectedStatusCodeError(text, httpx.Response(status, json={"error": text}))

    def test_create_collection_dynamic_422_converted_to_400(self, *, mock_client: MagicMock) -> None:
        """Verify a 422 status error on a dynamic index becomes a 400 with async indexing guidance."""
        mock_client.collections.exists.return_value = False
        mock_client.collections.create.side_effect = self._status_error(status=422)
        manager = WeaviateIndexManager(client=mock_client, collection_name="TestDocs", index_type="dynamic")
        with pytest.raises(DocpipeException) as exc_info:
            manager.create_collection(dimension_mapping={"embeddings": 384})
        assert exc_info.value.status_code == 400
        assert "requires async indexing enabled" in str(exc_info.value)
        assert exc_info.value.__cause__ is None

    def test_create_collection_422_with_other_index_type_is_generic(self, *, mock_client: MagicMock) -> None:
        """The same status with hnsw gives the generic creation failure, not the async hint."""
        mock_client.collections.exists.return_value = False
        mock_client.collections.create.side_effect = self._status_error(status=422)
        manager = WeaviateIndexManager(client=mock_client, collection_name="TestDocs", index_type="hnsw")
        with pytest.raises(DocpipeException) as exc_info:
            manager.create_collection(dimension_mapping={"embeddings": 384})
        assert exc_info.value.status_code == 500
        assert "async indexing" not in str(exc_info.value)
        assert "status 422" in str(exc_info.value)

    def test_create_collection_message_containing_422_is_not_the_async_hint(self, *, mock_client: MagicMock) -> None:
        """Message text is never inspected: another status whose text contains 422 is a generic failure."""
        mock_client.collections.exists.return_value = False
        mock_client.collections.create.side_effect = self._status_error(status=500, text="object 422 rejected")
        manager = WeaviateIndexManager(client=mock_client, collection_name="TestDocs", index_type="dynamic")
        with pytest.raises(DocpipeException) as exc_info:
            manager.create_collection(dimension_mapping={"embeddings": 384})
        assert exc_info.value.status_code == 500
        assert "async indexing" not in str(exc_info.value)

    def test_collection_exists_raises_instead_of_returning_false(self, *, mock_client: MagicMock) -> None:
        """An unanswerable existence check raises (503 when the server is unreachable)."""
        mock_client.collections.exists.side_effect = WeaviateConnectionError("down")
        manager = WeaviateIndexManager(client=mock_client, collection_name="TestDocs")
        with pytest.raises(DocpipeException, match="'TestDocs' exists") as exc_info:
            manager.collection_exists()
        assert exc_info.value.status_code == 503
        assert exc_info.value.__cause__ is None

    def test_collection_exists_error_is_redacted(self, *, mock_client: MagicMock) -> None:
        secret = "resolved-" + "credential-value"  # pragma: allowlist secret
        mock_client.collections.exists.side_effect = RuntimeError(f"denied for {secret}")
        manager = WeaviateIndexManager(client=mock_client, collection_name="TestDocs", secrets=[secret])
        with pytest.raises(DocpipeException) as exc_info:
            manager.collection_exists()
        assert secret not in str(exc_info.value)

    def test_validate_existing_collection_missing_raises_400(self, *, mock_client: MagicMock) -> None:
        """Verify validate_existing_collection raises 400 if collection does not exist."""
        mock_client.collections.exists.return_value = False
        manager = WeaviateIndexManager(
            client=mock_client,
            collection_name="MissingCollection",
        )
        with pytest.raises(DocpipeException) as exc_info:
            manager.validate_existing_collection(dimension_mapping={"embeddings": 384})
        assert exc_info.value.status_code == 400
        assert "does not exist" in str(exc_info.value)

    def test_validate_existing_collection_keyword_only_with_dense_run_fails(self, *, mock_client: MagicMock) -> None:
        """Verify a keyword-only collection is rejected for a dense vector run."""
        mock_client.collections.exists.return_value = True
        mock_coll = MagicMock()
        mock_cfg = MagicMock()

        # Vector config with skip=True (keyword only)
        mock_vec_cfg = MagicMock()
        mock_vec_cfg.vector_index_config.skip = True
        mock_cfg.vector_config = {"keyword_only": mock_vec_cfg}
        mock_cfg.properties = []
        mock_coll.config.get.return_value = mock_cfg
        mock_client.collections.get.return_value = mock_coll

        manager = WeaviateIndexManager(
            client=mock_client,
            collection_name="TestDocs",
        )
        with pytest.raises(DocpipeException) as exc_info:
            manager.validate_existing_collection(dimension_mapping={"embeddings": 384})
        assert exc_info.value.status_code == 400
        assert "is a keyword-only collection and has no indexed vector" in str(exc_info.value)

    def test_validate_existing_collection_dimension_mismatch_fails(self, *, mock_client: MagicMock) -> None:
        """Verify vector dimension mismatch fails validation."""
        mock_client.collections.exists.return_value = True
        mock_coll = MagicMock()
        mock_cfg = MagicMock()

        # Indexed vector
        mock_vec_cfg = MagicMock()
        mock_vec_cfg.vector_index_config.skip = False
        mock_cfg.vector_config = {"embeddings": mock_vec_cfg}

        # Valid properties
        pk_prop = MagicMock(
            spec=[
                "name",
                "data_type",
                "dataType",
                "tokenization",
                "index_filterable",
                "indexFilterable",
                "index_searchable",
                "indexSearchable",
            ]
        )
        pk_prop.name = "pk"
        pk_prop.data_type = DataType.TEXT
        pk_prop.dataType = DataType.TEXT
        pk_prop.tokenization = Tokenization.FIELD
        pk_prop.indexFilterable = True
        pk_prop.indexSearchable = True

        content_prop = MagicMock(
            spec=[
                "name",
                "data_type",
                "dataType",
                "tokenization",
                "index_filterable",
                "indexFilterable",
                "index_searchable",
                "indexSearchable",
            ]
        )
        content_prop.name = "content"
        content_prop.data_type = DataType.TEXT
        content_prop.dataType = DataType.TEXT
        content_prop.tokenization = Tokenization.WORD
        content_prop.indexFilterable = True
        content_prop.indexSearchable = True

        mock_cfg.properties = [pk_prop, content_prop]
        mock_coll.config.get.return_value = mock_cfg
        mock_coll.aggregate.over_all.return_value.total_count = 5

        # Sample object with dimension 768 instead of 384
        sample_obj = MagicMock()
        sample_obj.vector = {"embeddings": [0.1] * 768}
        mock_coll.query.fetch_objects.return_value.objects = [sample_obj]
        mock_client.collections.get.return_value = mock_coll

        manager = WeaviateIndexManager(
            client=mock_client,
            collection_name="TestDocs",
            available_features={"content": {"type": "text"}},
        )
        with pytest.raises(DocpipeException) as exc_info:
            manager.validate_existing_collection(dimension_mapping={"embeddings": 384})
        assert exc_info.value.status_code == 400
        assert "Vector dimension mismatch for 'embeddings'" in str(exc_info.value)

    def test_validate_existing_collection_identity_tokenization_mismatch_fails(self, *, mock_client: MagicMock) -> None:
        """Verify identity property with WORD tokenization fails validation."""
        mock_client.collections.exists.return_value = True
        mock_coll = MagicMock()
        mock_cfg = MagicMock()

        # Indexed vector
        mock_vec_cfg = MagicMock()
        mock_vec_cfg.vector_index_config.skip = False
        mock_cfg.vector_config = {"embeddings": mock_vec_cfg}

        # pk with WORD tokenization (invalid for identity)
        pk_prop = MagicMock(
            spec=[
                "name",
                "data_type",
                "dataType",
                "tokenization",
                "index_filterable",
                "indexFilterable",
                "index_searchable",
                "indexSearchable",
            ]
        )
        pk_prop.name = "pk"
        pk_prop.data_type = DataType.TEXT
        pk_prop.dataType = DataType.TEXT
        pk_prop.tokenization = Tokenization.WORD
        pk_prop.indexFilterable = True
        pk_prop.indexSearchable = True

        content_prop = MagicMock(
            spec=[
                "name",
                "data_type",
                "dataType",
                "tokenization",
                "index_filterable",
                "indexFilterable",
                "index_searchable",
                "indexSearchable",
            ]
        )
        content_prop.name = "content"
        content_prop.data_type = DataType.TEXT
        content_prop.dataType = DataType.TEXT
        content_prop.tokenization = Tokenization.WORD
        content_prop.indexFilterable = True
        content_prop.indexSearchable = True

        mock_cfg.properties = [pk_prop, content_prop]
        mock_coll.config.get.return_value = mock_cfg
        mock_coll.aggregate.over_all.return_value.total_count = 0
        mock_client.collections.get.return_value = mock_coll

        manager = WeaviateIndexManager(
            client=mock_client,
            collection_name="TestDocs",
            available_features={"content": {"type": "text"}},
        )
        with pytest.raises(DocpipeException) as exc_info:
            manager.validate_existing_collection(dimension_mapping={"embeddings": 384})
        assert exc_info.value.status_code == 400
        assert "Identity property 'pk' must have field tokenization" in str(exc_info.value)

    def test_validate_existing_collection_adds_missing_properties(self, *, mock_client: MagicMock) -> None:
        """Verify missing scalar properties are added when validation passes."""
        mock_client.collections.exists.return_value = True
        mock_coll = MagicMock()
        mock_cfg = MagicMock()

        mock_vec_cfg = MagicMock()
        mock_vec_cfg.vector_index_config.skip = False
        mock_cfg.vector_config = {"embeddings": mock_vec_cfg}

        # Existing properties have pk and content, but missing "doc_name"
        pk_prop = MagicMock(
            spec=[
                "name",
                "data_type",
                "dataType",
                "tokenization",
                "index_filterable",
                "indexFilterable",
                "index_searchable",
                "indexSearchable",
            ]
        )
        pk_prop.name = "pk"
        pk_prop.data_type = DataType.TEXT
        pk_prop.dataType = DataType.TEXT
        pk_prop.tokenization = Tokenization.FIELD
        pk_prop.indexFilterable = True
        pk_prop.indexSearchable = True

        content_prop = MagicMock(
            spec=[
                "name",
                "data_type",
                "dataType",
                "tokenization",
                "index_filterable",
                "indexFilterable",
                "index_searchable",
                "indexSearchable",
            ]
        )
        content_prop.name = "content"
        content_prop.data_type = DataType.TEXT
        content_prop.dataType = DataType.TEXT
        content_prop.tokenization = Tokenization.WORD
        content_prop.indexFilterable = True
        content_prop.indexSearchable = True

        mock_cfg.properties = [pk_prop, content_prop]
        mock_coll.config.get.return_value = mock_cfg
        mock_coll.aggregate.over_all.return_value.total_count = 0
        mock_client.collections.get.return_value = mock_coll

        manager = WeaviateIndexManager(
            client=mock_client,
            collection_name="TestDocs",
            feature_mappings=[
                {"feature_name": "doc_id_hash", "collection_column": "pk"},
                {"feature_name": "content", "collection_column": "content"},
                {"feature_name": "doc_name", "collection_column": "doc_name"},
            ],
            available_features={
                "doc_id_hash": {"type": "keyword", "is_primary": True},
                "content": {"type": "text"},
                "doc_name": {"type": "string"},
            },
        )
        manager.validate_existing_collection(dimension_mapping={"embeddings": 384})
        mock_coll.config.add_property.assert_called_once()
        added_prop = mock_coll.config.add_property.call_args[0][0]
        assert added_prop.name == "doc_name"

    def test_validate_existing_collection_adds_missing_properties_failure_raises(
        self, *, mock_client: MagicMock
    ) -> None:
        """A failed add_property raises: later writes to the missing property would fail."""
        mock_client.collections.exists.return_value = True
        mock_coll = MagicMock()
        mock_cfg = MagicMock()

        mock_vec_cfg = MagicMock()
        mock_vec_cfg.vector_index_config.skip = False
        mock_cfg.vector_config = {"embeddings": mock_vec_cfg}

        # Existing properties have pk and content, but missing "doc_name"
        pk_prop = MagicMock(
            spec=[
                "name",
                "data_type",
                "dataType",
                "tokenization",
                "index_filterable",
                "indexFilterable",
                "index_searchable",
                "indexSearchable",
            ]
        )
        pk_prop.name = "pk"
        pk_prop.data_type = DataType.TEXT
        pk_prop.dataType = DataType.TEXT
        pk_prop.tokenization = Tokenization.FIELD
        pk_prop.indexFilterable = True
        pk_prop.indexSearchable = True

        content_prop = MagicMock(
            spec=[
                "name",
                "data_type",
                "dataType",
                "tokenization",
                "index_filterable",
                "indexFilterable",
                "index_searchable",
                "indexSearchable",
            ]
        )
        content_prop.name = "content"
        content_prop.data_type = DataType.TEXT
        content_prop.dataType = DataType.TEXT
        content_prop.tokenization = Tokenization.WORD
        content_prop.indexFilterable = True
        content_prop.indexSearchable = True

        mock_cfg.properties = [pk_prop, content_prop]
        mock_coll.config.get.return_value = mock_cfg
        mock_coll.aggregate.over_all.return_value.total_count = 0
        mock_client.collections.get.return_value = mock_coll

        manager = WeaviateIndexManager(
            client=mock_client,
            collection_name="TestDocs",
            feature_mappings=[
                {"feature_name": "doc_id_hash", "collection_column": "pk"},
                {"feature_name": "content", "collection_column": "content"},
                {"feature_name": "doc_name", "collection_column": "doc_name"},
            ],
            available_features={
                "doc_id_hash": {"type": "keyword", "is_primary": True},
                "content": {"type": "text"},
                "doc_name": {"type": "string"},
            },
        )
        mock_coll.config.add_property.side_effect = RuntimeError("add failed")
        with pytest.raises(DocpipeException, match=r"Failed to add property 'doc_name'.*'TestDocs'") as exc_info:
            manager.validate_existing_collection(dimension_mapping={"embeddings": 384})
        assert exc_info.value.status_code == 500

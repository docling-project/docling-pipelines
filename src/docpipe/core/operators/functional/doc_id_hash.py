from typing import Any

import pyarrow as pa
from dpk_doc_id import DocIDTransform, doc_column_name_key, hash_column_name_key

from docpipe.core.constants.constants import AttributeDataTypes, DocpipeConstants, Metrics
from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.core.operators.abstract_operator import AbstractOperator, OperatorCategory
from docpipe.core.operators.operator_utils import OperatorUtils


class DocIdHashOperator(AbstractOperator):
    """
    Implements generating a doc id by hashing content.
    Uses dpk_doc_id.DocIDTransform to generate a hash of the document
    content column.

    This is an internal operator (IS_OPERATOR_AVAILABLE = False).
    It is used internally by other operators (e.g.,ExtractOperator, ChunkerOperator,
    EmbeddingsOperator) to generate document hash IDs.
    """

    short_name: str = OperatorConstants.Operators.DOC_ID_OPERATOR
    category: OperatorCategory = OperatorCategory.Functional
    owner = DocpipeConstants.OWNER_DOCPIPE

    def __init__(self, config: dict[str, Any]) -> None:
        """
        Initialize the DocIdHashOperator.

        Args:
            config: Configuration dictionary containing:
                - doc_column: Which column contains the text content (default: "content")
                - doc_id_hash_column: Name of the output hash column (default: "doc_id_hash")
        """
        # Set the hash column name and doc column name in config for DocIDTransform
        config[hash_column_name_key] = config.get(
            OperatorConstants.Columns.DOC_ID_HASH, OperatorConstants.Columns.DOC_ID_HASH_DEFAULT
        )
        config[doc_column_name_key] = config.get(
            OperatorConstants.Columns.DOC_COLUMN, OperatorConstants.Columns.DOC_COLUMN_DEFAULT
        )
        super().__init__(config)
        self.hash_column: str = config.get(
            OperatorConstants.Columns.DOC_ID_HASH, OperatorConstants.Columns.DOC_ID_HASH_DEFAULT
        )

        # Initialize DocIDTransform if available
        self._doc_id_transform: Any | None = DocIDTransform(config)

    @staticmethod
    def get_metadata() -> dict[str, Any]:
        """Get metadata."""
        return {
            OperatorConstants.Misc.IS_OPERATOR_AVAILABLE: False,
            OperatorConstants.Misc.CATEGORY: DocIdHashOperator.category.value,
            OperatorConstants.Misc.LABEL: "Document ID Hash",
            OperatorConstants.Config.DESCRIPTION: "Generates document hash IDs by hashing content",
            OperatorConstants.Config.ATTRIBUTES: {
                OperatorConstants.Columns.DOC_COLUMN: {
                    OperatorConstants.Misc.NAME: "Document Column",
                    OperatorConstants.Config.DESCRIPTION: "Column containing document content for hashing",
                    OperatorConstants.Config.REQUIRED: False,
                    OperatorConstants.Config.DEFAULT: OperatorConstants.Columns.DOC_COLUMN_DEFAULT,
                    OperatorConstants.Misc.TYPE: AttributeDataTypes.STRING,
                },
                OperatorConstants.Columns.DOC_ID_HASH: {
                    OperatorConstants.Misc.NAME: "Hash Column Name",
                    OperatorConstants.Config.DESCRIPTION: "Name of the output column for document hash IDs",
                    OperatorConstants.Config.REQUIRED: False,
                    OperatorConstants.Config.DEFAULT: OperatorConstants.Columns.DOC_ID_HASH_DEFAULT,
                    OperatorConstants.Misc.TYPE: AttributeDataTypes.STRING,
                },
            },
            OperatorConstants.Config.FEATURES: {
                OperatorConstants.Columns.DOC_ID_HASH_DEFAULT: {
                    OperatorConstants.Misc.NAME: "Document Hash ID",
                    OperatorConstants.Config.DESCRIPTION: "Generated hash ID for the document (output column)",
                    OperatorConstants.Config.AVAILABLE_FOR_VECTOR_DB: True,
                    OperatorConstants.Misc.TYPE: OperatorConstants.Types.TYPE_STRING,
                    OperatorConstants.Misc.IS_PRIMARY: True,
                    OperatorConstants.Misc.TAGS: [OperatorConstants.Misc.MANDATORY, OperatorConstants.Misc.PRIMARY],
                },
            },
        }

    def transform(self, table: pa.Table) -> tuple[list[pa.Table], dict[str, Any]]:
        """
        Generate hash IDs for documents by hashing the content column.

        Uses DocIDTransform from dpk_doc_id.

        Args:
            table: Input PyArrow table containing document content

        Returns:
            Tuple of (list of output tables, metadata dictionary)
        """
        total_docs: int = OperatorUtils.find_doc_count(table=table)
        metadata: dict[str, Any] = self.create_base_metadata(total_docs_count=total_docs)

        # Drop existing hash column before calling DocIDTransform to prevent it
        # from renaming it to "<hash_column>.original"
        if self.hash_column in table.column_names:
            table = table.drop_columns([self.hash_column])
        # Use DocIDTransform from dpk_doc_id
        result: tuple[list[pa.Table], dict[str, Any]] = self._doc_id_transform.transform(table)
        table = result[0][0]
        metadata["hashed_rows"] = total_docs
        metadata[Metrics.External.PROCESSED_DOCS] = total_docs

        return [table], metadata

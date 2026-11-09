# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""
ML Enrichment Operator

This operator computes text quality features using the dpk_enrichment package.
It analyzes document content to extract various quality metrics including:
- Basic statistics (word count, character count, paragraph count)
- Character ratios (alphanumeric, punctuation, control characters)
- Duplication metrics (paragraph and n-gram duplicates)
- Special pattern detection (ellipsis, bullet points, etc.)

Dependencies:
    - dpk_enrichment: IBM's text quality feature extraction package
    - NLTK punkt_tab: Required tokenizer data (auto-downloaded on first use)
"""

from typing import Any

import pyarrow as pa
from dpk_enrichment import EnrichmentTransform
from dpk_enrichment.features import DEFAULT_TEXT_ENRICHER_DICT

from docpipe.core.constants import (
    DocpipeConstants,
    ExecutionStatus,
    Metrics,
    OperatorConstants,
)
from docpipe.core.operators.abstract_operator import AbstractOperator, OperatorCategory
from docpipe.core.operators.operator_utils import OperatorUtils
from docpipe.utils.infrastructure.logging import get_logger
from docpipe.utils.infrastructure.nltk_data_manager import ensure_nltk_data

logger = get_logger()

# Metadata keys for ML enrichment results
FEATURES_ADDED_KEY: str = "features_added"
ENRICHMENT_COLUMNS_KEY: str = "enrichment_columns"


class MLEnrichmentOperator(EnrichmentTransform, AbstractOperator):
    """
    ML Enrichment Operator computes text quality features for document content.

    This operator uses the dpk_enrichment package to analyze text and extract
    30+ quality metrics that can be used for data quality assessment, filtering,
    and machine learning feature engineering.

    Features computed include:
    - Basic statistics: num_words, num_chars, num_paragraphs, num_newlines
    - Averages: avg_word_length, avg_paragraph_length
    - Character ratios: alphanumeric, punctuation, control characters
    - Duplication detection: paragraph duplicates, n-gram duplicates
    - Special patterns: ellipsis, bullet points, tabs, hashes
    """

    short_name: str = OperatorConstants.Operators.ML_ENRICHMENT
    category: OperatorCategory = OperatorCategory.Quality
    owner = DocpipeConstants.OWNER_DOCPIPE

    def __init__(self, config: dict[str, Any]) -> None:
        """
        Initialize the ML Enrichment operator.

        Parameters:
            config: Configuration dictionary with the following keys:
                - doc_column: Name of the column containing document text (default: "content")
                - lang_column: Name of the column containing language identifier (default: "lang_name")
                - output_column_prefix: Prefix to add to all output columns (default: "")
                - newline_normalized_column_name: Optional column name for normalized text
                - error_column_name: Optional column name for errors
                - <feature>_column_name: Optional custom name for each feature column
        """
        # Ensure NLTK data is available (punkt_tab tokenizer)
        # This will auto-download on first use with SSL bypass if needed
        ensure_nltk_data("punkt_tab")

        # Get configuration parameters with defaults
        self.lang_column: str = config.get(
            OperatorConstants.Columns.LANG_COLUMN, OperatorConstants.Columns.LANGUAGE_NAME_COLUMN_KEY
        )
        self.output_column_prefix: str = config.get(OperatorConstants.Columns.OUTPUT_COLUMN_PREFIX, "")
        self.newline_normalized_column_name: str = config.get(
            OperatorConstants.Columns.NEWLINE_NORMALIZED_COLUMN_NAME, ""
        )
        self.error_column_name: str = config.get(OperatorConstants.Columns.ERROR_COLUMN_NAME, "")

        # Update config with dpk_enrichment-specific keys
        config.update(
            {
                OperatorConstants.Columns.CONTENT_COLUMN_NAME: config.get(
                    OperatorConstants.Columns.DOC_COLUMN, OperatorConstants.Columns.DOC_COLUMN_DEFAULT
                ),
                OperatorConstants.Columns.LANG_COLUMN_NAME: self.lang_column,
                OperatorConstants.Columns.OUTPUT_COLUMN_PREFIX: self.output_column_prefix,
                OperatorConstants.Columns.NEWLINE_NORMALIZED_COLUMN_NAME: self.newline_normalized_column_name,
                OperatorConstants.Columns.ERROR_COLUMN_NAME: self.error_column_name,
            }
        )

        # Call both parent constructors
        super().__init__(config=config)

        # Setup logging context
        self.common_log_arguments: dict[str, Any] = {
            DocpipeConstants.JOB_ID: self.job_id,
            DocpipeConstants.JOB_RUN_ID: self.job_run_id,
        }

    @staticmethod
    def get_required_features() -> list[str]:
        """Return list of required input features."""
        return [
            OperatorConstants.Columns.DOC_COLUMN_DEFAULT,
            OperatorConstants.Columns.LANGUAGE_NAME_COLUMN_KEY,
        ]

    def validate(self, errors: list[str], warnings: list[str], available_features: list[str]) -> None:
        """
        Validate operator configuration and dependencies.

        Args:
            errors: List to append validation errors
            warnings: List to append validation warnings
            available_features: List of available input features
        """
        # Map configured custom columns to default names so parent class validates them correctly
        mapped_features = list(available_features)
        if self.doc_column in available_features:
            mapped_features.append(OperatorConstants.Columns.DOC_COLUMN_DEFAULT)
        if self.lang_column and self.lang_column in available_features:
            mapped_features.append(OperatorConstants.Columns.LANGUAGE_NAME_COLUMN_KEY)

        # Call parent validation
        super().validate(errors, warnings, mapped_features)

        # Check for output column conflicts
        if self.should_validate_field(field_value=self.output_column_prefix):
            for feature_key in DEFAULT_TEXT_ENRICHER_DICT.keys():
                output_col = f"{self.output_column_prefix}{feature_key}"
                if output_col in available_features:
                    warnings.append(f"Output column '{output_col}' already exists and will be overwritten")

    @staticmethod
    def get_metadata() -> dict[str, Any]:
        """
        Get operator metadata including features and attributes.

        Returns:
            Dictionary containing operator metadata with features and configuration
        """
        # Build features dictionary for all enrichment metrics
        features = {}

        # Add all default enrichment features (with empty prefix as default)
        for feature_key, default_value in DEFAULT_TEXT_ENRICHER_DICT.items():
            column_name = feature_key  # No prefix by default
            features[column_name] = {
                OperatorConstants.Misc.NAME: feature_key.replace("_", " ").title(),
                OperatorConstants.Config.DESCRIPTION: f"Text quality metric: {feature_key}",
                OperatorConstants.Config.AVAILABLE_FOR_FILTER: True,
                OperatorConstants.Misc.TYPE: OperatorConstants.Types.TYPE_FLOAT
                if isinstance(default_value, float)
                else OperatorConstants.Types.TYPE_INT32,
            }

        # Add optional columns (always include in metadata)
        features["newline_normalized_text"] = {
            OperatorConstants.Misc.NAME: "Newline Normalized Text",
            OperatorConstants.Config.DESCRIPTION: "Text with normalized newlines",
            OperatorConstants.Config.AVAILABLE_FOR_FILTER: False,
            OperatorConstants.Misc.TYPE: OperatorConstants.Types.TYPE_STRING,
        }

        features["processing_error"] = {
            OperatorConstants.Misc.NAME: "Processing Error",
            OperatorConstants.Config.DESCRIPTION: "Error message if processing failed",
            OperatorConstants.Config.AVAILABLE_FOR_FILTER: False,
            OperatorConstants.Misc.TYPE: OperatorConstants.Types.TYPE_STRING,
        }

        return {
            # The enrichment metrics need no credentials; this operator accepts no references.
            "secret_fields": [],
            OperatorConstants.Misc.CATEGORY: MLEnrichmentOperator.category.value,
            OperatorConstants.Misc.IS_OPERATOR_AVAILABLE: MLEnrichmentOperator.is_available(),
            OperatorConstants.Misc.LABEL: "ML Text Enrichment",
            OperatorConstants.Config.DESCRIPTION: (
                "Computes 30+ text quality features including word counts, character ratios, "
                "duplication metrics, and special pattern detection for data quality assessment"
            ),
            OperatorConstants.Config.FEATURES: features,
            OperatorConstants.Config.ATTRIBUTES: {
                OperatorConstants.Columns.DOC_COLUMN: {
                    OperatorConstants.Misc.NAME: "Document Column",
                    OperatorConstants.Config.DESCRIPTION: "Name of the column containing document text",
                    OperatorConstants.Config.REQUIRED: False,
                    OperatorConstants.Config.DEFAULT: OperatorConstants.Columns.DOC_COLUMN_DEFAULT,
                    OperatorConstants.Misc.TYPE: OperatorConstants.Types.TYPE_STRING,
                },
                OperatorConstants.Columns.LANG_COLUMN: {
                    OperatorConstants.Misc.NAME: "Language Column",
                    OperatorConstants.Config.DESCRIPTION: "Name of the column containing language identifier",
                    OperatorConstants.Config.REQUIRED: False,
                    OperatorConstants.Config.DEFAULT: OperatorConstants.Columns.LANGUAGE_NAME_COLUMN_KEY,
                    OperatorConstants.Misc.TYPE: OperatorConstants.Types.TYPE_STRING,
                },
                OperatorConstants.Columns.OUTPUT_COLUMN_PREFIX: {
                    OperatorConstants.Misc.NAME: "Output Column Prefix",
                    OperatorConstants.Config.DESCRIPTION: "Prefix to add to all output column names",
                    OperatorConstants.Config.REQUIRED: False,
                    OperatorConstants.Config.DEFAULT: "",
                    OperatorConstants.Misc.TYPE: OperatorConstants.Types.TYPE_STRING,
                },
            },
        }

    def transform(self, table: pa.Table, file_name: str | None = None) -> tuple[list[pa.Table], dict[str, Any]]:
        """
        Transform the input table by computing text enrichment features.

        Args:
            table: Input PyArrow table with document content
            file_name: Optional file name for logging

        Returns:
            Tuple of (list of output tables, metadata dictionary)
        """
        logger.info("Running ML Enrichment on table with %s rows", table.num_rows, extra=self.common_log_arguments)

        total_docs: int = OperatorUtils.find_doc_count(table=table)
        metadata: dict[str, Any] = self.create_base_metadata(total_docs_count=total_docs)

        if table.num_rows == 0:
            logger.info("Empty table provided, returning as-is", extra=self.common_log_arguments)
            return [table], metadata

        output_tables = self._run_enrichment(table=table, file_name=file_name)
        self._record_enrichment_errors(output_tables=output_tables, metadata=metadata)
        self._build_enrichment_metadata(
            output_tables=output_tables, input_table=table, total_docs=total_docs, metadata=metadata
        )

        if metadata.get(Metrics.External.FAILED_DOCS_COUNT, 0) > 0:
            logger.warning(
                "ML Enrichment completed with %s failed documents",
                metadata[Metrics.External.FAILED_DOCS_COUNT],
                extra=self.common_log_arguments,
            )
        else:
            logger.info("ML Enrichment completed successfully", extra=self.common_log_arguments)

        return output_tables, metadata

    def _run_enrichment(self, *, table: pa.Table, file_name: str | None) -> list[pa.Table]:
        """Strip DocLang for enrichment, call parent transform, restore original column."""
        doc_col = self.config.get(OperatorConstants.Columns.DOC_COLUMN, OperatorConstants.Columns.DOC_COLUMN_DEFAULT)
        processing_table = OperatorUtils.strip_doclang_column(table, col_name=doc_col, doc_format=self.doc_format)

        output_tables, _metadata = super().transform(table=processing_table, file_name=file_name or "")

        return [
            OperatorUtils.restore_doclang_column(
                t,
                original_table=table,
                col_name=doc_col,
                processing_table=processing_table,
            )
            for t in output_tables
        ]

    def _record_enrichment_errors(self, *, output_tables: list[pa.Table], metadata: dict[str, Any]) -> None:
        """Scan the error column (if present) and record any per-document failures."""
        if not (output_tables and self.error_column_name and self.error_column_name in output_tables[0].column_names):
            return

        error_column = output_tables[0][self.error_column_name]
        id_column = output_tables[0][OperatorConstants.Columns.ID]
        name_column = output_tables[0][OperatorConstants.Columns.NAME]

        for idx in range(output_tables[0].num_rows):
            error = error_column[idx].as_py()
            if error:
                self.record_failed_document(
                    metadata=metadata,
                    doc_id=str(id_column[idx].as_py()),
                    doc_name=str(name_column[idx].as_py()),
                    reason=f"ML Enrichment error: {error}",
                )
                metadata[Metrics.External.NODE_STATUS] = ExecutionStatus.COMPLETED_WITH_ERRORS.value

    def _build_enrichment_metadata(
        self,
        *,
        output_tables: list[pa.Table],
        input_table: pa.Table,
        total_docs: int,
        metadata: dict[str, Any],
    ) -> None:
        """Populate counts and enrichment-specific keys on *metadata*."""
        metadata[Metrics.External.PROCESSED_DOCS] = total_docs - metadata[Metrics.External.FAILED_DOCS_COUNT]
        metadata[Metrics.External.PROCESSED_ROWS] = output_tables[0].num_rows if output_tables else 0

        new_columns = (
            [col for col in output_tables[0].column_names if col not in input_table.column_names]
            if output_tables
            else []
        )
        metadata[FEATURES_ADDED_KEY] = len(new_columns)
        metadata[ENRICHMENT_COLUMNS_KEY] = new_columns

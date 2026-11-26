from typing import Any

import pyarrow as pa

from docpipe.core.adapters.llm_adapter_factory import LLMAdapterFactory
from docpipe.core.constants.constants import AttributeDataTypes, DocpipeConstants, Metrics
from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.core.operators.abstract_operator import AbstractOperator, OperatorCategory
from docpipe.core.operators.functional.summarization_service import SummarizationService
from docpipe.core.operators.operator_utils import OperatorUtils
from docpipe.exceptions.docpipe_exceptions import DocpipeException
from docpipe.utils.infrastructure.logging import get_logger

logger = get_logger()

PROVIDER_KEY = OperatorConstants.Config.PROVIDER
MAX_INPUT_TOKENS_KEY = "max_input_tokens"
OVERLAP_RATIO_KEY = "overlap_ratio"
SUMMARY_SENTENCES_KEY = "summary_sentences"
SUMMARY_MAX_WORDS_KEY = "summary_max_words"

MAX_INPUT_TOKENS_DEFAULT = 4096
OVERLAP_RATIO_DEFAULT = 0.1
SUMMARY_SENTENCES_DEFAULT = 3
SUMMARY_MAX_WORDS_DEFAULT = 50


class SummarizationOperator(AbstractOperator):
    """Standalone document summarization operator."""

    short_name: str = OperatorConstants.Operators.SUMMARIZATION
    category: OperatorCategory = OperatorCategory.Functional
    owner = DocpipeConstants.OWNER_DOCPIPE

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self.output_column = config.get(OperatorConstants.Columns.OUTPUT_COLUMN, OperatorConstants.Columns.SUMMARY)
        self.provider = config.get(PROVIDER_KEY)
        self.provider_config = config.get(OperatorConstants.Config.PROVIDER_CONFIG)
        self.max_input_tokens = config.get(MAX_INPUT_TOKENS_KEY, MAX_INPUT_TOKENS_DEFAULT)
        self.overlap_ratio = config.get(OVERLAP_RATIO_KEY, OVERLAP_RATIO_DEFAULT)
        self.summary_sentences = config.get(SUMMARY_SENTENCES_KEY, SUMMARY_SENTENCES_DEFAULT)
        self.summary_max_words = config.get(SUMMARY_MAX_WORDS_KEY, SUMMARY_MAX_WORDS_DEFAULT)
        self._validate_required_configuration()

        model_id = self.provider_config[OperatorConstants.Config.MODEL_ID]
        try:
            llm_adapter = LLMAdapterFactory.create_inference_adapter(
                provider=self.provider,
                model_id=model_id,
                provider_config=self.provider_config,
            )
            self.summarization_service = SummarizationService(
                llm_adapter=llm_adapter,
                max_input_tokens=self.max_input_tokens,
                overlap_ratio=self.overlap_ratio,
                summary_sentences=self.summary_sentences,
                summary_max_words=self.summary_max_words,
            )
        except DocpipeException:
            raise
        except Exception as exc:
            raise DocpipeException(f"Failed to initialize summarization adapter '{self.provider}': {exc!s}") from exc

    @staticmethod
    def get_metadata() -> dict[str, Any]:
        return {
            OperatorConstants.Misc.SHORT_NAME: SummarizationOperator.short_name,
            DocpipeConstants.OWNER_ATTRIBUTE: SummarizationOperator.owner,
            OperatorConstants.Misc.SDK: True,
            OperatorConstants.Misc.IS_OPERATOR_AVAILABLE: True,
            OperatorConstants.Misc.CATEGORY: SummarizationOperator.category.value,
            OperatorConstants.Misc.LABEL: "Document Summarization",
            OperatorConstants.Config.DESCRIPTION: "Generates summaries for document content",
            OperatorConstants.Config.ATTRIBUTES: {
                OperatorConstants.Columns.DOC_COLUMN: {
                    OperatorConstants.Misc.TYPE: AttributeDataTypes.STRING,
                    OperatorConstants.Config.DEFAULT: OperatorConstants.Columns.DOC_COLUMN_DEFAULT,
                },
                OperatorConstants.Columns.OUTPUT_COLUMN: {
                    OperatorConstants.Misc.TYPE: AttributeDataTypes.STRING,
                    OperatorConstants.Config.DEFAULT: OperatorConstants.Columns.SUMMARY,
                },
                PROVIDER_KEY: {
                    OperatorConstants.Misc.TYPE: AttributeDataTypes.STRING,
                    OperatorConstants.Config.REQUIRED: True,
                },
                OperatorConstants.Config.PROVIDER_CONFIG: {
                    OperatorConstants.Misc.TYPE: AttributeDataTypes.JSON,
                    OperatorConstants.Config.REQUIRED: True,
                },
                MAX_INPUT_TOKENS_KEY: {
                    OperatorConstants.Misc.TYPE: AttributeDataTypes.INTEGER,
                    OperatorConstants.Config.DEFAULT: MAX_INPUT_TOKENS_DEFAULT,
                },
                OVERLAP_RATIO_KEY: {
                    OperatorConstants.Misc.TYPE: AttributeDataTypes.DOUBLE,
                    OperatorConstants.Config.DEFAULT: OVERLAP_RATIO_DEFAULT,
                },
                SUMMARY_SENTENCES_KEY: {
                    OperatorConstants.Misc.TYPE: AttributeDataTypes.INTEGER,
                    OperatorConstants.Config.DEFAULT: SUMMARY_SENTENCES_DEFAULT,
                },
                SUMMARY_MAX_WORDS_KEY: {
                    OperatorConstants.Misc.TYPE: AttributeDataTypes.INTEGER,
                    OperatorConstants.Config.DEFAULT: SUMMARY_MAX_WORDS_DEFAULT,
                },
            },
            OperatorConstants.Config.OUTPUT_FEATURES: [OperatorConstants.Columns.SUMMARY],
        }

    def _validate_required_configuration(self) -> None:
        if not isinstance(self.provider, str) or not self.provider:
            raise DocpipeException("provider is required for summarization")
        if not isinstance(self.provider_config, dict) or not self.provider_config:
            raise DocpipeException("provider_config is required for summarization")
        if not isinstance(self.doc_column, str) or not self.doc_column:
            raise DocpipeException("doc_column must be a non-empty string")
        if not isinstance(self.output_column, str) or not self.output_column:
            raise DocpipeException("output_column must be a non-empty string")
        model_id = self.provider_config.get(OperatorConstants.Config.MODEL_ID)
        if not isinstance(model_id, str) or not model_id:
            raise DocpipeException("provider_config.model_id is required for summarization")
        if not isinstance(self.max_input_tokens, int) or self.max_input_tokens <= 0:
            raise DocpipeException("max_input_tokens must be a positive integer")
        if not isinstance(self.overlap_ratio, (int, float)) or not 0 <= self.overlap_ratio <= 0.5:
            raise DocpipeException("overlap_ratio must be between 0 and 0.5")
        if not isinstance(self.summary_sentences, int) or self.summary_sentences <= 0:
            raise DocpipeException("summary_sentences must be a positive integer")
        if not isinstance(self.summary_max_words, int) or self.summary_max_words <= 0:
            raise DocpipeException("summary_max_words must be a positive integer")

    @staticmethod
    def get_required_features() -> list[str]:
        return [OperatorConstants.Columns.DOC_COLUMN_DEFAULT]

    @staticmethod
    def get_static_required_features() -> list[str]:
        return [OperatorConstants.Columns.DOC_COLUMN_DEFAULT]

    def validate(self, errors: list[str], warnings: list[str], available_features: list[str]) -> None:
        OperatorUtils.validate_columns(available_features, [self.doc_column], self.short_name, errors)
        attributes = self.get_metadata().get(OperatorConstants.Config.ATTRIBUTES, {})
        from docpipe.utils.operators.config_validation import validate_config_from_metadata

        validate_config_from_metadata(config=self.config, attributes=attributes, errors=errors)

    def transform(self, table: pa.Table) -> tuple[list[pa.Table], dict[str, Any]]:
        total_docs = OperatorUtils.find_doc_count(table=table)
        metadata = self.create_base_metadata(total_docs_count=total_docs)
        if self.doc_column not in table.column_names:
            raise DocpipeException(f"Required column '{self.doc_column}' not found for summarization")

        summaries: list[str | None] = []
        for index, content in enumerate(table[self.doc_column].to_pylist()):
            doc_id = str(table["id"][index].as_py()) if "id" in table.column_names else str(index)
            doc_name = str(table["name"][index].as_py()) if "name" in table.column_names else doc_id
            if content is None or not str(content).strip():
                summaries.append(None)
                self.record_skipped_document(
                    metadata=metadata,
                    doc_id=doc_id,
                    doc_name=doc_name,
                    reason="Empty content",
                )
                continue
            try:
                summaries.append(self.summarization_service.generate_summary(content=str(content)))
                metadata[Metrics.External.PROCESSED_DOCS] += 1
            except Exception as exc:
                summaries.append(None)
                self.record_failed_document(
                    metadata=metadata,
                    doc_id=doc_id,
                    doc_name=doc_name,
                    reason="Summarization failed",
                )
                logger.warning(
                    "Summarization failed for document %s: %s",
                    doc_id,
                    type(exc).__name__,
                )

        summary_array = pa.array(summaries, type=pa.string())
        if self.output_column in table.column_names:
            output_table = table.set_column(
                table.column_names.index(self.output_column),
                self.output_column,
                summary_array,
            )
        else:
            output_table = table.append_column(self.output_column, summary_array)
        metadata[Metrics.External.NODE_STATUS] = OperatorUtils.determine_execution_status(
            processed_count=metadata[Metrics.External.PROCESSED_DOCS],
            failed_count=metadata[Metrics.External.FAILED_DOCS_COUNT],
            skipped_count=metadata[Metrics.External.SKIPPED_DOCS_COUNT],
        )
        return [output_table], metadata

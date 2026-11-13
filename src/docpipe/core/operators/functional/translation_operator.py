"""Translate document text using a configured LLM provider."""

from typing import Any

import pyarrow as pa

from docpipe.core.adapters.llm_adapter_factory import LLMAdapterFactory
from docpipe.core.constants.constants import (
    AttributeDataTypes,
    DocpipeConstants,
    Metrics,
)
from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.core.operators.abstract_operator import (
    AbstractOperator,
    OperatorCategory,
)
from docpipe.core.operators.functional.translation_service import TranslationService
from docpipe.utils.infrastructure.logging import get_logger

logger = get_logger()


class TranslationOperator(AbstractOperator):
    """Translate a document text column while preserving the input table."""

    short_name = "translation"
    category = OperatorCategory.Functional
    owner = DocpipeConstants.OWNER_DOCPIPE

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)

        self.output_column = config.get(
            "output_column", OperatorConstants.Columns.TRANSLATED_CONTENT
        )
        self.source_language = config.get("source_language", "auto")
        self.target_language = config.get("target_language")
        self.preserve_markdown = config.get("preserve_markdown", True)
        self.max_input_tokens = config.get("max_input_tokens", 4096)
        self.provider = config.get("provider")
        self.provider_config = config.get("provider_config")

        if not isinstance(self.target_language, str) or not self.target_language.strip():
            raise ValueError("A non-empty target_language is required")

        if self.provider not in {"litellm", "watsonx"}:
            raise ValueError("provider must be 'litellm' or 'watsonx'")

        if not isinstance(self.provider_config, dict):
            raise ValueError("provider_config must be a dictionary")

        model_id = self.provider_config.get("model_id")
        if not isinstance(model_id, str) or not model_id.strip():
            raise ValueError("provider_config.model_id is required")

        if (
            not isinstance(self.max_input_tokens, int)
            or isinstance(self.max_input_tokens, bool)
            or self.max_input_tokens < 1
        ):
            raise ValueError("max_input_tokens must be a positive integer")

        if not isinstance(self.source_language, str) or not self.source_language.strip():
            raise ValueError("source_language must be a non-empty string")

        if not isinstance(self.output_column, str) or not self.output_column.strip():
            raise ValueError("output_column must be a non-empty string")

        if self.output_column == self.doc_column:
            raise ValueError("output_column must differ from doc_column")

        if self.output_column in {
            OperatorConstants.Columns.TRANSLATION_SOURCE_LANGUAGE,
            OperatorConstants.Columns.TRANSLATION_TARGET_LANGUAGE,
        }:
            raise ValueError(
                "output_column cannot conflict with translation language metadata columns"
            )

        if not isinstance(self.preserve_markdown, bool):
            raise ValueError("preserve_markdown must be a boolean")

        adapter = LLMAdapterFactory.create_inference_adapter(
            provider=self.provider,
            model_id=model_id,
            provider_config=self.provider_config,
        )

        self.translation_service = TranslationService(
            llm_adapter=adapter,
            source_language=self.source_language,
            target_language=self.target_language,
            preserve_markdown=self.preserve_markdown,
            max_input_tokens=self.max_input_tokens,
        )

    @staticmethod
    def get_metadata() -> dict[str, Any]:
        """Return operator metadata for UI and flow validation."""
        return {
            OperatorConstants.Misc.SDK: True,
            OperatorConstants.Misc.CATEGORY: OperatorCategory.Functional.value,
            OperatorConstants.Misc.IS_OPERATOR_AVAILABLE: TranslationOperator.is_available(),
            OperatorConstants.Misc.LABEL: "Translation",
            OperatorConstants.Config.DESCRIPTION: (
                "Translate document text using litellm or watsonx."
            ),
            OperatorConstants.Config.FEATURES: {
                "translated_content": {
                    OperatorConstants.Misc.NAME: "Translated Content",
                    OperatorConstants.Config.DESCRIPTION: (
                        "Text translated into the configured target language."
                    ),
                    OperatorConstants.Misc.TYPE: OperatorConstants.Types.TYPE_TEXT,
            },
                "translation_source_language": {
                    OperatorConstants.Misc.NAME: "Translation Source Language",
                    OperatorConstants.Config.DESCRIPTION: (
                        "Configured source language, including auto when language detection is requested."
                    ),
                    OperatorConstants.Misc.TYPE: OperatorConstants.Types.TYPE_STRING,
            },
                "translation_target_language": {
                    OperatorConstants.Misc.NAME: "Translation Target Language",
                    OperatorConstants.Config.DESCRIPTION: (
                        "Configured target language for the translation."
                    ),
                    OperatorConstants.Misc.TYPE: OperatorConstants.Types.TYPE_STRING,
           },
       },
            OperatorConstants.Config.ATTRIBUTES: {
                "doc_column": {
                    OperatorConstants.Misc.NAME: "Input Column",
                    OperatorConstants.Config.DESCRIPTION: (
                        "Column containing text to translate."
                    ),
                    OperatorConstants.Config.REQUIRED: False,
                    OperatorConstants.Config.DEFAULT: "content",
                    OperatorConstants.Misc.TYPE: AttributeDataTypes.STRING,
                },
                "output_column": {
                    OperatorConstants.Misc.NAME: "Output Column",
                    OperatorConstants.Config.DESCRIPTION: (
                        "Column receiving translated text."
                    ),
                    OperatorConstants.Config.REQUIRED: False,
                    OperatorConstants.Config.DEFAULT: "translated_content",
                    OperatorConstants.Misc.TYPE: AttributeDataTypes.STRING,
                },
                "source_language": {
                    OperatorConstants.Misc.NAME: "Source Language",
                    OperatorConstants.Config.DESCRIPTION: (
                        "Source language code, or auto to let the model infer it."
                    ),
                    OperatorConstants.Config.REQUIRED: False,
                    OperatorConstants.Config.DEFAULT: "auto",
                    OperatorConstants.Misc.TYPE: AttributeDataTypes.STRING,
                },
                "target_language": {
                    OperatorConstants.Misc.NAME: "Target Language",
                    OperatorConstants.Config.DESCRIPTION: (
                        "Language to translate into."
                    ),
                    OperatorConstants.Config.REQUIRED: True,
                    OperatorConstants.Misc.TYPE: AttributeDataTypes.STRING,
                },
                "preserve_markdown": {
                    OperatorConstants.Misc.NAME: "Preserve Markdown",
                    OperatorConstants.Config.DESCRIPTION: (
                        "Ask the model to preserve Markdown formatting."
                    ),
                    OperatorConstants.Config.REQUIRED: False,
                    OperatorConstants.Config.DEFAULT: True,
                    OperatorConstants.Misc.TYPE: AttributeDataTypes.BOOLEAN,
                },
                "max_input_tokens": {
                    OperatorConstants.Misc.NAME: "Maximum Input Tokens",
                    OperatorConstants.Config.DESCRIPTION: (
                        "Approximate maximum input size used to estimate chunk length."
                    ),
                    OperatorConstants.Config.REQUIRED: False,
                    OperatorConstants.Config.DEFAULT: 4096,
                    OperatorConstants.Misc.TYPE: AttributeDataTypes.INTEGER,
                },
                "provider": {
                    OperatorConstants.Misc.NAME: "Provider",
                    OperatorConstants.Config.DESCRIPTION: "Inference provider.",
                    OperatorConstants.Config.REQUIRED: True,
                    OperatorConstants.Config.VALID_VALUES: ["litellm", "watsonx"],
                    OperatorConstants.Misc.TYPE: AttributeDataTypes.STRING,
                },
                "provider_config": {
                    OperatorConstants.Misc.NAME: "Provider Configuration",
                    OperatorConstants.Config.DESCRIPTION: (
                        "Provider settings, including model_id and credentials."
                    ),
                    OperatorConstants.Config.REQUIRED: True,
                    OperatorConstants.Misc.TYPE: AttributeDataTypes.JSON,
                },
            },
        }

    @staticmethod
    def get_required_features() -> list[str]:
        """Return required upstream table features."""
        return []

    def validate(
        self,
        errors: list[str],
        warnings: list[str],
        available_features: list[str],
    ) -> None:
        """Validate translation configuration and upstream features."""
        super().validate(errors, warnings, available_features)

        from docpipe.utils.operators.config_validation import (
            validate_config_from_metadata,
        )

        attributes = self.get_metadata().get(
            OperatorConstants.Config.ATTRIBUTES, {}
        )
        validate_config_from_metadata(
            config=self.config,
            attributes=attributes,
            errors=errors,
        )

    def transform(self, table: pa.Table) -> tuple[list[pa.Table], dict[str, Any]]:
        """Translate rows independently and preserve all original columns."""
        metadata = self.create_base_metadata(total_docs_count=len(table))

        if self.doc_column not in table.column_names:
            raise ValueError("Input table is missing column '%s'" % self.doc_column)

        protected_columns = {
            self.output_column,
            OperatorConstants.Columns.TRANSLATION_SOURCE_LANGUAGE,
            OperatorConstants.Columns.TRANSLATION_TARGET_LANGUAGE,
        }
        conflicts = protected_columns.intersection(table.column_names)
        if conflicts:
            raise ValueError(
                "Translation output columns already exist: %s"
                % ", ".join(sorted(conflicts))
            )

        input_values = table[self.doc_column].to_pylist()
        doc_ids = (
            table["doc_id"].to_pylist()
            if "doc_id" in table.column_names
            else []
        )
        doc_names = (
            table["doc_name"].to_pylist()
            if "doc_name" in table.column_names
            else []
        )

        translated_values: list[str | None] = []
        source_languages: list[str | None] = []
        target_languages: list[str | None] = []

        for index, value in enumerate(input_values):
            doc_id = str(doc_ids[index]) if doc_ids else str(index)
            doc_name = str(doc_names[index]) if doc_names else doc_id

            if value is None or not isinstance(value, str) or not value.strip():
                translated_values.append(None)
                source_languages.append(self.source_language)
                target_languages.append(self.target_language)
                self.record_skipped_document(
                    metadata=metadata,
                    doc_id=doc_id,
                    doc_name=doc_name,
                    reason="Input text is empty",
                )
                continue

            try:
                translated = self.translation_service.translate(content=value)
                translated_values.append(translated)
                source_languages.append(self.source_language)
                target_languages.append(self.target_language)
                metadata[Metrics.External.PROCESSED_DOCS] += 1
            except Exception as exc:
                logger.warning(
                    "Translation failed for document %s: %s",
                    doc_id,
                    type(exc).__name__,
                )
                translated_values.append(None)
                source_languages.append(self.source_language)
                target_languages.append(self.target_language)
                self.record_failed_document(
                    metadata=metadata,
                    doc_id=doc_id,
                    doc_name=doc_name,
                    reason="Translation failed: %s" % type(exc).__name__,
                )

        result = table
        new_columns = (
            (self.output_column, translated_values),
            (OperatorConstants.Columns.TRANSLATION_SOURCE_LANGUAGE, source_languages),
            (OperatorConstants.Columns.TRANSLATION_TARGET_LANGUAGE, target_languages),
        )

        for name, values in new_columns:
            array = pa.array(values, type=pa.string())
            if name in result.column_names:
                result = result.set_column(
                    result.column_names.index(name),
                    name,
                    array,
                )
            else:
                result = result.append_column(name, array)

        return [result], metadata

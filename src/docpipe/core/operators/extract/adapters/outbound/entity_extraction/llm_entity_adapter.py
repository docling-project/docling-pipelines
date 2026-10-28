"""Unified LLM entity extraction adapter using shared infrastructure.

This adapter implements entity extraction using the shared LLM infrastructure,
supporting both watsonx and litellm providers through a unified interface.
Provider-specific subclasses (LiteLLMEntityAdapter, WatsonxEntityAdapter) self-register
with EntityExtractionAdapterFactory. This class is the shared base and is not
registered directly.
"""

import json
from typing import Any

import pyarrow as pa
from pydantic import BaseModel

from docpipe.core.adapters.llm_adapter_factory import LLMAdapterFactory
from docpipe.core.constants import OperatorConstants
from docpipe.core.operators.extract.ports.outbound.entity_extraction import EntityExtractionPort
from docpipe.core.operators.extract.services.entity_extraction_service import EntityExtractionService
from docpipe.core.ports.llm_inference_port import LLMInferencePort
from docpipe.utils.document_class_utils import DocumentClassUtils
from docpipe.utils.infrastructure.logging import get_logger
from docpipe.utils.llm import parse_llm_json_response

logger = get_logger(__name__)


class LLMEntityAdapter(EntityExtractionPort):
    """Unified LLM-based entity extraction adapter (shared base).

    This adapter uses the shared LLM infrastructure to extract structured entities
    from document text across multiple LLM providers (watsonx, litellm). It supports
    both schema-based extraction (with a predefined schema) and schema-free
    extraction (discovering entities automatically).

    This class is the shared implementation base. Provider-specific subclasses
    (LiteLLMEntityAdapter, WatsonxEntityAdapter) hold ADAPTER_NAME and register
    themselves with the factory.

    Attributes:
        provider_name: LLM provider name (watsonx or litellm)
        model_name: LLM model identifier
        temperature: LLM sampling temperature (0.0 = deterministic)
        max_tokens: Maximum tokens for LLM response
        max_doc_chars: Maximum document characters to send to LLM
        llm_adapter: LLMInferencePort instance for LLM communication
    """

    def __init__(self, *, config: dict[str, Any]) -> None:
        """Initialize the adapter with configuration.

        Args:
            config: Configuration dictionary
        """
        super().__init__(config=config)

    def validate(self, *, config: dict[str, Any]) -> None:
        """Validate LLM-specific configuration.

        Args:
            config: Configuration dictionary to validate

        Raises:
            ValueError: If required configuration is missing or invalid
        """
        # Validate provider
        provider = config.get(OperatorConstants.Config.PROVIDER)
        if not isinstance(provider, str) or not provider.strip():
            raise ValueError("'provider' is required for LLM entity extraction")

        provider = provider.lower()

        # Reject direct ollama provider
        if provider == "ollama":
            raise ValueError(
                "Direct 'ollama' provider is deprecated for entity extraction. "
                "Use 'litellm' provider with model_id format 'openai/<model_name>' "
                "and configure api_base='http://localhost:11434/v1' in entity_provider_config. "
                "Example: provider='litellm', entity_model_id='openai/granite4:latest'"
            )

        # Validate provider is supported
        supported_providers = LLMAdapterFactory.get_supported_providers(capability="inference")
        if provider not in supported_providers:
            raise ValueError(
                f"Unsupported provider '{provider}' for entity extraction. Supported providers: {supported_providers}"
            )

        # Validate model_name
        model_name = config.get(OperatorConstants.Config.MODEL_NAME)
        if not isinstance(model_name, str) or not model_name.strip():
            raise ValueError(f"'{OperatorConstants.Config.MODEL_NAME}' is required for LLM entity extraction")

        # Validate numeric parameters if present
        for param in [
            OperatorConstants.LLM.TEMPERATURE,
            OperatorConstants.LLM.MAX_TOKENS,
            OperatorConstants.LLM.MAX_DOC_CHARS,
        ]:
            value = config.get(param)
            if value is not None and not isinstance(value, (int, float)):
                raise ValueError(f"LLMEntityAdapter '{param}' must be a number")

        super().validate(config=config)

    def _init_adapter_config(self, *, config: dict[str, Any]) -> None:
        """Initialize LLM-specific configuration.

        Args:
            config: Configuration dictionary containing:
                - provider: LLM provider (watsonx or litellm)
                - model_name: LLM model identifier
                - temperature: Sampling temperature (default: 0.0)
                - max_tokens: Maximum response tokens (default: 2000)
                - max_doc_chars: Maximum document characters (default: 8000)
                - entity_provider_config: Provider-specific configuration
        """
        self.provider: str = str(config.get(OperatorConstants.Config.PROVIDER)).lower()
        self.model_name: str = str(config.get(OperatorConstants.Config.MODEL_NAME))

        # Handle None values for numeric parameters
        temperature = config.get(OperatorConstants.LLM.TEMPERATURE, 0.0)
        self.temperature = float(temperature) if temperature is not None else 0.0

        max_tokens = config.get(OperatorConstants.LLM.MAX_TOKENS, 2000)
        self.max_tokens = int(max_tokens) if max_tokens is not None else 2000

        max_doc_chars = config.get(OperatorConstants.LLM.MAX_DOC_CHARS, 8000)
        self.max_doc_chars = int(max_doc_chars) if max_doc_chars is not None else 8000

        # Get provider-specific configuration
        provider_config = config.get("entity_provider_config", {})

        # Create LLM adapter using shared infrastructure
        self.llm_adapter: LLMInferencePort = LLMAdapterFactory.create_inference_adapter(
            provider=self.provider,
            model_id=self.model_name,
            provider_config=provider_config,
        )

        # Validate adapter configuration
        self._validate_adapter()

        logger.info(
            "Initialized LLMEntityAdapter with provider=%s, model=%s, temperature=%s, max_tokens=%s",
            self.provider,
            self.model_name,
            self.temperature,
            self.max_tokens,
        )

    @classmethod
    def build_provider_config(cls, *, entity_extraction_config: dict[str, Any], doc_column: str) -> dict[str, Any]:
        """Build LLM provider config from the entity_extraction config block.

        Uses ``cls.ADAPTER_NAME`` as the provider identifier so subclasses
        (LiteLLMEntityAdapter, WatsonxEntityAdapter) inherit the correct value
        without needing to override this method.

        Args:
            entity_extraction_config: Nested entity_extraction configuration dictionary
            doc_column: Document column name from text_extraction config

        Returns:
            Adapter-specific configuration dictionary
        """
        from docpipe.core.operators.extract.adapters.outbound.factories.entity_extraction_adapter_factory import (
            EntityExtractionAdapterFactory,
        )

        provider_config = entity_extraction_config.get(OperatorConstants.Config.PROVIDER_CONFIG, {})
        base = EntityExtractionAdapterFactory.build_common_config(
            entity_extraction_config=entity_extraction_config, doc_column=doc_column
        )
        base.update(
            {
                OperatorConstants.Config.PROVIDER: cls.ADAPTER_NAME,
                OperatorConstants.Config.MODEL_NAME: provider_config.get(OperatorConstants.Config.MODEL_ID),
                OperatorConstants.LLM.TEMPERATURE: provider_config.get(OperatorConstants.LLM.TEMPERATURE, 0.0),
                OperatorConstants.LLM.MAX_TOKENS: provider_config.get("max_tokens", 4096),
                OperatorConstants.LLM.MAX_DOC_CHARS: entity_extraction_config.get("max_doc_chars", 8000),
                "entity_provider_config": provider_config,
            }
        )
        return base

    @staticmethod
    def get_config_schema() -> type[BaseModel]:
        """Return the Pydantic config model class for this adapter."""
        from docpipe.core.operators.extract.adapters.outbound.entity_extraction.llm_entity_config import LLMEntityConfig

        return LLMEntityConfig

    def _validate_adapter(self) -> None:
        """Validate LLM adapter configuration on initialization.

        Raises:
            DocpipeException: If adapter validation fails
        """
        from docpipe.exceptions.docpipe_exceptions import DocpipeException

        result = self.llm_adapter.validate()

        # Log warnings
        if result.get("warnings"):
            for warning in result["warnings"]:
                logger.warning("LLM adapter validation warning: %s", warning)

        # Raise error if validation failed
        if not result.get("valid", True):
            errors = result.get("errors", ["Unknown validation error"])
            raise DocpipeException(
                message=f"LLM adapter validation failed: {'; '.join(errors)}",
                status_code=400,
            )

    def transform(self, *, table: pa.Table, metadata: dict[str, Any]) -> tuple[list[pa.Table], dict[str, Any]]:
        """Transform documents by extracting entities using LLM.

        This method delegates orchestration to EntityExtractionService while
        maintaining backward compatibility with the adapter interface.

        Args:
            table: PyArrow table with document information containing columns:
                - id: Document ID
                - name: Document name/filename
                - doc_content: Document text content
                - document_type: Document type for schema selection (optional)
            metadata: Metadata dictionary to update

        Returns:
            Tuple of (list of transformed tables, metadata dictionary)
        """
        # Create service instance with adapter and configuration
        service = EntityExtractionService(
            adapter=self,
            config={
                OperatorConstants.Columns.DOC_COLUMN: self.doc_column,
                OperatorConstants.Columns.OUTPUT_COLUMN: self.output_column,
                OperatorConstants.Config.EXPAND_EXTRACTED_DATA: self.expand_extracted_data,
                OperatorConstants.Columns.DOC_ID_HASH: self.doc_id_hash_column,
                OperatorConstants.Config.CUSTOM_SCHEMA: self.custom_schema,
                "common_log_arguments": self.common_log_arguments,
            },
            max_workers=self.max_workers,
            job_run_id=self.job_run_id,
            node_id=self.node_id,
            node_name=self.node_name,
            batch_id=self.batch_id,
        )

        # Delegate to service for orchestration
        return service.transform(table=table, metadata=metadata)

    # ========================================================================
    # LLM-Based Entity Extraction Helper Methods
    # ========================================================================
    # These methods provide common utilities for LLM-based entity extraction
    # adapters (Ollama, LiteLLM, etc.). They handle prompt building, schema
    # processing, and JSON parsing with repair logic.
    # ========================================================================

    def _build_schema_prompt(self, *, content: str, schema: dict[str, Any]) -> str:
        """Build prompt for schema-based extraction.
        Args:
            content: Document text content
            schema: Schema dictionary with fields/columns
        Returns:
            Formatted user prompt string
        """
        schema_name = schema.get("document_type", "") or schema.get("table", "") or "document"
        json_template = self._build_json_template(schema=schema)

        # Build per-field extraction hints from extraction_instructions (if present)
        hints = self._build_extraction_hints(schema=schema)
        hints_section = f"\nField extraction notes:\n{hints}\n" if hints else ""

        return (
            f"You are extracting structured data from a {schema_name} document.\n\n"
            f"DOCUMENT TEXT:\n"
            f"{content}\n\n"
            f"---\n\n"
            f"TASK:\n"
            f"Read the document above and fill in every field of the JSON template below.\n"
            f"Rules:\n"
            f"  1. Return ONLY the completed JSON object — no explanation, no markdown fences.\n"
            f"  2. Replace each null with the value found in the document.\n"
            f"  3. If a value is not present in the document, keep it as null.\n"
            f"  4. Match the template structure EXACTLY — do NOT add, rename, remove, or nest keys beyond what the template defines.\n"
            f"  5. Use key names EXACTLY as written in the template — do NOT copy key names from the document text.\n"
            f"  6. The value type must match the template: if the template has null (a scalar), return a string or number — never an object or array.\n"
            f"  7. If the template has a list, return a list with one object per item found; use null for missing sub-fields within each object.\n"
            f"  8. Preserve values exactly as they appear in the document (dates, amounts, names, identifiers).\n"
            f"  9. Each field name describes its exact meaning — read the field name carefully and extract only the value that matches it.\n"
            f"{hints_section}\n"
            f"JSON TEMPLATE (fill in the nulls):\n"
            f"{json.dumps(json_template, indent=2)}"
        )

    def _build_extraction_hints(self, *, schema: dict[str, Any]) -> str:
        """Build per-field extraction hints from extraction_instructions in the schema.

        Args:
            schema: Schema dictionary
        Returns:
            Formatted hints string, empty string if no instructions exist
        """
        fields = schema.get("fields", [])
        if not fields:
            return ""

        lines: list[str] = []
        for field in fields:
            instruction = field.get("extraction_instructions", "").strip()
            if instruction:
                lines.append(f"  - {field.get('name', '')}: {instruction}")
            # Recurse into nested fields
            for nested in field.get("fields", []):
                nested_instruction = nested.get("extraction_instructions", "").strip()
                if nested_instruction:
                    lines.append(f"  - {nested.get('name', '')}: {nested_instruction}")

        return "\n".join(lines)

    def _build_json_template(self, *, schema: dict[str, Any]) -> dict[str, Any]:
        """Build JSON template from schema.

        Supports three schema formats:
          1. fields format  : {"fields": [{"name": ..., "type": ...}, ...]}
          2. columns format : {"columns": {"field_name": "type", ...}}
          3. flat format    : {"field_name": "type", ...}  (custom_schema from flow config)

        Args:
            schema: Schema dictionary
        Returns:
            JSON template dictionary with null placeholders (or option hints)
        """
        # Format 1: new 'fields' list format
        if "fields" in schema:
            return DocumentClassUtils.build_json_template_from_fields(schema["fields"])

        # Format 2: explicit 'columns' dict
        columns = schema.get("columns", {})
        if columns:
            return self._template_from_columns(columns)

        # Format 3: flat {field_name: type_str} — custom_schema from flow config
        # Detect by checking that all values are strings (type hints) and none are
        # reserved schema meta-keys.
        _meta_keys = {"document_type", "document_description", "table", "description"}
        flat_fields = {k: v for k, v in schema.items() if k not in _meta_keys and isinstance(v, str)}
        if flat_fields:
            return self._template_from_columns(flat_fields)

        return {}

    def _template_from_columns(self, columns: dict[str, Any]) -> dict[str, Any]:
        """Build a null-placeholder template from a flat {col_name: type} dict.

        Supports dot-notation keys for nested structures (e.g. 'address.street').

        Args:
            columns: Dict mapping column names to type strings
        Returns:
            Nested template dict with None placeholders
        """
        template: dict[str, Any] = {}
        for col_name in columns.keys():
            if "." in col_name:
                parts = col_name.split(".")
                current = template
                for part in parts[:-1]:
                    if part not in current:
                        current[part] = {}
                    current = current[part]
                current[parts[-1]] = None
            else:
                template[col_name] = None
        return template

    def _build_schema_free_prompt(self, *, content: str) -> str:
        """Build prompt for schema-free extraction.
        Args:
            content: Document text content
        Returns:
            Formatted user prompt string
        """
        return (
            f"DOCUMENT TEXT:\n"
            f"{content}\n\n"
            f"---\n\n"
            f"TASK:\n"
            f"Extract all named entities and key structured information from the document above.\n"
            f"Return ONLY a valid JSON object — no explanation, no markdown fences.\n"
            f"Use descriptive snake_case keys (e.g. invoice_number, vendor_name, total_amount).\n"
            f"Group related fields under nested objects where appropriate (e.g. vendor, customer, line_items).\n"
            f"Set any field to null if the value cannot be determined."
        )

    def extract_entities_single(
        self, *, doc_id: str, doc_name: str, content: str | bytes, schema: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Extract entities from a single document using LLM.

        Args:
            doc_id: Document identifier
            doc_name: Document name
            content: Document content (text or bytes)
            schema: Optional schema dictionary for structured extraction

        Returns:
            Dictionary with extraction results:
            {
                "success": bool,              # Extraction success indicator
                "entities": dict,             # Extracted entities as dictionary
                "error": str | None           # Error message if failed
            }
        """
        # Convert bytes to string if needed
        if isinstance(content, bytes):
            content = content.decode("utf-8", errors="ignore")

        # Truncate content if too long
        if len(content) > self.max_doc_chars:
            logger.warning(
                "Document %s content truncated from %d to %d characters",
                doc_id,
                len(content),
                self.max_doc_chars,
            )
            content = content[: self.max_doc_chars]

        # non-empty schema (covers fields, columns, and flat custom_schema formats).
        if schema:
            system_prompt = OperatorConstants.ExtractionModes.ENTITY_EXTRACTION_SYSTEM_PROMPT
            user_prompt = self._build_schema_prompt(content=content, schema=schema)
        else:
            # Schema-free extraction
            system_prompt = OperatorConstants.ExtractionModes.ENTITY_EXTRACTION_SCHEMA_FREE_SYSTEM_PROMPT
            user_prompt = self._build_schema_free_prompt(content=content)

        # Call LLM using chat interface for better provider compatibility
        try:
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ]

            response = self.llm_adapter.chat(
                messages=messages,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
            )

            # Parse JSON response
            entities = self._parse_json_response(response)
            logger.debug("Extracted %d entities from document %s", len(entities), doc_id)

            return {
                OperatorConstants.Extraction.SUCCESS: True,
                OperatorConstants.Misc.ENTITIES: entities,
                OperatorConstants.Extraction.ERROR: None,
            }

        except Exception as e:
            error_msg = f"Error extracting entities from document {doc_id}: {e}"
            logger.error(error_msg)
            return {
                OperatorConstants.Extraction.SUCCESS: False,
                OperatorConstants.Misc.ENTITIES: {},
                OperatorConstants.Extraction.ERROR: error_msg,
            }

    def _parse_json_response(self, response: str) -> dict[str, Any]:
        """Parse JSON response from LLM, handling markdown fences and errors.

        Args:
            response: Raw LLM response string

        Returns:
            Parsed JSON dictionary, or empty dict if parsing fails
        """
        from docpipe.exceptions.docpipe_exceptions import DocpipeException

        try:
            parsed = parse_llm_json_response(
                response,
                log_on_error=True,
                log_level="warning",
            )
            return self._normalise_response(parsed)
        except DocpipeException:
            # Return empty dict on parsing failure (maintains backward compatibility)
            return {}

    def _normalise_response(self, obj: Any) -> Any:
        """Recursively normalise a parsed LLM response.

        - Strips leading/trailing whitespace from all dict keys.
        - Converts numeric leaf values (int/float) to strings so downstream
          transforms always receive string inputs.
        - Leaves None and bool values untouched.

        Args:
            obj: Parsed JSON value (dict, list, or scalar)

        Returns:
            Same structure with keys stripped and numerics stringified
        """
        if isinstance(obj, dict):
            return {k.strip(): self._normalise_response(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [self._normalise_response(item) for item in obj]
        if isinstance(obj, bool) or obj is None:
            return obj
        if isinstance(obj, (int, float)):
            return str(obj)
        return obj

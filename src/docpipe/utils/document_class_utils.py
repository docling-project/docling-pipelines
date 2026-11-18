#!/usr/bin/env python3
"""
Utility functions for working with document class definitions.
Converts document class JSON schemas to Docling extraction templates.
"""

import json
import logging
from pathlib import Path
from typing import Any, ClassVar

import re2 as re

from docpipe.core.constants.constants import DocpipeConstants
from docpipe.utils.infrastructure.logging import get_logger

logger: logging.Logger = get_logger()


class DocumentClassUtils:
    """Utilities for document class schema operations."""

    # Type mapping from target_tables column types to Docling template types
    TYPE_MAPPING: ClassVar[dict[str, str]] = {
        "string": "string",
        "date": "string",  # Extract as string, parse later
        "decimal": "float",
        "float": "float",
        "long": "int",
        "int": "int",
        "integer": "int",
        "boolean": "boolean",
        "bool": "boolean",
    }
    DOCUMENT_CLASSES_PATH = DocpipeConstants.DOCUMENT_CLASSES_PATH

    @staticmethod
    def normalize_filename(name: str) -> str:
        """Normalize document type name to filename."""
        name = name.lower()
        name = re.sub(r"[^a-z0-9]+", "_", name)
        name = re.sub(r"_+", "_", name)
        return name.strip("_")

    @staticmethod
    def load_document_class(doc_class_path: str | Path) -> dict[str, Any]:
        """
        Load document class JSON from file.

        Args:
            doc_class_path: Path to document class JSON file

        Returns:
            Document class dictionary

        Raises:
            FileNotFoundError: If file doesn't exist
            json.JSONDecodeError: If file is not valid JSON
        """
        doc_class_path = Path(doc_class_path)
        if not doc_class_path.exists():
            raise FileNotFoundError(f"Document class file not found: {doc_class_path}")

        with Path(doc_class_path).open(encoding="utf-8") as f:
            return json.load(f)

    @staticmethod
    def _check_direct_field_match(source: dict, field_path: list[str]) -> str | None:
        """Check if source has direct field reference matching field_path."""
        if "field" in source and source["field"] == field_path:
            return source.get("type")
        return None

    @staticmethod
    def _check_transform_field_match(source: dict, field_path: list[str]) -> bool:
        """Check if transform arguments contain matching field reference."""
        if "transform" not in source:
            return False

        transform = source["transform"]
        for arg in transform.get("arguments", []):
            if "value" in arg and "field" in arg["value"]:
                if arg["value"]["field"] == field_path:
                    return True
        return False

    @staticmethod
    def _get_field_type_from_target_tables(field_path: list[str], target_tables: list[dict]) -> str | None:
        """
        Get the type of a field from target_tables section.

        Args:
            field_path: Path to field (e.g., ["invoice_date"] or ["line_items", "amount"])
            target_tables: List of target table definitions

        Returns:
            Type string from target_tables or None if not found
        """
        for table in target_tables:
            for column in table.get("columns", []):
                source = column.get("source", {})

                # Handle direct field reference
                if "field" in source and source["field"] == field_path:
                    return column.get("type")

                # Handle transform with field reference
                if DocumentClassUtils._check_transform_field_match(source, field_path):
                    return column.get("type")

        return None

    @staticmethod
    def _build_template_from_fields(
        fields: list[dict], target_tables: list[dict], parent_path: list[str] | None = None
    ) -> dict[str, Any]:
        """
        Recursively build template from document fields.

        Args:
            fields: List of field definitions
            target_tables: Target tables for type lookup
            parent_path: Parent field path for nested fields

        Returns:
            Template dictionary
        """
        template: dict[str, Any] = {}
        parent_path = parent_path or []

        for field in fields:
            field_name = field.get("name")
            if not field_name:
                continue

            # Build field path
            field_path = [*parent_path, field_name]

            # Check if field has nested fields (like line_items)
            if "fields" in field:
                # For nested fields, create a nested template structure
                nested_template = DocumentClassUtils._build_template_from_fields(
                    fields=field["fields"],
                    target_tables=target_tables,
                    parent_path=field_path,
                )
                if nested_template:
                    template[field_name] = nested_template
            else:
                # Get type from target_tables
                field_type = DocumentClassUtils._get_field_type_from_target_tables(
                    field_path=field_path, target_tables=target_tables
                )

                # Map to Docling type
                if field_type:
                    docling_type = DocumentClassUtils.TYPE_MAPPING.get(field_type.lower(), "string")
                    template[field_name] = docling_type
                else:
                    # Default to string if type not found
                    logger.warning("Type not found for field %s, defaulting to string", ".".join(field_path))
                    template[field_name] = "string"

        return template

    @staticmethod
    def generate_docling_template(
        doc_class_path: str | Path,
        include_nested: bool = True,
        max_fields: int | None = None,
    ) -> dict[str, Any]:
        """
        Generate Docling extraction template from document class JSON.

        Args:
            doc_class_path: Path to document class JSON file
            include_nested: Whether to include nested fields (like line_items)
            max_fields: Maximum number of top-level fields to include (None for all)

        Returns:
            Docling template dictionary with field names and types

        Example:
            >>> template = DocumentClassUtils.generate_docling_template(
            ...     "src/docpipe_app/backend/common/document_classes/invoice.json"
            ... )
            >>> print(template)
            {
                "invoice_number": "string",
                "invoice_date": "string",
                "customer_name": "string",
                "sub_total": "float",
                "tax": "float",
                "total": "float",
                "line_items": {
                    "amount": "float",
                    "description": "string",
                    "quantity": "int"
                }
            }
        """
        # Load document class
        doc_class = DocumentClassUtils.load_document_class(doc_class_path)

        # Extract schema components
        schema = doc_class.get("document_class_schema", {})
        document = schema.get("document", {})
        fields = document.get("fields", [])
        target_tables = schema.get("target_tables", [])

        if not fields:
            logger.warning("No fields found in document class: %s", doc_class_path)
            return {}

        if not target_tables:
            logger.warning("No target_tables found in document class: %s", doc_class_path)
            return {}

        # Build template
        template = DocumentClassUtils._build_template_from_fields(fields=fields, target_tables=target_tables)

        # Filter nested fields if requested
        if not include_nested:
            template = {k: v for k, v in template.items() if not isinstance(v, dict)}

        # Limit number of fields if requested
        if max_fields and len(template) > max_fields:
            logger.info("Limiting template to %s fields (from %s)", max_fields, len(template))
            # Keep first max_fields items
            template = dict(list(template.items())[:max_fields])

        logger.info("Generated Docling template with %s fields from %s", len(template), Path(doc_class_path).name)

        return template

    @staticmethod
    def _extract_field_metadata(
        fields_list: list[dict], examples: dict[str, list], descriptions: dict[str, str], prefix: str = ""
    ) -> None:
        """
        Recursively extract examples and descriptions from fields.

        Args:
            fields_list: List of field definitions
            examples: Dictionary to populate with examples (modified in-place)
            descriptions: Dictionary to populate with descriptions (modified in-place)
            prefix: Current field path prefix
        """
        for field in fields_list:
            field_name = field.get("name")
            if not field_name:
                continue

            full_name = f"{prefix}{field_name}" if prefix else field_name

            if "fields" in field:
                # Nested field - recurse
                DocumentClassUtils._extract_field_metadata(field["fields"], examples, descriptions, f"{full_name}.")
            else:
                # Regular field - extract metadata
                if field.get("examples"):
                    examples[full_name] = field["examples"]
                if field.get("description"):
                    descriptions[full_name] = field["description"]

    @staticmethod
    def generate_template_with_examples(doc_class_path: str | Path, include_nested: bool = True) -> dict[str, Any]:
        """
        Generate Docling template with examples included as comments.

        Args:
            doc_class_path: Path to document class JSON file
            include_nested: Whether to include nested fields

        Returns:
            Dictionary with template and examples metadata

        Example:
            >>> result = DocumentClassUtils.generate_template_with_examples(
            ...     "src/docpipe_app/backend/common/document_classes/invoice.json"
            ... )
            >>> print(result["template"])
            {"invoice_number": "string", ...}
            >>> print(result["examples"])
            {"invoice_number": ["INV-2024-001"], ...}
        """
        # Load document class
        doc_class = DocumentClassUtils.load_document_class(doc_class_path)

        # Generate base template
        template = DocumentClassUtils.generate_docling_template(
            doc_class_path=doc_class_path, include_nested=include_nested
        )

        # Extract examples and descriptions
        schema = doc_class.get("document_class_schema", {})
        document = schema.get("document", {})
        fields = document.get("fields", [])

        examples: dict[str, list] = {}
        descriptions: dict[str, str] = {}

        DocumentClassUtils._extract_field_metadata(fields, examples, descriptions)

        return {
            "template": template,
            "examples": examples,
            "descriptions": descriptions,
            "document_type": document.get("document_type"),
            "document_description": document.get("document_description"),
        }

    @staticmethod
    def list_available_document_classes() -> list[dict[str, str]]:
        """
        List all available document class JSON files.

        Returns:
            List of dictionaries with document class info
        """

        doc_classes_dir = Path(DocumentClassUtils.DOCUMENT_CLASSES_PATH)

        if not doc_classes_dir.exists():
            logger.warning("Document classes directory not found: %s", doc_classes_dir)
            return []

        result = []
        for json_file in doc_classes_dir.glob("*.json"):
            try:
                doc_class = DocumentClassUtils.load_document_class(json_file)
                result.append(
                    {
                        "file": str(json_file),
                        "name": doc_class.get("document_class_name", json_file.stem),
                        "id": doc_class.get("document_class_id", ""),
                        "description": doc_class.get("document_class_schema", {})
                        .get("document", {})
                        .get("document_description", ""),
                    }
                )
            except Exception as e:
                logger.warning("Error loading %s: %s", json_file, e)
                continue

        return sorted(result, key=lambda x: x["name"])

    @staticmethod
    def build_schema_description_from_fields(fields: list[dict[str, Any]], indent: int = 0) -> str:
        """
        Build rich schema description from fields array format.

        Args:
            fields: List of field definitions with name, description, examples, etc.
            indent: Current indentation level for nested fields

        Returns:
            Human-readable schema description with examples
        """
        lines: list[str] = []
        prefix = "  " * indent

        for field in fields:
            name = field.get("name", "")
            description = field.get("description", "")
            examples = field.get("examples", [])
            nested_fields = field.get("fields", [])

            # Build field line with description
            if description:
                line = f"{prefix}- {name}: {description}"
            else:
                line = f"{prefix}- {name}"

            # Add examples if available
            if examples:
                if len(examples) == 1:
                    line += f" (e.g., '{examples[0]}')"
                else:
                    examples_str = "', '".join(str(ex) for ex in examples[:3])  # Show up to 3 examples
                    line += f" (e.g., '{examples_str}')"

            lines.append(line)

            # Recursively handle nested fields
            if nested_fields:
                lines.append(f"{prefix}  Contains:")
                lines.append(DocumentClassUtils.build_schema_description_from_fields(nested_fields, indent + 2))

        return "\n".join(lines)

    @staticmethod
    def build_json_template_from_fields(fields: list[dict[str, Any]]) -> dict[str, Any]:
        """
        Build JSON template from fields array format.

        Args:
            fields: List of field definitions

        Returns:
            Nested dictionary template matching the schema structure.
            Leaf fields with available_options use a hint string so the LLM
            knows the allowed values; all other leaf fields use None.
        """
        template: dict[str, Any] = {}

        for field in fields:
            name = field.get("name", "")
            nested_fields = field.get("fields", [])

            if nested_fields:
                # This is a nested object or array
                nested_template = DocumentClassUtils.build_json_template_from_fields(nested_fields)
                # Check if it's an array type (like line_items)
                if isinstance(nested_fields, list):
                    template[name] = [nested_template]
                else:
                    template[name] = nested_template
            else:
                options = field.get("available_options", [])
                if options:
                    # Embed allowed values inline so the LLM picks the right one
                    template[name] = f"<one of: {', '.join(str(o) for o in options)}>"
                else:
                    template[name] = None

        return template

    @staticmethod
    def get_document_types() -> dict[str, str]:
        """
        Load document types from all JSON files in document classes directory.

        Returns:
            Dictionary mapping document_type to document_description
        """
        doc_classes_dir = Path(DocumentClassUtils.DOCUMENT_CLASSES_PATH)
        document_types = {}

        try:
            if not doc_classes_dir.exists():
                logger.warning("Document classes path not found: %s", doc_classes_dir)
                return {}

            # Read all .json files in the directory
            json_files = list(doc_classes_dir.glob("*.json"))
            logger.info("Found %s document class files in %s", len(json_files), doc_classes_dir)

            for json_file in json_files:
                try:
                    with Path(json_file).open(encoding="utf-8") as f:
                        data = json.load(f)

                    # Extract document_type and document_description from the schema
                    doc_schema = data.get("document_class_schema", {}).get("document", {})
                    doc_type = doc_schema.get("document_type")
                    doc_description = doc_schema.get("document_description")

                    if doc_type and doc_description:
                        document_types[doc_type] = doc_description
                        logger.debug("Loaded document type '%s' from %s", doc_type, json_file.name)
                    else:
                        logger.warning("Skipping %s: missing document_type or document_description", json_file.name)

                except (OSError, json.JSONDecodeError) as e:
                    logger.warning("Failed to load %s: %s", json_file.name, str(e))
                    continue

            logger.info("Successfully loaded %s document types", len(document_types))
            return document_types

        except Exception as e:
            logger.error("Error loading document types: %s", str(e))
            return {}

    @staticmethod
    def get_schema_templates(document_types: list[str]) -> dict[str, dict]:
        """
        Load document class schemas for given document types.

        Args:
            document_types: List of document type names to load

        Returns:
            Dictionary mapping document_type to schema dict
        """

        doc_classes_dir = Path(DocumentClassUtils.DOCUMENT_CLASSES_PATH)
        schema_templates: dict[str, dict] = {}

        for document_type in document_types:
            if not document_type or document_type in schema_templates:
                continue

            file_name = doc_classes_dir / f"{DocumentClassUtils.normalize_filename(document_type)}.json"
            try:
                with Path(file_name).open(encoding="utf-8") as f:
                    doc_cls = json.load(f)
                    doc_cls = doc_cls.get("document_class_schema", {}).get("document", {})
                    if doc_cls:
                        schema_templates[document_type] = doc_cls
                        logger.info("Loaded schema for document type '%s' from %s", document_type, file_name)
                    else:
                        logger.warning("No valid schema found in %s", file_name)
            except (OSError, json.JSONDecodeError) as exc:
                logger.warning("Failed to load schema for '%s' from %s: %s", document_type, file_name, exc)

        return schema_templates

    @staticmethod
    def generate_docling_templates_for_types(
        document_types: list[str],
        include_nested: bool = True,
    ) -> dict[str, dict]:
        """
        Generate Docling templates for document types and update template_cache in-place.

        This method is optimized for performance by:
        - Processing only unique document types
        - Updating cache in-place to avoid memory overhead
        - Skipping already cached templates

        Args:
            document_types: List of document type names (may contain duplicates)
            include_nested: Whether to include nested fields in templates
        """

        doc_classes_dir = Path(DocpipeConstants.DOCUMENT_CLASSES_PATH)
        schema_templates: dict[str, dict] = {}
        # Get unique document types, excluding already cached ones
        unique_doc_types = {dt for dt in document_types if dt}

        if not unique_doc_types:
            logger.debug("No new document types to process for template generation")
            return schema_templates

        logger.info("Generating Docling templates for document types: %s", unique_doc_types)

        for doc_type in unique_doc_types:
            try:
                # Construct path to document class file
                normalized_name = DocumentClassUtils.normalize_filename(doc_type)
                doc_class_path = doc_classes_dir / f"{normalized_name}.json"

                if not doc_class_path.exists():
                    logger.warning("Document class file not found for type '%s': %s", doc_type, doc_class_path)
                    continue

                # Generate Docling template from document class
                template = DocumentClassUtils.generate_docling_template(
                    doc_class_path=doc_class_path, include_nested=include_nested
                )

                # Update cache in-place
                schema_templates[doc_type] = template
                logger.info("Generated Docling template for '%s' with %s fields", doc_type, len(template))

            except Exception as e:
                logger.warning("Failed to generate Docling template for '%s': %s", doc_type, e)

        return schema_templates

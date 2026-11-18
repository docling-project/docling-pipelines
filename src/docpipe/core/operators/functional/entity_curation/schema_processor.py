"""
Schema-based processing for entity curation.

This module handles the transformation of extracted entities using document class schemas.
It applies field filtering, type transformations, and handles nested structures.
"""

import json
from pathlib import Path
from typing import Any

from docpipe.core.constants.constants import DocpipeConstants, DocumentConstants
from docpipe.utils.document_class_utils import DocumentClassUtils
from docpipe.utils.infrastructure.logging import get_logger

from .transforms import TRANSFORMS

logger = get_logger(__name__)


class SchemaProcessor:
    """Processes entities based on document class schemas."""

    def __init__(self):
        """Initialize the schema processor with an empty cache."""
        self.schema_cache: dict[str, dict] = {}

    def load_schemas(self, *, document_types: list[str]) -> None:
        """
        Load full schemas (with target_tables) for document types from file system.

        Args:
            document_types: List of document type names
        """
        # Load full schemas with target_tables for entity curation
        doc_classes_dir = Path(DocpipeConstants.DOCUMENT_CLASSES_PATH)

        for document_type in document_types:
            if not document_type or document_type in self.schema_cache:
                continue

            file_name = doc_classes_dir / f"{DocumentClassUtils.normalize_filename(document_type)}.json"
            try:
                with Path(file_name).open(encoding="utf-8") as f:
                    doc_cls = json.load(f)
                    # Get the full document_class_schema (includes both document and target_tables)
                    doc_cls_schema = doc_cls.get("document_class_schema", {})
                    if doc_cls_schema:
                        self.schema_cache[document_type] = doc_cls_schema
                        logger.info("Loaded schema for document type '%s' from %s", document_type, file_name)
                    else:
                        logger.warning("No valid schema found in %s", file_name)
            except (OSError, json.JSONDecodeError) as exc:
                logger.warning("Failed to load schema for '%s' from %s: %s", document_type, file_name, exc)

        logger.info("Loaded %s schemas: %s", len(self.schema_cache), list(self.schema_cache.keys()))

    def process_with_schema(self, *, entities: dict[str, Any], document_type: str) -> dict[str, Any]:
        """
        Process entities using document class schema.

        Args:
            entities: Extracted entities dictionary
            document_type: Document type name

        Returns:
            Curated entities with transformations applied.
            Values can be either dict (single object) or list[dict] (array of objects).
        """
        schema = self.schema_cache.get(document_type)
        if not schema:
            logger.warning("No schema found for document type '%s', returning empty dict", document_type)
            return {}

        # Get target tables from schema
        target_tables = schema.get(DocumentConstants.TARGET_TABLES, [])
        if not target_tables:
            logger.warning("No target tables in schema for '%s'", document_type)
            return {}

        # Process each target table
        result: dict[str, Any] = {}
        for table in target_tables:
            table_name = table.get(DocumentConstants.TABLE_NAME)
            columns = table.get(DocumentConstants.COLUMNS, [])

            logger.debug("Processing table '%s' with %s columns", table_name, len(columns))

            # Detect if this is an array-based table
            array_field = self._detect_array_field(columns=columns, entities=entities)

            if array_field:
                # Process as array table - returns list[dict]
                result[table_name] = self._process_array_table(
                    columns=columns, entities=entities, array_field=array_field
                )
            else:
                # Process as single object table - returns dict
                result[table_name] = self._process_single_table(columns=columns, entities=entities)

        return result

    def _detect_array_field(self, *, columns: list[dict], entities: dict[str, Any]) -> str | None:
        """
        Detect if all columns reference the same array field.

        Args:
            columns: List of column definitions from schema
            entities: Extracted entities dictionary

        Returns:
            The array field name if detected, None otherwise
        """
        array_fields: set[str] = set()

        for column in columns:
            source = column.get(DocumentConstants.SOURCE, {})

            # Check field reference
            if DocumentConstants.FIELD in source:
                field_path = source[DocumentConstants.FIELD]
                self._check_and_add_array_field(field_path=field_path, entities=entities, array_fields=array_fields)

            # Check transform arguments
            elif DocumentConstants.TRANSFORM in source:
                transform = source[DocumentConstants.TRANSFORM]
                arguments = transform.get(DocumentConstants.ARGUMENTS, [])

                for arg in arguments:
                    arg_value = arg.get(DocumentConstants.ARG_VALUE, {})
                    if DocumentConstants.FIELD in arg_value:
                        field_path = arg_value[DocumentConstants.FIELD]
                        self._check_and_add_array_field(
                            field_path=field_path, entities=entities, array_fields=array_fields
                        )

        # If all columns reference the same array field, return it
        if len(array_fields) == 1:
            return array_fields.pop()

        # Warn if multiple array fields detected - will cause silent data loss
        if len(array_fields) > 1:
            logger.warning(
                "Columns reference multiple array fields %s; falling back to single-table mode",
                sorted(array_fields),
            )

        return None

    def _check_and_add_array_field(
        self, *, field_path: list[str] | None, entities: dict[str, Any], array_fields: set[str]
    ) -> None:
        """
        Check if a field path references an array and add it to the set.

        Args:
            field_path: Field path from schema (e.g., ["line_items", "amount"])
            entities: Extracted entities dictionary
            array_fields: Set to add array field names to (modified in place)
        """
        if field_path and len(field_path) > 0:
            first_field = field_path[0]
            if isinstance(entities.get(first_field), list):
                array_fields.add(first_field)

    def _process_array_table(
        self, *, columns: list[dict], entities: dict[str, Any], array_field: str
    ) -> list[dict[str, Any]]:
        """
        Process a table where all columns reference elements of an array.

        Args:
            columns: List of column definitions from schema
            entities: Extracted entities dictionary
            array_field: Name of the array field in entities

        Returns:
            List of processed objects, one per array element
        """
        # _detect_array_field only returns fields whose value in these entities is a list
        array_data: list[Any] = entities[array_field]

        result = []

        for idx, item in enumerate(array_data):
            logger.debug("Processing array item %s from '%s'", idx, array_field)

            # Create a temporary entities dict with the array item at the root
            temp_entities = {**entities, array_field: item}

            item_result: dict[str, Any] = {}
            for column in columns:
                col_name = column.get(DocumentConstants.COLUMN_NAME)
                if not col_name:
                    continue

                source = column.get(DocumentConstants.SOURCE, {})

                # Handle direct field reference
                if DocumentConstants.FIELD in source:
                    field_path = source[DocumentConstants.FIELD]
                    # Skip the array field name in the path
                    if field_path and field_path[0] == array_field:
                        adjusted_path = field_path[1:]
                        value = self._get_nested_value(obj=item, path=adjusted_path)
                    else:
                        value = self._get_nested_value(obj=temp_entities, path=field_path)
                    item_result[col_name] = value

                # Handle transformation
                elif DocumentConstants.TRANSFORM in source:
                    transform = source[DocumentConstants.TRANSFORM]
                    transform_name = transform.get(DocumentConstants.TRANSFORM_NAME)
                    arguments = transform.get(DocumentConstants.ARGUMENTS, [])

                    value = self._apply_transformation_for_array_item(
                        transform_name=transform_name,
                        arguments=arguments,
                        entities=temp_entities,
                        array_field=array_field,
                        array_item=item,
                    )
                    item_result[col_name] = value

            result.append(item_result)

        logger.debug("Processed %s items for array field '%s'", len(result), array_field)
        return result

    def _process_single_table(self, *, columns: list[dict], entities: dict[str, Any]) -> dict[str, Any]:
        """
        Process a table as a single object (non-array table).

        Args:
            columns: List of column definitions from schema
            entities: Extracted entities dictionary

        Returns:
            Processed object with column values
        """
        table_result: dict[str, Any] = {}
        for column in columns:
            col_name = column.get(DocumentConstants.COLUMN_NAME)
            if not col_name:
                continue

            source = column.get(DocumentConstants.SOURCE, {})

            # Handle direct field reference
            if DocumentConstants.FIELD in source:
                field_path = source[DocumentConstants.FIELD]
                value = self._get_nested_value(obj=entities, path=field_path)
                table_result[col_name] = value

            # Handle transformation
            elif DocumentConstants.TRANSFORM in source:
                transform = source[DocumentConstants.TRANSFORM]
                transform_name = transform.get(DocumentConstants.TRANSFORM_NAME)
                arguments = transform.get(DocumentConstants.ARGUMENTS, [])

                value = self._apply_transformation(
                    transform_name=transform_name, arguments=arguments, entities=entities
                )
                table_result[col_name] = value

        return table_result

    def _apply_transformation(
        self, *, transform_name: str, arguments: list[dict[str, Any]], entities: dict[str, Any]
    ) -> Any:
        """
        Apply a transformation function with arguments.

        Args:
            transform_name: Name of the transformation function
            arguments: List of argument definitions from schema
            entities: Extracted entities dictionary

        Returns:
            Transformed value or None if transformation fails
        """
        func = TRANSFORMS.get(transform_name)
        if not func:
            logger.warning("Unknown transformation: %s", transform_name)
            return None

        # Resolve argument values
        kwargs = self._resolve_transformation_arguments(
            arguments=arguments, entities=entities, array_field=None, array_item=None
        )

        # Debug log to inspect transformation inputs
        logger.debug(
            "Applying transformation '%s' with arguments: %s",
            transform_name,
            ", ".join(f"{k}={v!r} (type={type(v).__name__})" for k, v in kwargs.items()),
        )

        try:
            return func(**kwargs)
        except Exception as e:
            logger.warning(
                "Transformation %s failed: %s. Arguments were: %s",
                transform_name,
                e,
                ", ".join(f"{k}={v!r}" for k, v in kwargs.items()),
            )
            return None

    def _apply_transformation_for_array_item(
        self,
        *,
        transform_name: str,
        arguments: list[dict[str, Any]],
        entities: dict[str, Any],
        array_field: str,
        array_item: dict[str, Any],
    ) -> Any:
        """
        Apply transformation for an array item, adjusting field paths.

        Args:
            transform_name: Name of the transformation function
            arguments: List of argument definitions from schema
            entities: Extracted entities dictionary
            array_field: Name of the array field
            array_item: Current array item being processed

        Returns:
            Transformed value or None if transformation fails
        """
        func = TRANSFORMS.get(transform_name)
        if not func:
            logger.warning("Unknown transformation: %s", transform_name)
            return None

        # Resolve argument values with array path adjustment
        kwargs = self._resolve_transformation_arguments(
            arguments=arguments, entities=entities, array_field=array_field, array_item=array_item
        )

        # Debug log
        logger.debug(
            "Applying transformation '%s' with arguments: %s",
            transform_name,
            ", ".join(f"{k}={v!r} (type={type(v).__name__})" for k, v in kwargs.items()),
        )

        try:
            return func(**kwargs)
        except Exception as e:
            logger.warning(
                "Transformation %s failed: %s. Arguments were: %s",
                transform_name,
                e,
                ", ".join(f"{k}={v!r}" for k, v in kwargs.items()),
            )
            return None

    def _resolve_transformation_arguments(
        self,
        *,
        arguments: list[dict[str, Any]],
        entities: dict[str, Any],
        array_field: str | None,
        array_item: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """
        Resolve transformation arguments to kwargs.

        Args:
            arguments: List of argument definitions from schema
            entities: Extracted entities dictionary
            array_field: Name of array field (None for non-array processing)
            array_item: Current array item (None for non-array processing)

        Returns:
            Dictionary of resolved argument name -> value pairs
        """
        kwargs = {}
        for arg in arguments:
            arg_name = arg.get(DocumentConstants.ARG_NAME)
            arg_value = arg.get(DocumentConstants.ARG_VALUE, {})

            # Ensure arg_name is a string
            if not isinstance(arg_name, str):
                logger.warning("Invalid argument name type: %s", type(arg_name))
                continue

            if DocumentConstants.FIELD in arg_value:
                field_path = arg_value[DocumentConstants.FIELD]

                # Handle array item path adjustment
                if array_field and array_item and field_path and field_path[0] == array_field:
                    adjusted_path = field_path[1:]
                    value = self._get_nested_value(obj=array_item, path=adjusted_path)
                else:
                    value = self._get_nested_value(obj=entities, path=field_path)

                kwargs[arg_name] = value
            else:
                kwargs[arg_name] = arg_value

        return kwargs

    @staticmethod
    def _get_nested_value(*, obj: dict, path: list[str]) -> Any:
        """
        Get value from nested dictionary using path.

        Args:
            obj: Dictionary to traverse
            path: List of keys representing the path

        Returns:
            Value at the path or None if not found
        """
        value: Any = obj
        for key in path:
            if isinstance(value, dict):
                value = value.get(key)
            else:
                return None
        return value

# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""
Helper functions and classes for PII and HAP detection.

This module provides utility functions for managing PII and HAP detection results,
including table column management, field mapping, and redaction logic.
"""

from typing import Any

import pyarrow as pa
import re2 as re
from data_processing.utils import TransformUtils

from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.utils.infrastructure.logging import get_logger

logger = get_logger(__name__)

# Constants
DEFAULT_REDACTIONS = [
    OperatorConstants.PIIHAP.PII_FIELD_NAME,
    OperatorConstants.PIIHAP.HAP_FIELD_NAME,
]

DEFAULT_PII_TO_COLUMN_MAPPING = {
    "BankAccountNumber": "bank_account",
    "CreditCardNumber": "credit_card",
    "EmailAddress": "email_address",
    "IPAddress": "ip_address",
    "PhoneNumber": "phone_number",
    "SocialSecurityNumber": "ssn_details",
    OperatorConstants.PIIHAP.PII_TYPE_PERSON_NAME: OperatorConstants.PIIHAP.PII_SEARCH_PERSON_NAME,
    OperatorConstants.PIIHAP.PII_TYPE_DATE_OF_BIRTH: OperatorConstants.PIIHAP.PII_SEARCH_DATE_OF_BIRTH,
    OperatorConstants.PIIHAP.PII_TYPE_ADDRESS: OperatorConstants.PIIHAP.PII_SEARCH_ADDRESS,
    OperatorConstants.PIIHAP.PII_TYPE_PASSPORT_NUMBER: OperatorConstants.PIIHAP.PII_SEARCH_PASSPORT_NUMBER,
    OperatorConstants.PIIHAP.PII_TYPE_DRIVER_LICENSE: OperatorConstants.PIIHAP.PII_SEARCH_DRIVER_LICENSE,
    OperatorConstants.PIIHAP.PII_TYPE_NATIONAL_ID: OperatorConstants.PIIHAP.PII_SEARCH_NATIONAL_ID,
    OperatorConstants.PIIHAP.PII_TYPE_MEDICAL_RECORD: OperatorConstants.PIIHAP.PII_SEARCH_MEDICAL_RECORD,
}

DEFAULT_PII_TYPES_OF_CONCERN = list(DEFAULT_PII_TO_COLUMN_MAPPING.keys())
DISPLAY_PII_KEY = "display_pii"
PII_COLUMN_PREFIX = "pii_"
DISPLAY_PII_COLUMN_SUFFIX = "_info"
COLUMN_NAME_SUFFIX = "_column"
DEFAULT_PII_THRESHOLD_VALUE = 0.5

METADATA_HAP_FIELD_NAME = OperatorConstants.PIIHAP.REDACTION_TYPE_HAP
DEFAULT_HAP_THRESHOLD_VALUE = 0.8
MIN_HAP_THRESHOLD_VALUE = 0.0
MAX_HAP_THRESHOLD_VALUE = 1.0


def get_fields_to_redact(expected_redactions: set[str] | list[str], pii_list: list[str]) -> list[str]:
    """
    Find fields to redact based on user input.

    Args:
        expected_redactions: Set or list of redaction types (PII, HAP)
        pii_list: List of specific PII types to detect

    Returns:
        List of field names to redact
    """
    fields_to_redact = []

    for expected_redaction in expected_redactions:
        if expected_redaction == OperatorConstants.PIIHAP.HAP_FIELD_NAME:
            fields_to_redact.append(METADATA_HAP_FIELD_NAME)
        elif expected_redaction == OperatorConstants.PIIHAP.PII_FIELD_NAME:
            fields_to_redact.extend(pii_list if pii_list else DEFAULT_PII_TYPES_OF_CONCERN)

    return fields_to_redact


def initialize_table_columns(
    *, metadata: dict[str, Any], fields_to_redact: list[str], display_pii: bool = False
) -> dict[str, list]:
    """
    Initialize table columns and add field-specific metadata counters.

    Args:
        metadata: Metadata dictionary to update
        fields_to_redact: List of fields to create columns for
        display_pii: Whether to include PII display columns

    Returns:
        Dictionary of column names to empty lists
    """
    table_columns: dict[str, list[Any]] = {}

    for field in fields_to_redact:
        metadata[field] = 0

        if field == METADATA_HAP_FIELD_NAME:
            table_columns[OperatorConstants.PIIHAP.HAP_FIELD_NAME] = []
        elif field in DEFAULT_PII_TO_COLUMN_MAPPING:
            table_column_name = DEFAULT_PII_TO_COLUMN_MAPPING.get(field, "")
            if not table_column_name:
                continue
            pii_column_name = PII_COLUMN_PREFIX + table_column_name + COLUMN_NAME_SUFFIX
            table_columns[pii_column_name] = []

            if display_pii:
                display_pii_column_name = (
                    PII_COLUMN_PREFIX + table_column_name + DISPLAY_PII_COLUMN_SUFFIX + COLUMN_NAME_SUFFIX
                )
                table_columns[display_pii_column_name] = []

    return table_columns


def get_detected_field(detection_dict: dict[str, Any], fields_to_redact: list[str]) -> str:
    """
    Get the detected field name from detection dictionary.

    Args:
        detection_dict: Detection result dictionary
        fields_to_redact: List of fields we're looking for

    Returns:
        Detected field name or empty string if not found
    """
    detected_field = detection_dict.get("detection")

    # Exact match
    if detected_field in fields_to_redact:
        return detected_field

    # Partial match (e.g., "NationalNumber.SocialSecurityNumber.US" matches "SocialSecurityNumber")
    if detected_field:
        matches = []
        for field in fields_to_redact:
            if field in detected_field:
                matches.append(field)
    else:
        matches = []

    return matches[-1] if matches else ""


def update_table(
    table: pa.Table,
    table_columns: dict[str, list],
    fields_to_redact: list[str],
    display_pii: bool,
) -> pa.Table:
    """
    Update table with new PII and HAP columns.

    Args:
        table: Input PyArrow table
        table_columns: Dictionary of column data
        fields_to_redact: List of fields that were processed
        display_pii: Whether PII display columns were created

    Returns:
        Updated PyArrow table with new columns
    """
    for field in fields_to_redact:
        column_name = DEFAULT_PII_TO_COLUMN_MAPPING.get(field)
        if column_name:
            pii_column_name = PII_COLUMN_PREFIX + column_name
            table = TransformUtils.add_column(
                table=table,
                name=pii_column_name,
                content=table_columns[pii_column_name + COLUMN_NAME_SUFFIX],
            )

    # Add display columns in separate loop to preserve order
    if display_pii:
        for field in fields_to_redact:
            column_name = DEFAULT_PII_TO_COLUMN_MAPPING.get(field)
            if column_name:
                display_pii_column_name = PII_COLUMN_PREFIX + column_name + DISPLAY_PII_COLUMN_SUFFIX
                table = TransformUtils.add_column(
                    table=table,
                    name=display_pii_column_name,
                    content=table_columns[display_pii_column_name + COLUMN_NAME_SUFFIX],
                )

    if METADATA_HAP_FIELD_NAME in fields_to_redact:
        table = TransformUtils.add_column(
            table=table,
            name=OperatorConstants.PIIHAP.HAP_FIELD_NAME,
            content=table_columns[OperatorConstants.PIIHAP.HAP_FIELD_NAME],
        )

    return table


class GuardRailsPIIAndHAPExtractor:
    """
    Extractor class for PII and HAP detection with redaction support.

    This class manages the extraction and optional redaction of PII and HAP
    content from documents.
    """

    def __init__(self, config: dict[str, Any]):
        """
        Initialize the extractor with configuration.

        Args:
            config: Configuration dictionary
        """
        self.doc_column_name = config.get(
            OperatorConstants.Columns.DOC_COLUMN, OperatorConstants.Columns.DOC_COLUMN_DEFAULT
        )
        self.expected_redactions = config.get(OperatorConstants.PIIHAP.EXPECTED_REDACTIONS, DEFAULT_REDACTIONS)
        self.pii_list = config.get(OperatorConstants.PIIHAP.PII_LIST, DEFAULT_PII_TYPES_OF_CONCERN)
        self.redaction = config.get(OperatorConstants.PIIHAP.REDACTION_KEY, False)
        self.redaction_character = config.get(OperatorConstants.PIIHAP.REDACTION_CHARACTER_KEY, "*")
        self.hap_redaction = config.get(OperatorConstants.PIIHAP.HAP_REDACTION_KEY, False)
        self.hap_redaction_character = config.get(OperatorConstants.PIIHAP.HAP_REDACTION_CHARACTER_KEY, "*")
        self.display_pii = config.get(DISPLAY_PII_KEY, False)

    def redact(self, content: Any, item: dict[str, Any], detected_type: str) -> str:
        """
        Redact detected content from text.

        Note: For handling multiple overlapping detections, use redact_batch() instead,
        which properly sorts detections by position and handles overlaps.

        Args:
            content: Document content (string or PyArrow scalar)
            item: Detection item with 'start'/'end' positions and optional 'text' field
            detected_type: Type of detection (PII or HAP)

        Returns:
            Content with redacted text
        """
        if not isinstance(content, str):
            content = content.as_py()

        redaction_character = (
            self.hap_redaction_character if detected_type == METADATA_HAP_FIELD_NAME else self.redaction_character
        )

        # Validate redaction character is a single safe character
        if not isinstance(redaction_character, str) or len(redaction_character) != 1:
            logger.warning("Invalid redaction character '%s'. Using default '*'.", redaction_character)
            redaction_character = "*"

        redaction_symbol = redaction_character

        # If position information is available, use it for precise redaction
        if "start" in item and "end" in item:
            start = item["start"]
            end = item["end"]
            redaction_length = end - start
            redacted_word = redaction_symbol * redaction_length
            content = content[:start] + redacted_word + content[end:]
        elif item.get("text"):
            # Fallback to text-based redaction
            redaction_length = len(item["text"])
            redacted_word = redaction_symbol * redaction_length
            text_to_redact = item["text"]
            pattern = re.compile("(?i)" + re.escape(text_to_redact))
            content = pattern.sub(redacted_word, content)
        else:
            # No position or text - cannot redact
            logger.warning(
                "Detection missing both position and text, cannot redact: %s", item.get("detection", "unknown")
            )

        return content

    def redact_batch(self, content: Any, detections: list[dict[str, Any]], detected_types: list[str]) -> str:
        """
        Redact multiple detections from text, handling overlaps correctly.

        This method sorts detections by position and redacts from end to start
        to preserve character positions. Overlapping detections are merged.

        Args:
            content: Document content (string or PyArrow scalar)
            detections: List of detection items with 'text' and optional 'start'/'end'
            detected_types: List of detection types corresponding to each detection

        Returns:
            Content with all detections redacted
        """
        if not isinstance(content, str):
            content = content.as_py()

        if not detections:
            return content

        # Prepare redaction items with positions
        redaction_items = []
        for item, detected_type in zip(detections, detected_types, strict=True):
            redaction_character = (
                self.hap_redaction_character if detected_type == METADATA_HAP_FIELD_NAME else self.redaction_character
            )

            # Find all occurrences if position not provided
            if "start" not in item or "end" not in item:
                text_to_find = item["text"]
                pattern = re.compile("(?i)" + re.escape(text_to_find))
                for match in pattern.finditer(content):
                    redaction_items.append(
                        {
                            "start": match.start(),
                            "end": match.end(),
                            "text": match.group(),
                            "redaction_char": redaction_character,
                        }
                    )
            else:
                redaction_items.append(
                    {
                        "start": item["start"],
                        "end": item["end"],
                        "text": item["text"],
                        "redaction_char": redaction_character,
                    }
                )

        if not redaction_items:
            return content

        # Sort by start position
        redaction_items.sort(key=lambda x: x["start"])

        # Merge overlapping detections
        merged_items: list[dict[str, Any]] = []
        for item in redaction_items:
            if not merged_items:
                merged_items.append(item)
            else:
                last = merged_items[-1]
                # Check for overlap
                if item["start"] <= last["end"]:
                    # Merge: extend the end position and use the longer text
                    last["end"] = max(last["end"], item["end"])
                    last["text"] = content[last["start"] : last["end"]]
                else:
                    merged_items.append(item)

        # Redact from end to start to preserve positions
        for item in reversed(merged_items):
            redacted_word = item["redaction_char"] * (item["end"] - item["start"])
            content = content[: item["start"]] + redacted_word + content[item["end"] :]

        return content

    def redact_if_needed(self, detected_field: str, input_dict: dict[str, Any]) -> tuple[pa.Table, Any]:
        """
        Redact content if redaction is enabled for the detected field.

        Args:
            detected_field: Name of the detected field
            input_dict: Dictionary containing table, content, and detection info

        Returns:
            Tuple of (updated table, updated content)
        """
        redaction_flag = self.hap_redaction if detected_field == METADATA_HAP_FIELD_NAME else self.redaction
        content_column_name = OperatorConstants.Columns.DOC_COLUMN_DEFAULT

        if redaction_flag:
            input_dict["doc_content"] = self.redact(
                input_dict["doc_content"], input_dict["detection_dict"], detected_field
            )
            input_dict["updated_content_list"][input_dict["row_index"]] = input_dict["doc_content"]
            new_content = pa.array(input_dict["updated_content_list"])
            table = input_dict["table"].set_column(
                input_dict["table"].column_names.index(content_column_name),
                content_column_name,
                new_content,
            )
            return table, input_dict["doc_content"]

        return input_dict["table"], input_dict["doc_content"]

    def update_metadata_and_columns_to_add(
        self,
        metadata: dict[str, Any],
        columns_to_add: dict[str, Any],
        detected_field: str,
        detection_dict: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """
        Update metadata and column values with detection results.

        Args:
            metadata: Metadata dictionary
            columns_to_add: Column values dictionary
            detected_field: Name of detected field
            detection_dict: Detection result dictionary

        Returns:
            Tuple of (updated metadata, updated columns_to_add)
        """
        metadata[detected_field] += 1

        if detected_field == METADATA_HAP_FIELD_NAME:
            # Always store counts for HAP, regardless of redaction setting
            columns_to_add[OperatorConstants.PIIHAP.HAP_FIELD_NAME] += 1
        else:
            column_name = DEFAULT_PII_TO_COLUMN_MAPPING[detected_field]
            columns_to_add[column_name] += 1

            if self.display_pii:
                columns_to_add[column_name + DISPLAY_PII_COLUMN_SUFFIX].append(detection_dict)

        return metadata, columns_to_add

    def column_values(self, fields_to_redact: list[str]) -> dict[str, Any]:
        """
        Initialize column values based on redaction flags.

        Args:
            fields_to_redact: List of fields to create columns for

        Returns:
            Dictionary of column names to initial values
        """
        columns_to_add: dict[str, int | list[Any]] = {}

        for field in fields_to_redact:
            column_name = DEFAULT_PII_TO_COLUMN_MAPPING.get(field)
            if column_name:
                columns_to_add[column_name] = 0

                if self.display_pii:
                    columns_to_add[column_name + DISPLAY_PII_COLUMN_SUFFIX] = []

        if METADATA_HAP_FIELD_NAME in fields_to_redact:
            # Always initialize as counter for HAP
            columns_to_add[OperatorConstants.PIIHAP.HAP_FIELD_NAME] = 0

        return columns_to_add

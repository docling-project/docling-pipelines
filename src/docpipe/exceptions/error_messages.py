# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Shared validation messages and structured alert payloads."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class ValidationMessage(BaseModel):
    """
    this class can be used to bind together validation error message and its extra arguments for validation alert model

    """

    message: str | None = None
    message_code: str | None = None

    model_config = ConfigDict(extra="allow")

    @classmethod
    def create(cls, message: str, message_code: str | None = None, **kwargs) -> "ValidationMessage":
        """
        Factory method to create a ValidationMessage with extra attributes.

        Args:
            message (str): The validation message.
            message_code (Optional[str]): Optional code for the message.
            **extras (Any): Any additional fields to include.

        Returns:
            ValidationMessage: An instance of the class with all fields.
        """
        return cls(message=message, message_code=message_code, **kwargs)

    def __str__(self) -> str:
        """Return a readable string representation of the validation message."""
        if self.message_code:
            return f"{self.message_code}: {self.message}"
        return self.message or ""

    def __contains__(self, item: str) -> bool:
        """Check if a string is contained in the message or message_code."""
        message_str = str(self)
        return item.lower() in message_str.lower()


class ValidationCodeMessages(StrEnum):
    """Validationcodemessages."""

    INGEST_PROVIDER_MISSING = "Provider not added. Select a provider for the ingest source operator."

    MISSING_FEATURES = """Not all required features for {operator_name} operator are available - required: {missing_features},
        Missing one or more operators:  {missing_operators},
        Please consider adding the missing operators to ensure full functionality
        """

    MISSING_COLUMNS = """Not all required columns for {operator_name} operator are present in the table - required {missing_features},
        Missing one or more operators:  {missing_operators},
        Please consider adding the missing operators to ensure full functionality """

    OPERATOR_NAME_REPEATED = """Same operator name(s) are used for multiple operators, operator(s): {operators}"""

    MISSING_MODEL_ID_FOR_EMBEDDINGS = (
        """Missing model id for generating embeddings. Model ID not found in project settings or configuration."""
    )

    INVALID_EMBEDDINGS_MODEL_ID = """Invalid embeddings model ID '{model_id}'. This model is not available to generate embeddings. Please verify the model ID."""

    EXTRACT_OPERATOR_MISSING = """Extract operator is either missing or not connected in the flow."""

    CHUNKER_OPERATOR_MISSING = """Chunker operator is either missing or not connected in the flow or is placed after the Embeddings operator."""

    INGEST_OPERATOR_MISPLACED = """The first operator in the flow must be an "Ingest data" operator"""

    GENERATE_OUTPUT_MISSING = """The last operator is not a "Generate Output" operator"""

    MULTIPLE_EXTRACTED_DETECTED = """Multiple extract operators detected. Ensure they are used correctly"""

    PIPELINE_NOT_FOUND_ERROR = """Flow must have 'dag'."""

    DAG_PIPELINE_MISSING = """The DAG pipeline is empty or missing."""

    MISSING_NODE_ID = """ID is missing for the node"""

    MISSING_NODE_NAME = """Name is missing for the node"""

    GET_OPERATOR_FAILED = """Failed to get operator."""

    SQL_FILTER_ID_DROP_ATTEMPTED = """ID column drop was attempted"""

    SQL_FILTER_CONTENT_DROP_ATTEMPTED = """Content column drop was attempted"""

    SQL_FILTER_PAGES_DROP = """Pages Processed column drop was attempted"""

    SQL_FILTER_ALLOWED_USERS_DROP_ATTEMPTED = """allowed_users column drop was attempted"""

    SQL_FILTER_CHUNKED_CONTENT_DROP_ATTEMPTED = """chunked_content column drop was attempted"""

    SQL_FILTER_INVALID_COLUMN = """Invalid column name. Please ensure the filter_criteria has correct column names"""

    CHUNKER_INVALID_CHUNK_TYPE = "Invalid chunk_type: {chunk_type}"

    CHUNK_OVERLAP_EXCEEDS_THRESHOLD = (
        "chunk_overlap_percentage exceeds the recommended threshold of {threshold}%. "
        "High overlap may significantly increase processing time and storage."
    )

    CHUNKER_OPERATOR_MISPLACED = "Invalid Flow definition. Chunking operator placed after Embeddings operator. Please rearrange the chunking operator in the flow"

    EMBEDDINGS_INVALID_TYPE = "Invalid embeddings type: {embeddings_type}"

    DROPPING_MANDATORY_FEATURES = "Mandatory features drop attempted: {mandatory_features} By node: '{operator}', mandatory features cannot be dropped"

    RENAMING_MANDATORY_FEATURES = (
        "Mandatory features rename attempted: {mandatory_features}, renaming of mandatory features is not allowed"
    )

    DISJOINT_OPERATORS_DETECTED = (
        """Flow contains disconnected operators. Ensure every operator has valid input and output connections."""
    )

    INVALID_FLOW_WRAPPER = "Flow wrapper contains invalid structure"

    # Document Library error messages
    DOCUMENT_LIBRARY_NOT_FOUND = "Document library not found: {details}"
    DOCUMENT_LIBRARY_INVALID_DATA = "Invalid document library data: {details}"
    DOCUMENT_LIBRARY_STORAGE_ERROR = "Document library storage error: {details}"
    DOCUMENT_LIBRARY_ALREADY_EXISTS = "Document library with name '{name}' already exists"
    DOCUMENT_LIBRARY_DOCUMENTSET_NOT_FOUND = "Document set not found: {details}"
    DOCUMENT_LIBRARY_TABLE_ERROR = "Document library table error: {details}"

    # Document Set errors
    DOCUMENT_SET_NOT_FOUND = "Document set not found: {document_set_id}"
    DOCUMENT_SET_INVALID_DATA = "Invalid data for document set: {details}"
    DOCUMENT_SET_STORAGE_ERROR = "Storage error for document set: {details}"
    DOCUMENT_SET_INVALID_NAME = "Invalid document set name: {name}"
    DOCUMENT_SET_TABLE_ERROR = "Table operation failed: {details}"

    # Merge Operator errors
    MERGE_INPUT_LINKS_INSUFFICIENT = "At least two input links are required for merging. Please connect at least two operators to the Merge operator."
    MERGE_TYPE_NOT_PROVIDED = "Merge type is required. Please specify 'merge_type' in the operator configuration as either 'rows' or 'columns'."
    INVALID_MERGE_TYPE = "Invalid merge type '{merge_type}'. Please use either 'rows' or 'columns'."
    MERGE_COLUMN_OPTION_NOT_PROVIDED = "Column option is required when merge_type is 'columns'. Please specify 'column_option' as either 'inner_join' or 'full_outer'."
    MERGE_INVALID_COLUMN_OPTION = "Invalid column option '{column_option}'. When merge_type is 'columns', column_option must be either 'inner_join' or 'full_outer'."
    DATABASE_CONNECTION_ERROR = "Failed to connect to database: {details}"

    # ACL Operator errors
    ACL_OPERATOR_NO_INPUT = "ACL operator has no input connections. Please connect it to an ingest_source operator."
    ACL_MULTIPLE_PARENTS = (
        "ACL operator should have only one parent. Found {parent_count} parents. In flows, only one ingest is allowed."
    )
    ACL_OPERATOR_MISPLACED = (
        "ACL operator must be placed immediately after an ingest operator. Current predecessor: {predecessor_operator}"
    )
    ACL_INVALID_PROVIDER = "ACL operator requires ingest_source to use 'sharepoint' provider, but found '{provider}'"
    MULTIPLE_ACL_OPERATORS = "Multiple ACL operators detected in the flow. Only one ACL operator is allowed per flow."

    # Storage Output Operator errors
    STORAGE_OUTPUT_REQUIRES_INGEST_SOURCE = (
        "storage_output: mode '{mode}' requires an upstream 'ingest_source' operator"
    )

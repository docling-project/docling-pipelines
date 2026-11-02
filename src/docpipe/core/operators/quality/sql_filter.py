from enum import Enum
from typing import Any

import duckdb
import pyarrow as pa
import re2 as re

from docpipe.core.constants.constants import (
    AttributeDataTypes,
    DocpipeConstants,
    ExecutionStatus,
    Metrics,
)
from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.core.operators.abstract_operator import AbstractOperator, OperatorCategory
from docpipe.core.operators.operator_utils import OperatorUtils
from docpipe.exceptions.docpipe_exceptions import DocpipeException
from docpipe.exceptions.error_codes import ErrorCode
from docpipe.exceptions.error_messages import ValidationCodeMessages, ValidationMessage
from docpipe.utils.infrastructure.logging import get_logger

logger = get_logger()


""" AST Key holds the list of filter criteria (in SQL WHERE clause format)"""

""" Key holds the logical operators that joins filter criteria (AND or OR)"""

""" AST Key holds the list of features to drop after filtering"""
FILTER_LOGICAL_OPERATOR_AND: str = "AND"
FILTER_LOGICAL_OPERATOR_OR: str = "OR"
VALID_FILTER_LOGICAL_OPERATORS: list[str] = [
    FILTER_LOGICAL_OPERATOR_AND,
    FILTER_LOGICAL_OPERATOR_OR,
]

# defaults
FILTER_CRITERIA_DEFAULT: list[Any] = []
""" The default list of filter criteria (in SQL WHERE clause format)"""
FILTER_LOGICAL_OPERATOR_DEFAULT: str = FILTER_LOGICAL_OPERATOR_AND
FILTER_FEATURES_TO_DROP_DEFAULT: list[Any] = []
""" The default list of features to drop"""

IS_NULL: str = "IS NULL"
IS_NOT_NULL: str = "IS NOT NULL"


class Mode(Enum):
    """Mode."""

    COLUMNS_TO_DROP = "features to drop"
    FILTER_CRITERIA_JSON = "filter criteria (JSON)"
    FILTER_CRITERIA_LIST = "filter criteria (list)"


class SQLFilterOperator(AbstractOperator):
    """
    Implements filtering - select from a pyarrow.Table a set of rows that
    satisfy a set of filtering criteria.

    Protected columns (cannot be removed via features_to_drop):
        - id
        - content
        - pages_processed
        - allowed_users  (required for OpenSearch ACL queries)
        - chunked_content  (required by EmbeddingsOperator and VectorDBOperator)
    """

    short_name: str = OperatorConstants.Operators.SQL_FILTER
    category: OperatorCategory = OperatorCategory.Quality
    owner = DocpipeConstants.OWNER_DOCPIPE

    def __init__(self, config: dict[str, Any]) -> None:
        """
        Initialize based on the dictionary of configuration information.
        This is generally called with configuration parsed from the CLI arguments defined
        by the companion runtime, FilterTransformRuntime.  If running from the Ray orchestrator,
        these will be provided by that class with help from the RayMutatingDriver.
        """

        super().__init__(config)
        self.filter_criteria: list[str] = (
            config.get(OperatorConstants.Filtering.FILTER_CRITERIA_LIST, FILTER_CRITERIA_DEFAULT) or []
        )
        self.logical_operator: str = config.get(
            OperatorConstants.Filtering.FILTER_LOGICAL_OPERATOR_KEY,
            FILTER_LOGICAL_OPERATOR_DEFAULT,
        )
        self.features_to_drop: list[str] = config.get(
            OperatorConstants.Filtering.FILTER_FEATURES_TO_DROP_KEY,
            FILTER_FEATURES_TO_DROP_DEFAULT,
        )
        self.columns_to_drop: list[str] = self.features_to_drop
        self.filter_criteria_json: dict[str, Any] | None = config.get(OperatorConstants.Filtering.FILTER_CRITERIA_JSON)
        self.duckdb_memory_limit: str = config.get(OperatorConstants.Filtering.DUCKDB_MEMORY_LIMIT, "512MB")
        self.duckdb_threads: int = config.get(OperatorConstants.Filtering.DUCKDB_THREADS, 2)

    def validate(
        self,
        errors: list[str | ValidationMessage],
        warnings: list[str],
        available_features: list[str],
    ) -> None:
        """
        Validate operator conditions.
        """
        # Check if at least one filter criteria is provided (only validate non-parameterized fields)
        should_validate_criteria = self.should_validate_field(field_value=self.filter_criteria)
        should_validate_json = self.should_validate_field(field_value=self.filter_criteria_json)

        # Only validate if both fields are not parameterized
        if should_validate_criteria and should_validate_json:
            criteria_valid, json_valid = OperatorUtils.validate_filter_criteria(
                criteria_list=self.filter_criteria,
                criteria_json=self.filter_criteria_json,
            )

            # Warn if both are invalid/empty
            # If either field is parameterized, skip warning (it will be provided at runtime)
            if not (criteria_valid or json_valid):
                warnings.append("Filter criteria must have at least one condition.")

        # Validate features to drop
        if self.should_validate_field(field_value=self.features_to_drop):
            has_protected, protected_cols = self._has_protected_columns()
            if has_protected:
                protected_features = {
                    OperatorConstants.Misc.ID: ValidationCodeMessages.SQL_FILTER_ID_DROP_ATTEMPTED,
                    OperatorConstants.Columns.DOC_COLUMN_DEFAULT: ValidationCodeMessages.SQL_FILTER_CONTENT_DROP_ATTEMPTED,
                    OperatorConstants.Columns.PAGES_PROCESSED_COLUMN: ValidationCodeMessages.SQL_FILTER_PAGES_DROP,
                    OperatorConstants.ACL.ALLOWED_USERS_COLUMN: ValidationCodeMessages.SQL_FILTER_ALLOWED_USERS_DROP_ATTEMPTED,
                    OperatorConstants.Columns.CHUNKED_CONTENT: ValidationCodeMessages.SQL_FILTER_CHUNKED_CONTENT_DROP_ATTEMPTED,
                }
                for feature in protected_cols:
                    if feature in protected_features:
                        errors.append(
                            ValidationMessage(
                                message=protected_features[feature].value, message_code=protected_features[feature].name
                            )
                        )

        # Validate filter criteria columns - only if at least one is not parameterized
        criteria_to_validate: list[str] | dict[str, Any] | None = None
        if should_validate_json and self.filter_criteria_json:
            criteria_to_validate = self.filter_criteria_json
        elif should_validate_criteria and self.filter_criteria:
            criteria_to_validate = self.filter_criteria

        if criteria_to_validate:
            criteria_columns = extract_columns(criteria_to_validate)

            # Identify invalid features
            invalid_features = [feature for feature in criteria_columns if feature not in available_features]
            if invalid_features:
                errors.append(
                    ValidationMessage(
                        message=(
                            f"Invalid feature name(s): {', '.join(sorted(invalid_features))}. "
                            f"Please ensure the filter_criteria has features from {', '.join(available_features)}."
                        ),
                        message_code=ValidationCodeMessages.SQL_FILTER_INVALID_COLUMN.name,
                    )
                )

        # Validate features to drop columns
        if self.should_validate_field(field_value=self.features_to_drop):
            drop_column_validation = self.has_invalid_columns(
                input_table_columns_set=set(available_features),
                mode=Mode.COLUMNS_TO_DROP,
            )
            if drop_column_validation and isinstance(drop_column_validation, (set, list)):
                errors.append(
                    f"Invalid feature name in the feature drop list: {', '.join(drop_column_validation)}. Please select features from {', '.join(available_features)}"  # nosec B608 — error message, not executed SQL
                )

    def transform(self, table: pa.Table) -> tuple[list[pa.Table], dict[str, Any]]:
        """
        This implementation filters the input table using a SQL statement and
        returns the filtered table and execution stats
        :param table: input table
        :return: list of output tables and custom statistics
        """
        # Initialize metadata
        metadata: dict[str, Any] = self.create_base_metadata(total_docs_count=OperatorUtils.find_doc_count(table=table))

        try:
            filtered_table: list[pa.Table] = self._dpk_transform(table=table, metadata=metadata)
            if not metadata.get(Metrics.External.SKIPPED_DOCS_COUNT):
                metadata.update(
                    OperatorUtils.find_skipped_docs(
                        input_table=table,
                        output_table=filtered_table[0],
                        reason="Document Filtered out based on the specified filter criteria.",
                    )
                )
            return filtered_table, metadata
        except DocpipeException as e:
            # Record the error in metadata and return original table
            error_msg = str(e)
            logger.error(
                "SQL filter operation failed: %s",
                error_msg,
                extra=self.common_log_arguments,
            )
            metadata[Metrics.External.NODE_STATUS] = ExecutionStatus.FAILED.value
            metadata[OperatorConstants.Extraction.ERROR] = error_msg
            # Mark all documents as failed since filter couldn't be applied
            for idx in range(table.num_rows):
                doc_id = str(idx)
                doc_name = table["name"][idx].as_py() if "name" in table.column_names else f"doc_{idx}"
                self.record_failed_document(
                    metadata=metadata,
                    doc_id=doc_id,
                    doc_name=doc_name,
                    reason=error_msg,
                )
            return [table], metadata
        except Exception as e:
            # Handle unexpected errors
            logger.exception(
                "Unexpected error in SQL filter operation: %s",
                e,
                extra=self.common_log_arguments,
            )
            metadata[Metrics.External.NODE_STATUS] = ExecutionStatus.FAILED.value
            metadata[OperatorConstants.Extraction.ERROR] = str(e)
            # Mark all documents as failed
            for idx in range(table.num_rows):
                doc_id = str(idx)
                doc_name = table["name"][idx].as_py() if "name" in table.column_names else f"doc_{idx}"
                self.record_failed_document(
                    metadata=metadata,
                    doc_id=doc_id,
                    doc_name=doc_name,
                    reason=str(e),
                )
            return [table], metadata

    def _dpk_transform(self, table: pa.Table, metadata: dict[str, Any]) -> list[pa.Table]:
        """
        This implementation filters the input table using a SQL statement and
        returns the filtered table and execution stats
        :param table: input table
        :return: list of output tables
        """

        # move table under a different name, to avoid SQL query parsing error
        input_table: pa.Table = table
        total_docs: int = input_table.num_rows
        total_columns: int = input_table.num_columns
        total_bytes: int = input_table.nbytes
        input_table_columns_set: set[str] = set(input_table.column_names)

        # initialize the metadata dictionary
        metadata[Metrics.External.DOCS_BEFORE_FILTER] = total_docs
        metadata[Metrics.External.COLUMNS_BEFORE_FILTER] = total_columns
        metadata[Metrics.External.BYTES_BEFORE_FILTER] = total_bytes

        # initialize the SQL statement used for filtering
        sql_statement: str = "SELECT * FROM input_table"
        stats_sql: str = ""
        needs_filter: bool = False

        if self.filter_criteria_json:
            if self.has_invalid_columns(
                input_table_columns_set=input_table_columns_set,
                metadata=metadata,
                mode=Mode.FILTER_CRITERIA_JSON,
            ):
                return [table]

            sql_where: str = json_to_sql_where(self.filter_criteria_json)
            sql_statement = sql_statement + " " + sql_where
            needs_filter = True

        elif len(self.filter_criteria) > 0:
            if self.has_invalid_columns(
                input_table_columns_set=input_table_columns_set,
                metadata=metadata,
                mode=Mode.FILTER_CRITERIA_LIST,
            ):
                return [table]

            # populate per-criterion stats in a single query using conditional aggregation
            case_exprs: list[str] = [
                f"COUNT(CASE WHEN ({c}) THEN 1 END) AS _keep_{i}" for i, c in enumerate(self.filter_criteria)
            ]
            stats_sql = f"SELECT {', '.join(case_exprs)} FROM input_table"  # nosec B608 — criteria validated before use

            # use filtering criteria to build the SQL query for filtering
            filter_clauses: list[str] = [f"({x})" for x in self.filter_criteria]
            where_clause: str = f" {self.logical_operator} ".join(filter_clauses)
            sql_statement = f"{sql_statement} WHERE {where_clause}"
            needs_filter = True

        if needs_filter:
            # filter using SQL statement
            duckdb_binding_errors = (
                duckdb.BinderException,
                duckdb.ConversionException,
                duckdb.CatalogException,
            )

            with duckdb.connect(
                config={"memory_limit": self.duckdb_memory_limit, "threads": self.duckdb_threads}
            ) as con:
                try:
                    # collect per-criterion stats before the main filter (filter_criteria_list path only)
                    if len(self.filter_criteria) > 0 and not self.filter_criteria_json:
                        stats_row = con.execute(stats_sql).fetchone()
                        for i, criterion in enumerate(self.filter_criteria):
                            keep_count: int = stats_row[i] if stats_row else 0  # type: ignore[index]
                            docs_filtered: int = total_docs - keep_count
                            metadata[f"docs_filtered_out_by '{criterion}'"] = docs_filtered

                    filtered_table: pa.Table = con.execute(sql_statement).arrow()
                except duckdb_binding_errors as ex:  # type: ignore[misc]
                    binding_err_msg: str = f"Filter condition is invalid due to mismatched data types. (e.g. comparing text to numbers). Please review the filter expression and table schema. {ex}"
                    raise DocpipeException(
                        message=binding_err_msg,
                        status_code=400,
                        error_code=ErrorCode.SQL_FILTER_ERROR,
                    ) from ex
                except Exception as ex:
                    unexpected_err_msg: str = f"An unexpected error occurred. Please review your filter logic. {ex}"
                    raise DocpipeException(
                        message=unexpected_err_msg,
                        status_code=400,
                        error_code=ErrorCode.SQL_FILTER_ERROR,
                    ) from ex
        else:
            filtered_table = table

        # drop any columns requested from the final result
        if len(self.columns_to_drop) > 0:
            if self.has_invalid_columns(
                metadata=metadata,
                input_table_columns_set=input_table_columns_set,
                mode=Mode.COLUMNS_TO_DROP,
            ):
                # Update metadata to reflect unchanged table on validation failure
                self._set_filter_metadata(metadata=metadata, table=filtered_table)
                return [filtered_table]

            # Runtime check for protected columns - always enforce regardless of validation settings
            has_protected, protected_cols = self._has_protected_columns()
            if has_protected:
                error_msg = f"Cannot drop protected columns: {', '.join(protected_cols)}. These columns are required for downstream operators."
                logger.error(error_msg, extra=self.common_log_arguments)
                raise DocpipeException(
                    message=error_msg,
                    status_code=400,
                    error_code=ErrorCode.SQL_FILTER_ERROR,
                )

            filtered_table_cols_dropped: pa.Table = filtered_table.drop_columns(self.columns_to_drop)
        else:
            filtered_table_cols_dropped = filtered_table

        # add global filter stats to metadata
        self._set_filter_metadata(metadata=metadata, table=filtered_table_cols_dropped)

        return [filtered_table_cols_dropped]

    def _set_filter_metadata(
        self,
        *,
        metadata: dict[str, Any],
        table: pa.Table,
    ) -> None:
        """
        Set common filter metadata for the given table.

        Parameters:
            metadata: Metadata dictionary to update
            table: PyArrow table to extract metrics from
        """
        metadata[Metrics.External.DOCS_AFTER_FILTER] = table.num_rows
        metadata[Metrics.External.COLUMNS_AFTER_FILTER] = table.num_columns
        metadata[Metrics.External.BYTES_AFTER_FILTER] = table.nbytes
        metadata[Metrics.External.PROCESSED_DOCS] = OperatorUtils.find_doc_count(table=table)

    def _has_protected_columns(self) -> tuple[bool, list[str]]:
        """
        Check if any protected columns are in the features_to_drop list.
        Protected columns cannot be dropped as they are required by downstream operators:
            - id, content, pages_processed (core pipeline columns)
            - allowed_users (required for OpenSearch ACL queries)
            - chunked_content (required by EmbeddingsOperator and VectorDBOperator)

        Returns:
            tuple: (has_protected, list_of_protected_columns)
        """
        protected_columns_to_drop = [
            col for col in self.features_to_drop if col in OperatorConstants.PROTECTED_PIPELINE_COLUMNS
        ]
        return (len(protected_columns_to_drop) > 0, protected_columns_to_drop)

    def has_invalid_columns(
        self,
        input_table_columns_set: set[str],
        mode: Mode,
        metadata: dict[str, Any] | None = None,
    ) -> bool | list[str]:
        """Has invalid columns."""
        filter_column_set: set[str]
        if mode == Mode.COLUMNS_TO_DROP:
            filter_column_set = set(self.columns_to_drop)
        elif mode == Mode.FILTER_CRITERIA_JSON:
            filter_column_set = extract_columns(self.filter_criteria_json) if self.filter_criteria_json else set()
        else:
            filter_column_set = extract_columns(self.filter_criteria)

        invalid_columns: set[str] = filter_column_set - input_table_columns_set

        if invalid_columns:
            logger.error(
                "Invalid features found in %s - %s. %s should use only the available features.",
                mode,
                ", ".join(invalid_columns),
                mode,
            )
            if metadata is not None:
                metadata[Metrics.External.PROCESSED_DOCS] = 0
                metadata[Metrics.External.NODE_STATUS] = ExecutionStatus.COMPLETED_WITH_WARNINGS.value
                return True
            return list(invalid_columns)
        return False

    @staticmethod
    def get_metadata() -> dict[str, Any]:
        """Get metadata."""
        return {
            OperatorConstants.Misc.SDK: True,
            OperatorConstants.Misc.IS_OPERATOR_AVAILABLE: SQLFilterOperator.is_available(),
            OperatorConstants.Misc.CATEGORY: SQLFilterOperator.category.value,
            OperatorConstants.Misc.LABEL: "Annotation Filter",
            OperatorConstants.Config.DESCRIPTION: "Filter or drop rows from the pipeline using SQL-style WHERE clause conditions.",
            OperatorConstants.Config.ATTRIBUTES: {
                OperatorConstants.Filtering.FILTER_CRITERIA_LIST: {
                    OperatorConstants.Misc.NAME: "Filter Criteria (List)",
                    OperatorConstants.Config.DESCRIPTION: "Add different Filter criteria as part of the WHERE clause",
                    OperatorConstants.Config.DEFAULT: FILTER_CRITERIA_DEFAULT,
                    OperatorConstants.Config.REQUIRED: False,
                    OperatorConstants.Misc.TYPE: AttributeDataTypes.LIST,
                },
                OperatorConstants.Filtering.FILTER_CRITERIA_JSON: {
                    OperatorConstants.Misc.NAME: "Filter Criteria (String/Json)",
                    OperatorConstants.Config.DESCRIPTION: "Add different Filter criteria as part of the WHERE clause in JSON format",
                    OperatorConstants.Config.DEFAULT: None,
                    OperatorConstants.Config.REQUIRED: False,
                    OperatorConstants.Misc.TYPE: AttributeDataTypes.JSON,
                },
                OperatorConstants.Filtering.FILTER_LOGICAL_OPERATOR_KEY: {
                    OperatorConstants.Misc.NAME: "Logical Operator",
                    OperatorConstants.Config.DESCRIPTION: "Select the logical Operator for WHERE clause: OR or AND",
                    OperatorConstants.Config.DEFAULT: FILTER_LOGICAL_OPERATOR_DEFAULT,
                    OperatorConstants.Config.REQUIRED: False,
                    OperatorConstants.Config.VALID_VALUES: VALID_FILTER_LOGICAL_OPERATORS,
                    OperatorConstants.Misc.TYPE: AttributeDataTypes.STRING,
                },
                OperatorConstants.Filtering.FILTER_FEATURES_TO_DROP_KEY: {
                    OperatorConstants.Misc.NAME: "Features to drop",
                    OperatorConstants.Config.DESCRIPTION: "Declare the features which need to be dropped",
                    OperatorConstants.Config.DEFAULT: FILTER_FEATURES_TO_DROP_DEFAULT,
                    OperatorConstants.Config.REQUIRED: False,
                    OperatorConstants.Misc.TYPE: AttributeDataTypes.LIST,
                },
            },
        }


_OPERATOR_MAP: dict[str, str] = {
    "=": "=",
    "==": "=",
    "!=": "!=",
    "<>": "<>",
    ">": ">",
    "<": "<",
    ">=": ">=",
    "<=": "<=",
    "in": "IN",
    "not in": "NOT IN",
    "like": "LIKE",
    "not like": "NOT LIKE",
    "is null": IS_NULL,
    "is not null": IS_NOT_NULL,
    "between": "BETWEEN",
}


def convert_operator(op: str) -> str:
    """Convert JSON operator to SQL operator."""
    if not isinstance(op, str):
        raise DocpipeException(
            message=f"Operator must be a string, got {type(op).__name__}",
            status_code=400,
            error_code=ErrorCode.SQL_FILTER_ERROR,
        )
    try:
        return _OPERATOR_MAP[op.lower()]
    except KeyError as e:
        raise DocpipeException(
            message=f"Unknown operator: {op}",
            status_code=400,
            error_code=ErrorCode.SQL_FILTER_ERROR,
        ) from e


def format_value(value: Any) -> str:
    """Format value for SQL based on its type."""
    if value is None:
        return "NULL"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        return f"({', '.join(format_value(v) for v in value)})"
    if isinstance(value, str):
        try:
            # Try to parse as number
            return str(float(value)) if "." in value else str(int(value))
        except ValueError:
            escaped_str: str = value.replace("'", "''")
            return f"'{escaped_str}'"
    else:
        escaped_other: str = str(value).replace("'", "''")
        return f"'{escaped_other}'"


def process_condition(condition: dict[str, Any]) -> str:
    """Process a single condition."""

    required_keys: list[str] = ["variable", "operator"]
    if not all(key in condition for key in required_keys):
        raise DocpipeException(
            message="Condition must contain 'variable' and 'operator'",
            status_code=400,
            error_code=ErrorCode.SQL_FILTER_ERROR,
        )

    variable: str = condition["variable"]
    operator: str = convert_operator(condition["operator"])
    value_raw: Any = condition.get("value")

    # Handle special cases
    if operator in [IS_NULL, IS_NOT_NULL]:
        return f"{variable} {operator}"

    if operator == "BETWEEN":
        if isinstance(value_raw, list) and len(value_raw) == 2:
            a, b = value_raw
        elif isinstance(value_raw, str):
            parts: list[str] = [v.strip() for v in value_raw.split(",")]
            if len(parts) != 2:
                raise DocpipeException(
                    message=f"BETWEEN operator requires 2 values, got: '{value_raw}'",
                    status_code=400,
                    error_code=ErrorCode.SQL_FILTER_ERROR,
                )
            a, b = parts
        else:
            raise DocpipeException(
                message=f"BETWEEN operator requires a list or comma-separated string of 2 values, got: {value_raw}",
                status_code=400,
                error_code=ErrorCode.SQL_FILTER_ERROR,
            )

        lower: str = format_value(a)
        upper: str = format_value(b)
        return f"{variable} {operator} {lower} AND {upper}"

    if operator in ["IN", "NOT IN"]:
        value_list: list[Any]
        if isinstance(value_raw, str):
            value_list = [v.strip() for v in value_raw.split(",")]
        elif isinstance(value_raw, list):
            value_list = value_raw
        else:
            raise DocpipeException(
                message=f"{operator} operator requires a list or comma-separated string, got: {value_raw}",
                status_code=400,
                error_code=ErrorCode.SQL_FILTER_ERROR,
            )
        formatted_value: str = format_value(value_list)
        return f"{variable} {operator} {formatted_value}"

    # All other operators
    default_formatted_value: str = format_value(value_raw)
    return f"{variable} {operator} {default_formatted_value}"


def process_criteria_group(group: dict[str, Any]) -> str:
    """Process a group of criteria connected by a logical operator."""
    if not isinstance(group, dict):
        raise DocpipeException(
            message="Group must be a dictionary",
            status_code=400,
            error_code=ErrorCode.SQL_FILTER_ERROR,
        )

    # Check if it's a leaf condition
    if "criteria_list" not in group:
        return process_condition(group)

    logical_op: str = group.get("logical_operator", "AND").upper()
    criteria_list: list[Any] = group["criteria_list"]

    if not isinstance(criteria_list, list):
        raise DocpipeException(
            message="criteria_list must be a list",
            status_code=400,
            error_code=ErrorCode.SQL_FILTER_ERROR,
        )
    if not criteria_list:
        return ""

    processed_criteria: list[str] = []
    for criterion in criteria_list:
        if isinstance(criterion, dict) and "criteria_list" in criterion:
            # Nested group
            processed_group: str = process_criteria_group(criterion)
            if processed_group:
                processed_criteria.append(f"({processed_group})")
        else:
            # Leaf condition
            try:
                processed_condition: str = process_condition(criterion)
                if processed_condition:
                    processed_criteria.append(processed_condition)
            except ValueError as e:
                raise DocpipeException(
                    message=f"Skipping invalid condition: {criterion}. {e}",
                    status_code=400,
                    error_code=ErrorCode.SQL_FILTER_ERROR,
                ) from e

    if not processed_criteria:
        return ""

    return f" {logical_op} ".join(processed_criteria)


def json_to_sql_where(where_json: dict[str, Any] | None) -> str:
    """Convert JSON representation to SQL WHERE clause."""
    if not where_json or not isinstance(where_json, dict):
        return ""

    try:
        where_clause: str = process_criteria_group(where_json)
    except (ValueError, TypeError) as e:
        raise DocpipeException(
            message=f"Error processing WHERE clause: {e}",
            status_code=400,
            error_code=ErrorCode.SQL_FILTER_ERROR,
        ) from e

    if not where_clause.strip():
        return ""

    return f"WHERE {where_clause}"


def extract_columns(filter_input: dict[str, Any] | list[str]) -> set[str]:
    """
    Extract column names from either JSON criteria (dict) or list of filter strings.

    Args:
        filter_input: Either a dict (JSON criteria) or a list of strings.

    Returns:
        A set of column names.
    """
    if isinstance(filter_input, dict):
        return extract_columns_json(filter_input)
    if isinstance(filter_input, list) and all(isinstance(x, str) for x in filter_input):
        return extract_columns_list(filter_input)
    raise DocpipeException(
        message=f"Unsupported filter_input type: {type(filter_input).__name__}",
        status_code=400,
    )


def extract_columns_json(condition_or_group: dict[str, Any]) -> set[str]:
    """Extract all column names from condition(s)."""
    columns: set[str] = set()
    if "variable" in condition_or_group and "operator" in condition_or_group:
        columns.add(condition_or_group["variable"])
    elif "criteria_list" in condition_or_group:
        for criterion in condition_or_group["criteria_list"]:
            if isinstance(criterion, dict):
                columns.update(extract_columns_json(criterion))
    return columns


def extract_columns_list(filter_criteria: list[str]) -> set[str]:
    """Extract column names from filter criteria strings."""

    # Pattern to split expressions on AND / OR
    logical_split_pattern = re.compile(r"(?i)\s+(AND|OR)\s+")

    # Pattern to match a column name at the start of a condition
    column_pattern = re.compile(r"(?i)^\s*([\w.]+)\s*(?:IN|NOT IN|LIKE|IS NULL|IS NOT NULL|=|<>|!=|<=|>=|<|>)")

    columns: set[str] = set()
    for criterion in filter_criteria:
        # Split complex condition into individual expressions
        expressions: list[str] = logical_split_pattern.split(criterion)
        for expr in expressions:
            if expr.upper() in {"AND", "OR"}:
                continue
            match = column_pattern.match(expr.strip())
            if match:
                columns.add(match.group(1))

    return columns

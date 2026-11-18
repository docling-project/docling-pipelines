"""Branching operator that splits a document table into multiple sub-flows."""

from typing import Any

import pyarrow as pa
import re2 as re
import sqlglot
from sqlglot import expressions as exp

from docpipe.core.constants.constants import (
    AttributeDataTypes,
    DocpipeConstants,
    MemoryLogPhases,
    Metrics,
)
from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.core.operators.abstract_operator import AbstractOperator, OperatorCategory
from docpipe.core.operators.operator_utils import OperatorUtils
from docpipe.core.operators.quality.sql_filter import (
    SQLFilterOperator,
    extract_columns,
)
from docpipe.utils.infrastructure.logging import get_logger
from docpipe.utils.infrastructure.performance import log_memory_usage

logger = get_logger()


class BranchingOperator(AbstractOperator):
    """
    BranchingOperator class for branching data based on specified conditions.
    This class inherits from AbstractOperator and provides functionality to branch data
    based on given conditions and logical operators.
    """

    short_name: str = OperatorConstants.Operators.BRANCHING
    category: OperatorCategory = OperatorCategory.Functional
    owner = DocpipeConstants.OWNER_DOCPIPE

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self._config: dict[str, Any] = config
        self.branch_criteria: list[dict[str, Any]] = config.get("branches", [])

    def _validate_branch(
        self,
        *,
        branch: dict[str, Any],
        existing_link_names: set[str],
        invalid_features: set[str],
        available_features: list[str],
        errors: list[str],
        warnings: list[str],
        is_unconditional: bool,
    ) -> None:
        """Validate a single branch entry and update errors/warnings/invalid_features in-place."""
        logical_op: str | None = branch.get("logical_operator")
        criteria_list: list[str] = branch.get(OperatorConstants.Filtering.FILTER_CRITERIA_LIST, [])
        criteria_json: dict[str, Any] | None = branch.get(OperatorConstants.Filtering.FILTER_CRITERIA_JSON)
        link_name: str | None = branch.get(OperatorConstants.Misc.LINK_NAME)

        OperatorUtils.validate_link_name(
            link_name=link_name,
            existing_link_names=existing_link_names,
            errors=errors,
        )

        if logical_op and logical_op not in ["AND", "OR"]:
            errors.append(f"Invalid logical operator '{logical_op}' in branch. Use 'AND' or 'OR'.")

        if is_unconditional:
            return

        criteria_valid, json_valid = OperatorUtils.validate_filter_criteria(
            criteria_list=criteria_list, criteria_json=criteria_json
        )
        if not (criteria_valid or json_valid):
            warnings.append(
                f"Filter criteria must have at least one condition for conditional branch '{link_name or 'unnamed'}'"
            )

        if criteria_json:
            criteria_columns: set[str] = extract_columns(criteria_json)
            invalid_features.update(criteria_columns - set(available_features))
        elif criteria_list:
            for criteria in criteria_list:
                if criteria and criteria.strip():
                    self.validate_expression(
                        expr=criteria,
                        available_features=available_features,
                        errors=errors,
                    )

        if not branch.get(OperatorConstants.Misc.LINK_ID):
            errors.append("Branch Id is missing in the branch parameters.")

    def validate(self, errors: list[str], warnings: list[str], available_features: list[str]) -> None:
        """Validate."""
        if not self.should_validate_field(field_value=self.branch_criteria):
            return

        if not self.branch_criteria:
            errors.append("branch_criteria parameter is missing")
            return

        if len(self.branch_criteria) == 1:
            warnings.append("Branching Operator has only one branch. Consider using a Filter Operator instead.")

        # Check if this is unconditional branching (all branches have empty criteria_json['criteria_list'])
        is_unconditional_branching: bool = all(
            isinstance(branch.get(OperatorConstants.Filtering.FILTER_CRITERIA_JSON), dict)
            and not branch.get(OperatorConstants.Filtering.FILTER_CRITERIA_JSON, {}).get("criteria_list", [])
            for branch in self.branch_criteria
        )

        invalid_features: set[str] = set()
        existing_link_names: set[str] = set()
        for branch in self.branch_criteria:
            self._validate_branch(
                branch=branch,
                existing_link_names=existing_link_names,
                invalid_features=invalid_features,
                available_features=available_features,
                errors=errors,
                warnings=warnings,
                is_unconditional=is_unconditional_branching,
            )

        if invalid_features:
            errors.append(
                f"Invalid features in filter criteria - {', '.join(invalid_features)}. Filter criteria should use only the available features: {', '.join(available_features)}."
            )

    @staticmethod
    def get_metadata() -> dict[str, Any]:
        """Get metadata."""
        return {
            OperatorConstants.Misc.SDK: True,
            OperatorConstants.Misc.CATEGORY: BranchingOperator.category.value,
            OperatorConstants.Misc.IS_OPERATOR_AVAILABLE: BranchingOperator.is_available(),
            OperatorConstants.Misc.LABEL: "Branching Operator",
            OperatorConstants.Config.DESCRIPTION: "Split pipeline data into multiple branches based on filter conditions.",
            OperatorConstants.Config.ATTRIBUTES: {
                "branch_criteria": {
                    OperatorConstants.Misc.NAME: "Branches",
                    OperatorConstants.Config.DESCRIPTION: (
                        "A list of branch configurations. Each branch includes a set of filter conditions, "
                        "a logical operator (AND/OR) to combine them, and features to drop from the resulting table."
                    ),
                    OperatorConstants.Config.REQUIRED: True,
                    OperatorConstants.Misc.TYPE: AttributeDataTypes.LIST,
                    OperatorConstants.Config.ITEMS: {
                        OperatorConstants.Misc.TYPE: AttributeDataTypes.JSON,
                        OperatorConstants.Config.PROPERTIES: {
                            OperatorConstants.Misc.LINK_ID: {
                                OperatorConstants.Misc.NAME: "Branch ID",
                                OperatorConstants.Config.DESCRIPTION: "Unique identifier for this branch. Referenced by MergeOperator input_links.",
                                OperatorConstants.Config.REQUIRED: True,
                                OperatorConstants.Misc.TYPE: AttributeDataTypes.STRING,
                            },
                            OperatorConstants.Misc.LINK_NAME: {
                                OperatorConstants.Misc.NAME: "Branch Name",
                                OperatorConstants.Config.DESCRIPTION: "Human-readable label for this branch.",
                                OperatorConstants.Config.REQUIRED: False,
                                OperatorConstants.Misc.TYPE: AttributeDataTypes.STRING,
                            },
                            OperatorConstants.Filtering.FILTER_CRITERIA_LIST: {
                                OperatorConstants.Misc.NAME: "Criteria List",
                                OperatorConstants.Config.DESCRIPTION: "SQL-like filter expressions (e.g. \"lang_name = 'en'\"). Omit for an unconditional branch.",
                                OperatorConstants.Config.REQUIRED: False,
                                OperatorConstants.Misc.TYPE: AttributeDataTypes.LIST,
                            },
                            OperatorConstants.Filtering.FILTER_CRITERIA_JSON: {
                                OperatorConstants.Misc.NAME: "Criteria JSON",
                                OperatorConstants.Config.DESCRIPTION: "Structured filter criteria object (alternative to criteria_list).",
                                OperatorConstants.Config.REQUIRED: False,
                                OperatorConstants.Misc.TYPE: AttributeDataTypes.JSON,
                            },
                            OperatorConstants.Filtering.FILTER_LOGICAL_OPERATOR_KEY: {
                                OperatorConstants.Misc.NAME: "Logical Operator",
                                OperatorConstants.Config.DESCRIPTION: "How to combine multiple criteria: AND or OR.",
                                OperatorConstants.Config.REQUIRED: False,
                                OperatorConstants.Config.DEFAULT: "AND",
                                OperatorConstants.Config.VALID_VALUES: ["AND", "OR"],
                                OperatorConstants.Misc.TYPE: AttributeDataTypes.STRING,
                            },
                        },
                    },
                }
            },
        }

    def _update_metadata(
        self,
        idx: int,
        filtered_table: pa.Table,
        metadata: dict[str, Any],
        total_docs: int,
        skipped_docs: list[dict[str, Any]],
        failed_docs: list[dict[str, Any]],
    ) -> None:
        branch_id: str | None = self.branch_criteria[idx].get(OperatorConstants.Misc.LINK_ID)
        metadata["branches"][branch_id] = {
            "result_index": idx,
            "processed_docs": filtered_table.num_rows,
            "docs_filtered": total_docs - filtered_table.num_rows,
            "skipped_docs_count": total_docs - filtered_table.num_rows,
            "failed_docs_count": len(failed_docs),
        }
        metadata[Metrics.External.SKIPPED_DOCS] = skipped_docs
        metadata[Metrics.External.FAILED_DOCS] = failed_docs

    def runner(self, table: pa.Table) -> tuple[list[pa.Table], dict[str, Any]]:
        """Runner."""
        log_memory_usage(
            operator_name=self.name,
            phase=MemoryLogPhases.TRANSFORM_COMPLETED,
            table=table,
            extra=self.common_log_arguments,
            logger=logger,
        )
        total_docs: int = table.num_rows

        metadata: dict[str, Any] = self.create_base_metadata(total_docs_count=OperatorUtils.find_doc_count(table=table))
        metadata["branches"] = {}

        filtered_tables: list[pa.Table] = []
        skipped_docs: list[dict[str, Any]] = []
        failed_docs: list[dict[str, Any]] = []
        processed_doc_ids: set[str] = set()

        for idx, branch in enumerate(self.branch_criteria):
            if not branch.get(OperatorConstants.Filtering.FILTER_CRITERIA_LIST) and not branch.get(
                OperatorConstants.Filtering.FILTER_CRITERIA_JSON
            ):
                filtered_tables.append(pa.Table.from_batches(table.to_batches()))
                # Track unique document IDs for unconditional branching
                if OperatorConstants.Misc.ID in table.column_names:
                    doc_ids: list[str] = table.column(OperatorConstants.Misc.ID).to_pylist()
                    processed_doc_ids.update(doc_ids)
                self._update_metadata(
                    idx=idx,
                    filtered_table=table,
                    metadata=metadata,
                    total_docs=total_docs,
                    skipped_docs=skipped_docs,
                    failed_docs=failed_docs,
                )
                continue

            config: dict[str, Any] = {
                OperatorConstants.Filtering.FILTER_CRITERIA_LIST: branch.get(
                    OperatorConstants.Filtering.FILTER_CRITERIA_LIST
                ),
                OperatorConstants.Filtering.FILTER_LOGICAL_OPERATOR_KEY: branch.get(
                    OperatorConstants.Filtering.FILTER_LOGICAL_OPERATOR_KEY
                ),
                OperatorConstants.Filtering.FILTER_CRITERIA_JSON: branch.get(
                    OperatorConstants.Filtering.FILTER_CRITERIA_JSON
                ),
            }
            filter_operator: Any = SQLFilterOperator(config=config)

            branch_tables: list[pa.Table]
            metadata_filter_transform: dict[str, Any]
            branch_tables, metadata_filter_transform = filter_operator.transform(table)
            filtered_table: pa.Table = branch_tables[0]

            # Track unique document IDs for conditional branching
            if OperatorConstants.Misc.ID in filtered_table.column_names:
                doc_ids = filtered_table.column(OperatorConstants.Misc.ID).to_pylist()
                processed_doc_ids.update(doc_ids)

            skipped_docs = self.get_skipped_doc(skipped_docs, metadata_filter_transform, idx=idx)
            failed_docs = self.get_failed_doc(failed_docs, metadata_filter_transform, idx=idx)

            self._update_metadata(
                idx=idx,
                filtered_table=filtered_table,
                metadata=metadata,
                total_docs=total_docs,
                skipped_docs=skipped_docs,
                failed_docs=failed_docs,
            )
            filtered_tables.append(filtered_table)

        # Update overall metadata counts
        metadata[Metrics.External.PROCESSED_DOCS] = len(processed_doc_ids)
        metadata[Metrics.External.SKIPPED_DOCS_COUNT] = len(skipped_docs)
        metadata[Metrics.External.FAILED_DOCS_COUNT] = len(failed_docs)

        log_memory_usage(
            operator_name=self.name,
            phase=MemoryLogPhases.TRANSFORM_COMPLETED,
            table=filtered_tables,
            extra=self.common_log_arguments,
            logger=logger,
        )
        return filtered_tables, metadata

    @staticmethod
    def get_skipped_doc(
        skipped_docs: list[dict[str, Any]],
        metadata_filter_transform: dict[str, Any],
        idx: int,
    ) -> list[dict[str, Any]]:
        """Get skipped doc."""
        metadata_skipped: list[dict[str, Any]] = metadata_filter_transform.get(Metrics.External.SKIPPED_DOCS, [])

        if not skipped_docs:
            return metadata_skipped if (metadata_skipped and idx == 0) else []

        if not metadata_skipped:
            return []

        metadata_ids: set[str] = {doc["id"] for doc in metadata_skipped}
        return [doc for doc in skipped_docs if doc["id"] in metadata_ids]

    @staticmethod
    def get_failed_doc(
        failed_docs: list[dict[str, Any]],
        metadata_filter_transform: dict[str, Any],
        idx: int,
    ) -> list[dict[str, Any]]:
        """Get failed doc."""
        metadata_failed: list[dict[str, Any]] = metadata_filter_transform.get(Metrics.External.FAILED_DOCS, [])

        if not failed_docs:
            return metadata_failed if (metadata_failed and idx == 0) else []

        if not metadata_failed:
            return []

        metadata_ids: set[str] = {doc["id"] for doc in metadata_failed}
        return [doc for doc in failed_docs if doc["id"] in metadata_ids]

    def transform(self, table: pa.Table, file_name: str | None = None) -> tuple[list[pa.Table], dict[str, Any]]:
        """Transform."""
        return self.runner(table=table)

    def validate_expression(self, *, expr: str, available_features: list[str], errors: list[str]) -> None:
        """Validate expression."""
        is_valid: bool
        columns: list[str]
        is_valid, columns = self.analyze_where_clause(clause_str=expr)
        invalid_columns: set[str] = set(columns) - set(available_features)
        if invalid_columns:
            errors.append(
                f"Invalid branching criteria expression: {expr}, invalid features found: {invalid_columns}, Please use valid features in criteria expression"
            )
        elif not is_valid:
            errors.append(f"Invalid branching criteria expression: {expr}, Please use valid criteria expression")

    def analyze_where_clause(self, *, clause_str: str) -> tuple[bool, list[str]]:
        """Analyze where clause."""
        clause_str = clause_str.strip()
        if not clause_str:
            return False, []
        if ";" in clause_str:
            return False, []

        if re.search(r"\w%\w", clause_str):
            return False, []

        sql: str = f"SELECT * FROM dummy_table WHERE {clause_str}"  # nosec B608 - not executed, parsed by sqlglot for AST extraction only
        try:
            # The statement always has a WHERE clause; a clause that cannot be parsed raises
            where: Any = sqlglot.parse_one(sql).find(exp.Where)
            columns: list[str] = []

            for col in where.find_all(exp.Column):
                # col.name strips table qualifiers automatically
                columns.append(col.name)
            # Remove duplicates while preserving order
            unique_cols: list[str] = []
            for c in columns:
                if c not in unique_cols and self._is_valid_column_name(c):
                    unique_cols.append(c)
            return True, unique_cols
        except Exception as e:
            logger.error("Error while parsing sql statement: %s", e)
            return False, []

    def _is_valid_column_name(self, column_name: str) -> bool:
        """
        **STRICT VALIDATION**: Validate column name format

        Args:
            column_name (str): Column name to validate

        Returns:
            bool: True if valid column name format
        """
        if not column_name or len(column_name) > 128:  # Max column name length
            return False

        # Allow alphanumeric, underscore, and dot for table.column format
        # Must start with letter or underscore
        pattern: str = r"^\w+(\.\w+)?$"

        return bool(re.match(pattern, column_name))

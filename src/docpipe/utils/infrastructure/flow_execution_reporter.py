"""Flow execution reporter for clean, user-friendly console output.

This module provides reporting for flow execution using the logging system
at INFO level. Users can control visibility via DS_LOG_LEVEL environment variable.
"""

from datetime import UTC, datetime
from typing import Any, ClassVar

from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.core.job_management.domain.models.job_stats import JobStats
from docpipe.core.job_management.domain.models.node_stats import NodeStats
from docpipe.utils.infrastructure.logging import get_logger

logger = get_logger()


class FlowExecutionReporter:
    """Reports on flow execution progress and results to console.

    Uses logger.info() for all output, providing clean, structured summaries
    of flow execution progress and results. Output visibility is controlled
    via DS_LOG_LEVEL environment variable (INFO level or lower shows summaries).

    Uses PyArrow tables as the source of truth for schema information and
    document name lookups.
    """

    # Fields already shown in header or schema section
    _STANDARD_FIELDS: ClassVar[set[str]] = {
        "documents_in_scope",
        "processed_docs",
        "failed_docs_count",
        "skipped_docs_count",
        "node_status",
        "enrichment_columns",
        "columns_added",
        "new_columns",
        "output_columns",
        "added_columns",
    }

    def __init__(self) -> None:
        """Initialize the flow output formatter."""
        self._flow_start_time: datetime | None = None
        self._current_tables: list | None = None
        self._previous_tables: list | None = None

    def print_flow_header(self, *, flow_name: str, operator_count: int) -> None:
        """Print flow execution start banner.

        Args:
            flow_name: Name of the flow being executed
            operator_count: Number of operators in the flow
        """
        self._flow_start_time = datetime.now(tz=UTC)
        logger.info("")
        logger.info("=" * 80)
        logger.info(" FLOW: %s", flow_name)
        logger.info(" Operators: %s", operator_count)
        logger.info(" Started: %s", self._flow_start_time.strftime("%Y-%m-%d %H:%M:%S"))
        logger.info("=" * 80)
        logger.info("")

    @staticmethod
    def print_operator_start(*, step_name: str, operator_type: str) -> None:
        """Print operator execution start message.

        Args:
            step_name: Name/ID of the operator step
            operator_type: Type of operator (e.g., 'extract_operator', 'embeddings')
        """
        logger.info("[%s] Starting %s...", step_name, operator_type)

    def print_operator_summary(self, *, step_name: str, node_stats: NodeStats, tables=None) -> None:
        """Print operator execution summary card.

        Args:
            step_name: Name/ID of the operator step
            node_stats: Statistics for the completed operator
            tables: Optional list of PyArrow tables for enhanced display (e.g., document name lookup)
        """
        # Store current tables and update previous for next iteration
        self._current_tables = tables
        status = node_stats.node_status
        duration_str = self._format_duration(node_stats.time_taken)

        # Calculate counts
        completed_count = len(node_stats.docs_completed)
        failed_count = len(node_stats.failed_docs)
        skipped_count = len(node_stats.skipped_docs)

        has_failures = failed_count > 0
        log = logger.error if has_failures else logger.info

        logger.info("")
        log("=" * 80)
        log(" %s (%s)", step_name, status)
        log("=" * 80)
        log(
            " Duration: %s | Documents: %s processed, %s failed, %s skipped",
            duration_str,
            completed_count,
            failed_count,
            skipped_count,
        )

        # Print schema information if available
        if node_stats.col_names:
            self._print_schema_info(col_names=node_stats.col_names, step_name=step_name)

        # Print operator-specific metadata if available
        if node_stats.node_metadata:
            self._print_operator_metadata(node_stats.node_metadata)

        logger.info("=" * 80)
        logger.info("")

        # Save current tables as previous for next operator
        self._previous_tables = self._current_tables

    @staticmethod
    def _format_duration(time_taken: int | float | None) -> str:
        """Format duration for display.

        Args:
            time_taken: Time in seconds

        Returns:
            Formatted duration string
        """
        if not time_taken or time_taken < 1:
            return "< 1s"
        return f"{float(time_taken):.2f}s"

    @staticmethod
    def _log_column_change_header(*, total_cols: int, new_cols_count: int, removed_cols_count: int) -> None:
        """Log the Data Columns header line reflecting what changed."""
        if new_cols_count > 0 and removed_cols_count > 0:
            logger.info(
                " Data Columns: %s total (%s added, %s removed by this operator)",
                total_cols,
                new_cols_count,
                removed_cols_count,
            )
        elif new_cols_count > 0:
            logger.info(
                " Data Columns: %s total (%s added by this operator)",
                total_cols,
                new_cols_count,
            )
        elif removed_cols_count > 0:
            logger.info(
                " Data Columns: %s total (%s removed by this operator)",
                total_cols,
                removed_cols_count,
            )
        else:
            logger.info(" Data Columns: %s total", total_cols)

    def _print_schema_info(self, *, col_names: list[str], step_name: str) -> None:
        """Print schema/column information in a user-friendly format.

        Args:
            col_names: List of column names in the table
            step_name: Name of the operator step (for context)
        """
        if not col_names:
            return

        new_columns = self._get_new_columns(col_names=col_names)
        removed_columns = self._get_removed_columns(col_names=col_names)
        existing_columns = [col for col in col_names if col not in new_columns]

        total_cols = len(col_names)
        new_cols_count = len(new_columns)
        removed_cols_count = len(removed_columns)

        logger.info("")
        self._log_column_change_header(
            total_cols=total_cols, new_cols_count=new_cols_count, removed_cols_count=removed_cols_count
        )

        if new_columns:
            logger.info("   Added (%s):", new_cols_count)
            self._print_column_list(new_columns)
            if removed_columns or existing_columns:
                logger.info("")

        if removed_columns:
            logger.info("   Removed (%s):", removed_cols_count)
            self._print_column_list(removed_columns)
            if existing_columns:
                logger.info("")

        if existing_columns:
            logger.info("   Existing (%s): %s", len(existing_columns), ", ".join(existing_columns[:10]))
            if len(existing_columns) > 10:
                logger.info("      ... and %s more", len(existing_columns) - 10)

        if not new_columns and not removed_columns and not existing_columns:
            # No columns at all (shouldn't happen, but handle gracefully)
            logger.info("   (no columns)")

    def _print_column_list(self, columns: list[str], *, indent: str = "     ") -> None:
        """Print a list of columns with appropriate formatting based on count.

        Args:
            columns: List of column names to print
            indent: Indentation string for each line
        """
        col_count = len(columns)
        if col_count <= 10:
            # Simple comma-separated list
            logger.info("%s%s", indent, ", ".join(columns))
        elif col_count <= 20:
            # Wrapped list without grouping
            self._print_wrapped_columns(columns, indent=indent)
        else:
            # Many columns: group by prefix
            self._print_grouped_columns(columns, indent=indent)

    def _get_new_columns(self, *, col_names: list[str]) -> list[str]:
        """Get list of new columns added by this operator.

        Uses PyArrow tables as the source of truth for schema changes.

        Args:
            col_names: Current column names

        Returns:
            List of new column names
        """
        # Use PyArrow tables to get actual schema changes
        if self._previous_tables and self._current_tables:
            try:
                prev_cols = self._extract_column_names(self._previous_tables)
                curr_cols = self._extract_column_names(self._current_tables)

                # New columns are those in current but not in previous
                if curr_cols:
                    return list(curr_cols - prev_cols)
            except Exception:  # nosec B110 — intentional: schema diff is non-critical reporting; any comparison failure silently yields empty list
                # If table comparison fails, return empty list
                pass

        # First operator or no tables: all columns are "new"
        return col_names

    def _get_removed_columns(self, *, col_names: list[str]) -> list[str]:
        """Get list of columns removed by this operator.

        Uses PyArrow tables as the source of truth for schema changes.

        Args:
            col_names: Current column names

        Returns:
            List of removed column names
        """
        # Use PyArrow tables to get actual schema changes
        if self._previous_tables and self._current_tables:
            try:
                prev_cols = self._extract_column_names(self._previous_tables)
                curr_cols = self._extract_column_names(self._current_tables)

                # Removed columns are those in previous but not in current
                if prev_cols:
                    return list(prev_cols - curr_cols)
            except Exception:  # nosec B110 — intentional: schema diff is non-critical reporting; any comparison failure silently yields empty list
                # If table comparison fails, return empty list
                pass

        # First operator or no previous tables: no columns removed
        return []

    @staticmethod
    def _extract_column_names(tables: list) -> set[str]:
        """Extract all column names from a list of PyArrow tables.

        Args:
            tables: List of PyArrow tables

        Returns:
            Set of column names
        """
        columns = set()
        for table in tables:
            if table is not None and hasattr(table, "column_names"):
                columns.update(table.column_names)
        return columns

    @staticmethod
    def _print_wrapped_columns(columns: list[str], *, indent: str = "   ") -> None:
        """Print columns wrapped at ~70 characters per line.

        Args:
            columns: List of column names
            indent: Indentation string for each line
        """
        current_line = indent
        for i, col in enumerate(columns):
            # Check if adding this column would exceed line length
            test_line = current_line + col + (", " if i < len(columns) - 1 else "")
            if len(test_line) > 70 and current_line != indent:
                # Print current line and start new one
                logger.info(current_line.rstrip(", "))
                current_line = indent + col
            else:
                current_line += col

            if i < len(columns) - 1:
                current_line += ", "

        # Print final line
        if current_line != indent:
            logger.info(current_line)

    def _print_grouped_columns(self, columns: list[str], *, indent: str = "   ") -> None:
        """Print columns grouped by common prefix.

        Args:
            columns: List of column names
            indent: Indentation string for each line
        """
        groups = self._group_columns_by_prefix(columns)

        # If grouping resulted in empty dict, fall back to wrapped display
        if not groups:
            self._print_wrapped_columns(columns, indent=indent)
            return

        for group_name, cols in groups.items():
            logger.info("%s%s (%s):", indent, group_name, len(cols))
            self._print_wrapped_columns(cols, indent=indent + "  ")

    def _group_columns_by_prefix(self, columns: list[str]) -> dict[str, list[str]]:
        """Group columns by common prefix (before first underscore).

        Args:
            columns: List of column names

        Returns:
            Dictionary mapping group names to lists of column names
        """
        from collections import defaultdict

        prefix_groups: dict[str, list[str]] = defaultdict(list)

        for col in columns:
            parts = col.split("_", 1)  # Split on first underscore only
            if len(parts) > 1:
                prefix = parts[0]
                prefix_groups[prefix].append(col)
            else:
                prefix_groups["other"].append(col)

        # Convert to nice group names and organize
        result: dict[str, list[str]] = {}
        other_cols: list[str] = []

        for prefix, cols in sorted(prefix_groups.items()):
            if len(cols) >= 2:  # Only group if 2+ columns share prefix
                group_name = self._format_group_name(prefix)
                result[group_name] = sorted(cols)
            else:
                # Single column with this prefix goes to "Other"
                other_cols.extend(cols)

        # Add "Other" group if it has columns
        if other_cols:
            result["Other"] = sorted(other_cols)

        return result

    @staticmethod
    def _format_group_name(prefix: str) -> str:
        """Convert prefix to nice group name.

        Args:
            prefix: Column prefix

        Returns:
            Formatted group name
        """
        # Special cases for common prefixes
        special_names = {
            "ml": "ML Features",
            "lang": "Language Features",
            "acl": "ACL Features",
            "chunk": "Chunking Features",
            "classification": "Classification Features",
            "embedding": "Embedding Features",
        }

        prefix_lower = prefix.lower()
        if prefix_lower in special_names:
            return special_names[prefix_lower]

        # Default: Title case with "Features" suffix
        return f"{prefix.title()} Features"

    def _print_operator_metadata(self, metadata: dict[str, Any]) -> None:
        """Print all operator metadata with formatting.

        Args:
            metadata: Operator-specific metadata dictionary (may contain nested 'node_metadata' for old format)
        """
        if not metadata:
            return

        # Handle old format where metadata is wrapped
        actual_metadata = metadata.get("node_metadata", metadata) if "node_metadata" in metadata else metadata

        if not actual_metadata:
            return

        # Separate metadata by type for organized display
        categorized = self._categorize_metadata(actual_metadata)

        if not any(categorized.values()):
            return

        # Print sections
        logger.info("")
        self._print_numeric_fields(categorized["numeric"])
        self._print_dict_fields(categorized["dict"], has_numeric=bool(categorized["numeric"]))
        self._print_other_fields(categorized["other"])
        self._print_list_fields(categorized["list"])

    def _categorize_metadata(self, metadata: dict[str, Any]) -> dict[str, dict[str, Any]]:
        """Categorize metadata fields by type.

        Args:
            metadata: Metadata dictionary

        Returns:
            Dictionary with categorized fields
        """
        categorized: dict[str, dict[str, Any]] = {"numeric": {}, "dict": {}, "list": {}, "other": {}}

        for field, value in metadata.items():
            if field in self._STANDARD_FIELDS:
                continue

            if isinstance(value, (int, float)) and value != 0:
                categorized["numeric"][field] = value
            elif isinstance(value, dict) and value:
                categorized["dict"][field] = value
            elif isinstance(value, list):
                categorized["list"][field] = value
            elif value not in (None, ""):
                categorized["other"][field] = value

        return categorized

    @staticmethod
    def _print_numeric_fields(fields: dict[str, Any]) -> None:
        """Print numeric metadata fields."""
        if not fields:
            return

        logger.info(" Operator Metrics:")
        for field, value in sorted(fields.items()):
            display_name = field.replace("_", " ").title()
            logger.info("   %s: %s", display_name, value)

    def _print_dict_fields(self, fields: dict[str, Any], *, has_numeric: bool) -> None:
        """Print dictionary metadata fields."""
        if not fields:
            return

        if not has_numeric:
            logger.info(" Operator Details:")

        for field, value in sorted(fields.items()):
            display_name = field.replace("_", " ").title()
            self._format_dict_field(display_name, value)

    @staticmethod
    def _print_nested_dict_field(*, display_name: str, value: dict) -> None:
        """Print a dict field that contains nested dict values."""
        logger.info("   %s:", display_name)
        for k, v in value.items():
            if isinstance(v, dict):
                logger.info("      %s:", k)
                for nested_k, nested_v in v.items():
                    logger.info("         %s: %s", nested_k, nested_v)
            else:
                logger.info("      %s: %s", k, v)

    def _format_dict_field(self, display_name: str, value: dict) -> None:
        """Format and print a dictionary field."""
        if any(isinstance(v, dict) for v in value.values()):
            self._print_nested_dict_field(display_name=display_name, value=value)
        elif len(value) <= 10:
            formatted = ", ".join(f"{k}={v}" for k, v in value.items())
            logger.info("   %s: %s", display_name, formatted)
        else:
            logger.info("   %s:", display_name)
            for k, v in list(value.items())[:10]:
                logger.info("      %s: %s", k, v)
            if len(value) > 10:
                logger.info("      ... and %s more", len(value) - 10)

    @staticmethod
    def _print_other_fields(fields: dict[str, Any]) -> None:
        """Print string/other metadata fields."""
        if not fields:
            return

        for field, value in sorted(fields.items()):
            display_name = field.replace("_", " ").title()
            str_value = str(value)
            if len(str_value) > 100:
                str_value = str_value[:97] + "..."
            logger.info("   %s: %s", display_name, str_value)

    def _print_list_fields(self, fields: dict[str, Any]) -> None:
        """Print list metadata fields."""
        if not fields:
            return

        for field, value in sorted(fields.items()):
            if field in ("failed_docs", "skipped_docs"):
                self._print_failed_skipped_docs(field, value)
            else:
                self._print_generic_list(field, value)

    def _print_failed_skipped_docs(self, field: str, docs: list) -> None:
        """Print failed or skipped documents.

        Failed docs are printed at ERROR level so they surface regardless of DS_LOG_LEVEL.
        Skipped docs remain at INFO level.
        """
        if not docs:
            return

        is_failed = field == "failed_docs"
        log = logger.error if is_failed else logger.info

        log("")
        log(" %s (%d items):", field.replace("_", " ").upper(), len(docs))
        for item in docs:
            if isinstance(item, dict):
                doc_id = item.get("id", "unknown")
                reason = item.get("reason", "")
                display_name = self._lookup_doc_name_from_table(doc_id) or item.get("name") or doc_id

                if reason:
                    log("   - %s: %s", display_name, reason)
                else:
                    log("   - %s", display_name)
            else:
                log("   - %s", item)

    @staticmethod
    def _print_generic_list(field: str, value: list) -> None:
        """Print generic list field."""
        display_name = field.replace("_", " ").title()
        if value:
            if len(value) <= 5:
                formatted_list = ", ".join(str(v) for v in value)
                logger.info("   %s: %s", display_name, formatted_list)
            else:
                preview = ", ".join(str(v) for v in value[:3])
                logger.info("   %s (%s items): %s, ...", display_name, len(value), preview)
        else:
            logger.info("   %s: []", display_name)

    @staticmethod
    def _extract_name_from_row(*, table: Any, idx: int, search_id: str) -> str | None:
        """Extract a usable display name from a matched row.

        Tries the name then path columns; returns the first non-empty value
        that is not the document ID itself.

        Args:
            table: PyArrow table containing the row
            idx: Row index to inspect
            search_id: The document ID string (excluded from results)

        Returns:
            Display name if found, None otherwise
        """
        for col_name in [OperatorConstants.Columns.NAME, OperatorConstants.Columns.PATH]:
            if col_name in table.column_names:
                name_value = table.column(col_name)[idx].as_py()
                if name_value and str(name_value) != search_id:
                    return name_value
        return None

    def _find_doc_name_in_table(self, *, table: Any, doc_id: str) -> str | None:
        """Search a single PyArrow table for a document name matching doc_id.

        Args:
            table: A PyArrow table to search
            doc_id: Document ID to look up

        Returns:
            Document name/path if found, None otherwise
        """
        id_column = OperatorConstants.Columns.ID
        if id_column not in table.column_names:
            return None

        search_id = str(doc_id)
        id_col = table.column(id_column)
        for idx in range(len(id_col)):
            if str(id_col[idx].as_py()) == search_id:
                # Found the row — delegate name extraction to helper
                return self._extract_name_from_row(table=table, idx=idx, search_id=search_id)

        return None

    def _lookup_doc_name_from_table(self, doc_id: str) -> str | None:
        """Look up document name from PyArrow table using document ID.

        Args:
            doc_id: Document ID (hash) to look up

        Returns:
            Document name/path if found, None otherwise
        """
        if not doc_id:
            return None

        try:
            tables_to_search = []
            if self._current_tables:
                tables_to_search.extend(self._current_tables)
            if self._previous_tables:
                tables_to_search.extend(self._previous_tables)

            if not tables_to_search:
                return None

            for table in tables_to_search:
                if table is None:
                    continue
                result = self._find_doc_name_in_table(table=table, doc_id=doc_id)
                if result is not None:
                    return result

            return None
        except Exception:
            # Silently fail - this is just for enhanced display
            return None

    def print_flow_summary(self, *, job_stats: JobStats, dag_nodes: list[dict]) -> None:
        """Print final flow execution summary.

        Uses logger.error when there are any failures so the summary is visible
        regardless of DS_LOG_LEVEL.

        Args:
            job_stats: Complete job statistics
            dag_nodes: DAG node definitions in execution order
        """
        status = job_stats.status.value if job_stats.status else "UNKNOWN"
        duration = float(job_stats.duration) if job_stats.duration else 0.0

        has_failures = job_stats.failed_docs > 0
        log = logger.error if has_failures else logger.info

        total_docs = job_stats.total_docs
        actually_completed = total_docs - job_stats.failed_docs - job_stats.skipped_docs

        log("")
        log("=" * 80)
        log(" FLOW EXECUTION SUMMARY")
        log("=" * 80)
        log(" Status: %s", status)
        log(" Total Duration: %.2fs", duration)
        log(
            " Documents: %s completed, %s failed, %s skipped (of %s total)",
            actually_completed,
            job_stats.failed_docs,
            job_stats.skipped_docs,
            total_docs,
        )

        if job_stats.node_stats:
            self._print_operator_summary_table(job_stats.node_stats, dag_nodes, log=log)

        log("=" * 80)
        log("")

    def _print_operator_summary_table(self, node_stats: dict, dag_nodes: list[dict], *, log=None) -> None:
        """Print operator summary table in DAG execution order."""
        if log is None:
            log = logger.info

        log("")
        log(" Operator Summary:")
        log(" %-30s %-20s %-12s %-10s", "Operator", "Status", "Duration", "Docs")
        log(" %s", "-" * 78)

        dag_order = [
            op_def.get(OperatorConstants.Columns.ID) for op_def in dag_nodes if op_def.get(OperatorConstants.Columns.ID)
        ]
        position_map = {node_id: idx for idx, node_id in enumerate(dag_order)}

        sorted_nodes = sorted(node_stats.items(), key=lambda x: position_map.get(x[0], float("inf")))

        for node_id, stats in sorted_nodes:
            step_name = stats.name or node_id[:8]
            status_str = stats.node_status
            duration_str = self._format_duration(stats.time_taken)

            completed = len(stats.docs_completed)
            failed = len(stats.failed_docs)
            skipped = len(stats.skipped_docs)
            total = completed + failed + skipped
            docs_str = f"{completed}/{total}"

            row_log = logger.error if failed > 0 else log
            row_log(" %-30s %-20s %-12s %-10s", step_name, status_str, duration_str, docs_str)

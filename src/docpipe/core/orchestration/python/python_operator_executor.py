"""Pure-Python operator executor for in-process flow orchestration."""

import copy
from typing import Any

import pyarrow as pa
from data_processing.data_access import DataAccessFactory

from docpipe.core.constants.constants import (
    DocpipeConstants,
    MemoryLogPhases,
    OrchestratorType,
)
from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.core.job_management.domain.ports import JobStatsService
from docpipe.core.operators.abstract_operator import AbstractOperator
from docpipe.core.operators.operator_utils import OperatorUtils
from docpipe.core.orchestration.abstract_operator_executor import AbstractOperatorExecutor
from docpipe.core.orchestration.operator_factory import OperatorFactoryProvider
from docpipe.exceptions.docpipe_exceptions import DocpipeException
from docpipe.exceptions.error_messages import ValidationCodeMessages
from docpipe.utils.infrastructure.logging import get_logger
from docpipe.utils.infrastructure.performance import cleanup_pyarrow_buffers, log_memory_usage

logger = get_logger()


class PythonOperatorExecutor(AbstractOperatorExecutor):
    """Python operator executor that runs operators directly within the Python runtime."""

    def __init__(
        self,
        *,
        name: str,
        operator: str,
        params: dict,
        job_stats_service: JobStatsService | None = None,
        enable_custom_operators: bool = True,
        custom_operator_packages: list[str] | None = None,
    ):
        """Initialise the executor and build the operator factory.

        Args:
            name: Logical name for this executor node.
            operator: Short name of the operator to resolve and run.
            params: Configuration dictionary passed to the operator.
            job_stats_service: Optional service for recording job statistics.
            enable_custom_operators: Whether to load externally registered operators.
            custom_operator_packages: Optional list of package names to load custom operators from.
        """
        super().__init__(
            name=name,
            operator=operator,
            params=params,
            job_stats_service=job_stats_service,
        )
        # Create operator factory with custom operator support
        self.operator_factory = OperatorFactoryProvider.get_operator_factory(
            orchestrator=OrchestratorType.PYTHON,
            package_names=custom_operator_packages,
            enable_custom_operators=enable_custom_operators,
        )
        # Cached operator instance — constructed once on first call, reused within this executor.
        # An executor lives exactly one node execution (created per node per batch), so caching
        # here carries no cross-batch state and needs no thread-safety guard.
        self._operator_instance: AbstractOperator | None = None

    def _execute_impl(self, tables: pa.Table | dict[str, pa.Table] | None) -> tuple[list[pa.Table], dict[str, Any]]:
        """
        Executes the operator logic with support for pipeline branching.
        Uses Postgres-backed logger if pipeline branching is enabled.
        # Backward compatibility maintained
        """
        op = self.get_operator()
        op_config = op.config
        node_id = op_config.get(OperatorConstants.Columns.ID)
        if not isinstance(tables, dict):
            log_memory_usage(
                operator_name=op.name or "unknown",
                phase=MemoryLogPhases.START,
                table=tables,
                extra=op.common_log_arguments,
                logger=logger,
            )
        import timeit

        start = timeit.default_timer()

        common_log_arguments = {
            DocpipeConstants.JOB_ID: op_config.get(DocpipeConstants.JOB_ID),
            DocpipeConstants.JOB_RUN_ID: op_config.get(DocpipeConstants.JOB_RUN_ID),
            DocpipeConstants.NODE_ID: node_id,
        }

        op.logger = get_logger(f"{DocpipeConstants.LOGGER_NAME} : NODE_LOGGER")

        span = op._create_operator_span()
        try:
            self._log_start(
                op_logger=logger,
                name=op.name,
                short_name=op.short_name,
                common_log_arguments=common_log_arguments,
            )
            self.set_default_node_stats(tables=tables)
            is_merge_operator = isinstance(tables, dict)
            if is_merge_operator:
                logger.info(
                    "Invoking the transform method with multiple tables for the %s operator...",
                    op.short_name,
                )
                result = op.transform(table=pa.table({}), tables=tables)
            else:
                result = op.transform(tables)

            if len(op.output_features_to_drop) > 0:
                for i in range(len(result[0])):
                    result[0][i] = OperatorUtils.drop_features_from_table(op.output_features_to_drop, result[0][i])
            if len(op.updated_features) > 0:
                for i in range(len(result[0])):
                    result[0][i] = OperatorUtils.rename_features_and_save_original(
                        updated_features=op.updated_features,
                        input_features=result[0][i],
                    )
            metadata_copy = copy.deepcopy(result[1])
            # Handle empty documents after execution
            # Skip empty document handling for merge operators as they may have null values
            # in some columns due to outer joins, which doesn't mean the document is empty
            if is_merge_operator:
                out_tables, metadata = result[0], result[1]
            else:
                out_tables, metadata = self._handle_empty_documents(out_tables=result[0], metadata=result[1])
            cleanup_pyarrow_buffers(
                operator_name=op.name,
                phase=MemoryLogPhases.TRANSFORM_COMPLETED,
                table=result[0],
                extra=op.common_log_arguments,
                logger=logger,
            )
            self.update_final_node_stats(tables=out_tables, metadata=metadata)
            time_taken = timeit.default_timer() - start
            # Removing the internal metrics from the operator metadata if any to another dict
            _ = OperatorUtils.remove_internal_metrics_from_metadata(metadata=metadata_copy)
            op._record_operator_metrics(span=span, metadata=metadata, duration_ms=time_taken * 1000, success=True)
            self._log_completion(
                op_logger=logger,
                name=op.name,
                time_taken=time_taken,
                result=result,
                metadata=metadata,
                common_log_arguments=common_log_arguments,
            )
            return out_tables, metadata
        except Exception as e:
            op._record_operator_metrics(
                span=span,
                duration_ms=(timeit.default_timer() - start) * 1000,
                success=False,
            )
            op._telemetry.record_exception(e, span=span)
            self._handle_exception(op_logger=op.logger, node_id=node_id, exception=e)
            raise
        finally:
            op._telemetry.end_span(span)

    def _handle_exception(self, *, op_logger, node_id, exception):
        """Log the exception that occurred during operator transformation."""
        from docpipe.core.models.session_info import get_session_info

        # Log error with transaction id
        logger.error(
            "Error during transformation in node id: %s transaction_ID: %s",
            node_id,
            get_session_info().transaction_id,
            stack_info=True,
            exc_info=True,
        )

    @staticmethod
    def _collect_vault_paths(obj: object, *, prefix: str = "") -> list[str]:
        """Recursively collect JSON paths of vault references in an object."""
        from docpipe.integrations.secrets.secret_provider import is_vault_reference

        if isinstance(obj, str) and is_vault_reference(obj):
            return [prefix]
        if isinstance(obj, dict):
            found_dict: list[str] = []
            for k, v in obj.items():
                found_dict.extend(
                    PythonOperatorExecutor._collect_vault_paths(v, prefix=f"{prefix}.{k}" if prefix else str(k))
                )
            return found_dict
        if isinstance(obj, list):
            found_list: list[str] = []
            for i, item in enumerate(obj):
                found_list.extend(PythonOperatorExecutor._collect_vault_paths(item, prefix=f"{prefix}[{i}]"))
            return found_list
        return []

    def _resolve_operator_params(self) -> dict[str, Any]:
        """Resolve any vault references in operator parameters."""
        from docpipe.integrations.secrets.secret_provider import resolve_value

        vault_paths = self._collect_vault_paths(self._params)
        if not vault_paths:
            return self._params

        logger.info(
            "Resolving vault references in operator '%s' config for paths: %s",
            self._operator,
            vault_paths,
        )
        resolved_params = resolve_value(self._params)
        logger.info("Vault references resolved successfully for operator '%s'", self._operator)
        return resolved_params

    def get_operator(self) -> AbstractOperator:
        """Return this executor's operator, constructing it on first use.

        The operator is built once and cached for the lifetime of this executor.
        An executor is created per node per batch, so the cache is always
        batch-scoped — no cross-batch state and no thread-safety concern.
        """
        if self._operator_instance is not None:
            return self._operator_instance

        clazz = self.operator_factory.get_operator(operator_name=self._operator)
        if clazz is None:
            raise DocpipeException(f"{ValidationCodeMessages.GET_OPERATOR_FAILED.value}: {self._operator}")

        resolved_params = self._resolve_operator_params()
        self._operator_instance = clazz(config=resolved_params)
        return self._operator_instance

    def release(self) -> None:
        """Release resources held by this executor's operator.

        Called by the orchestrator once it has finished with the executor, so it
        covers both the executed and the skipped path — a skipped operator has
        still been constructed by ``get_operator()`` and may hold a model
        reference (e.g. FastText).

        The cached instance is dropped as well as cleaned, so a later
        ``get_operator()`` rebuilds rather than returning a half-destroyed object.
        Idempotent, and never raises.
        """
        op, self._operator_instance = self._operator_instance, None
        if op is None or not hasattr(op, "cleanup"):
            return
        try:
            op.cleanup()
        except Exception:
            logger.warning("operator cleanup failed for %s", self._operator, exc_info=True)


# used for unit testing only
def main():  # pragma: no cover
    """Main."""
    op_def: dict[str, Any] = {
        "name": "regex",
        "operator": "regex_annotator",
        "config": {
            "doc_column": "content",
            "hash_column": "doc_hash",
            "regex": r"([a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+)",
        },
    }

    executor = PythonOperatorExecutor(
        name=op_def["name"],
        operator=op_def["operator"],
        params=op_def["config"],
        job_stats_service=None,
    )
    logger.debug("Starting execution...")
    content = pa.array(
        [
            "Contact support team via email:  support@ibm.com, or the sales team sales@in.ibm.com.",
            "My personal email id is jj@acm.org",
        ]
    )
    col_names = ["content"]
    input_table = pa.Table.from_arrays(arrays=[content], names=col_names)

    data_access_factory = DataAccessFactory()
    data_access_factory.apply_input_params({})
    data_access = data_access_factory.create_data_access()
    data_access.save_table("", input_table)

    _tables, _ = executor.execute(data_access=data_access, deleted_rows_list=None)

    logger.debug("Completed execution...")


# main entry point into the program; used for unit testing only
if __name__ == "__main__":  # pragma: no cover
    main()

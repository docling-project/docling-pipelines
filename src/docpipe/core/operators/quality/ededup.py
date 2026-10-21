"""Content deduplication with atomic, run-scoped shared admissions."""

from typing import Any

import pyarrow as pa
from data_processing.utils import TransformUtils

from docpipe.core.constants.constants import DocpipeConstants, Metrics
from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.core.operators.abstract_operator import AbstractOperator, OperatorCategory
from docpipe.core.operators.quality.ededup_storage.factory import get_default_ededup_factory
from docpipe.utils.infrastructure.logging import get_logger

logger = get_logger()


class EdedupOperator(AbstractOperator):
    """Remove repeated normalized content within a node's execution across batches."""

    short_name: str = OperatorConstants.Operators.EDEDUP
    category: OperatorCategory = OperatorCategory.Quality
    owner = DocpipeConstants.OWNER_DOCPIPE

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self.doc_id_column: str = config.get(
            OperatorConstants.Columns.DOC_ID_HASH, OperatorConstants.Columns.DOC_ID_HASH_DEFAULT
        )
        if "filter" in config:
            raise ValueError("ededup no longer accepts a DPK filter; configure the ededup storage backend instead")
        # Preserve standalone library use without creating a shared 'None' run.
        self._local_hashes: set[str] = set()

    @staticmethod
    def get_metadata() -> dict[str, Any]:
        """Get metadata."""
        return {
            OperatorConstants.Misc.CATEGORY: EdedupOperator.category.value,
            OperatorConstants.Misc.IS_OPERATOR_AVAILABLE: EdedupOperator.is_available(),
            OperatorConstants.Misc.LABEL: "De-duplicator",
            OperatorConstants.Config.DESCRIPTION: "Exact deduplication operator that removes duplicate documents based on content hash",
        }

    def transform(self, table: pa.Table) -> tuple[list[pa.Table], dict[str, Any]]:
        """Keep first local occurrences admitted by the configured shared store.

        Hash normalization matches the previous DPK transform. Shared admission
        is enabled when job and run context are present; standalone instances
        retain only local state. Store errors propagate rather than passing data.
        """
        total = table.num_rows if table is not None else 0
        metadata = self.create_base_metadata(total_docs_count=total)
        metadata[Metrics.External.REMOVED_DOCUMENTS] = 0
        if not total:
            return [table], metadata

        TransformUtils.validate_columns(table=table, required=[self.doc_column, self.doc_id_column])
        first_rows: dict[str, int] = {}
        for index, content in enumerate(table[self.doc_column].to_pylist()):
            content_hash = TransformUtils.str_to_hash(TransformUtils.normalize_string(str(content)))
            first_rows.setdefault(content_hash, index)

        source_column = OperatorConstants.Columns.ID
        if source_column not in table.column_names:
            source_column = self.doc_id_column
        doc_ids = table[source_column].to_pylist()
        if self.job_id or self.job_run_id:
            if not (self.job_id and self.job_run_id and self.id):
                raise ValueError("Shared ededup requires job_id, job_run_id and the flow node id")
            accepted = (
                get_default_ededup_factory()
                .get_store()
                .check_and_register_hashes(
                    job_id=str(self.job_id),
                    node_id=str(self.id),
                    job_run_id=str(self.job_run_id),
                    records={value: str(doc_ids[index]) for value, index in first_rows.items()},
                )
            )
        else:
            accepted = set(first_rows) - self._local_hashes
            self._local_hashes.update(accepted)

        keep = {index for value, index in first_rows.items() if value in accepted}
        output = table.filter(pa.array([index in keep for index in range(total)], type=pa.bool_()))
        names = table[OperatorConstants.Columns.NAME].to_pylist() if "name" in table.column_names else [""] * total
        paths = table["path"].to_pylist() if "path" in table.column_names else [""] * total
        for index in range(total):
            if index not in keep:
                self.record_skipped_document(
                    metadata=metadata,
                    doc_id=doc_ids[index],
                    doc_name=names[index],
                    reason="This document was identified as a duplicate and removed.",
                )
                metadata[Metrics.External.SKIPPED_DOCS][-1][Metrics.External.DOCUMENT_URL] = paths[index]
        metadata[Metrics.External.PROCESSED_DOCS] = len(keep)
        metadata[Metrics.External.REMOVED_DOCUMENTS] = total - len(keep)
        logger.info("Deduplication accepted %s of %s documents", len(keep), total, extra=self.common_log_arguments)
        return [output], metadata

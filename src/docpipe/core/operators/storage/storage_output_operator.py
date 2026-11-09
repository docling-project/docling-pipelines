# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""StorageOutputOperator — writes pipeline documents to storage destinations."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pyarrow as pa

# Import adapters so they self-register via @register_destination_adapter
import docpipe.core.operators.storage.adapters.outbound.destinations.box.adapter
import docpipe.core.operators.storage.adapters.outbound.destinations.filesystem.adapter
import docpipe.core.operators.storage.adapters.outbound.destinations.google_drive.adapter
import docpipe.core.operators.storage.adapters.outbound.destinations.s3.adapter
import docpipe.core.operators.storage.adapters.outbound.destinations.sharepoint.adapter  # noqa: F401
from docpipe.core.constants.constants import AttributeDataTypes, DocpipeConstants, ExecutionStatus, Metrics
from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.core.operators.abstract_operator import AbstractOperator, OperatorCategory
from docpipe.core.operators.operator_utils import OperatorUtils
from docpipe.core.operators.storage.adapters.outbound.destinations.factories.destination_factory import (
    DestinationAdapterFactory,
)
from docpipe.core.operators.storage.domain.models import ContentFormat, WriteMode, WriteResult
from docpipe.utils.infrastructure.exception_sanitizer import sanitize_exception
from docpipe.utils.infrastructure.logging import get_logger
from docpipe.utils.operators.binary_content_fetcher import get_binary_content
from docpipe.utils.operators.config_validation import validate_config_from_metadata

logger = get_logger()

_REQUIRED_COLUMNS_BY_MODE: dict[str, list[str]] = {
    WriteMode.PROCESSED_CONTENT: ["id", "name", "content"],
    WriteMode.REFETCH_ORIGINAL: ["id", "name", "path", "document_format"],
    WriteMode.COMPREHENSIVE_EXPORT: ["id", "name", "path", "content", "metadata", "document_format"],
}

_ALL_INPUT_COLUMNS = ["id", "name", "path", "content", "metadata", "document_format"]


def resolve_path_template(
    *,
    template: str | None,
    doc_id: str,
    name: str,
    ext: str,
    hierarchical: bool = False,
    source_relative_path: str | None = None,
) -> str:
    """Resolve a path template string with per-document variable substitution.

    Variables: {doc_id}, {name}, {ext}, {year}, {month}, {day}, {relative_dir}
    Falls back to "{name}.{ext}" (flat) or the source relative path (hierarchical)
    when template is None.

    When ``hierarchical=True`` and no template is provided, the source relative
    path is used to mirror the source directory structure at the destination.

    ``{relative_dir}`` expands to the directory portion of ``source_relative_path``
    (e.g. ``sub01`` for a file ingested as ``sub01/report.pdf``).  It is empty
    when the file lives at the root of the source tree.
    """
    now = datetime.now(tz=UTC)
    # Strip extension from name to get stem
    stem = Path(name).stem
    # Normalise ext: remove any leading dot so templates like "{doc_id}.{ext}" don't produce "..pdf"
    ext = ext.lstrip(".")

    # Derive the directory portion of the source relative path for {relative_dir}.
    relative_dir = str(Path(source_relative_path).parent) if source_relative_path else ""
    # Path("file.pdf").parent == "." — normalise to empty string so templates don't get a stray dot.
    if relative_dir == ".":
        relative_dir = ""

    variables = {
        "doc_id": doc_id,
        "name": stem,
        "ext": ext,
        "year": now.strftime("%Y"),
        "month": now.strftime("%m"),
        "day": now.strftime("%d"),
        "relative_dir": relative_dir,
    }

    if not template:
        if hierarchical and source_relative_path:
            return source_relative_path
        return f"{stem}.{ext}"

    resolved = template.format(**variables)
    # Collapse any double (or more) slashes that arise when {relative_dir} is empty.
    while "//" in resolved:
        resolved = resolved.replace("//", "/")
    return resolved


def _extract_source_relative_path(
    row: dict[str, Any],
    *,
    source_prefix: str | None = None,
    ingest_root: str | None = None,
    hierarchical: bool = False,
    source_paths: list[str] | None = None,
) -> str | None:
    """Extract ``relative_path`` from the row.

    Resolution order:
    1. ``metadata["relative_path"]`` — set by ``ingest_source`` filesystem adapter.
       When ``hierarchical=True`` and multiple ``source_paths`` are configured, the
       matching source root's folder name is prepended so each root gets its own
       sub-directory at the destination (e.g. ``source_files/report.pdf`` or
       ``sub01/report.pdf``).  The absolute file path is resolved from
       ``metadata["absolute_path"]`` or ``row["path"]`` for the match.
    2. ``metadata["key"]`` stripped of ``source_prefix`` — for S3 ``ingest_source`` rows.
    3. ``row["path"]`` stripped of ``ingest_root`` — for ``ingest_source`` (filesystem) rows which have
       no ``metadata`` column but carry the absolute path in ``path``.

    Returns the relative path (e.g. ``sub01/report.pdf``) when it can be determined,
    else ``None``.
    """
    raw = row.get("metadata", "{}")
    try:
        parsed = json.loads(raw) if raw else {}
    except (json.JSONDecodeError, TypeError):
        parsed = {}

    # 1. Prefer an explicitly stored relative_path (ingest_source filesystem adapter sets this).
    explicit = parsed.get("relative_path")
    if explicit:
        if hierarchical and source_paths:
            # Determine which configured source root owns this file and prefix its
            # folder name so each root gets its own sub-directory at the destination.
            # Each source path is treated as an independent root regardless of any
            # parent/child relationship between them.  We reconstruct the expected
            # absolute path as src_path / explicit and compare it directly against
            # the file's own absolute path — this is an exact match and cannot be
            # fooled by one source path being a subdirectory of another.
            abs_path_str = parsed.get("absolute_path") or row.get("path") or ""
            if abs_path_str:
                abs_path_resolved = Path(abs_path_str)
                for src in source_paths:
                    src_path = Path(src)
                    if src_path / explicit == abs_path_resolved:
                        return f"{src_path.name}/{explicit}"
        return explicit

    # 2. Fall back to deriving relative path from the S3 key by stripping the source prefix.
    key = parsed.get("key")
    if key and source_prefix:
        # Normalise: remove any leading slash from both sides so the comparison is stable.
        normalised_prefix = source_prefix.lstrip("/")
        normalised_key = key.lstrip("/")
        if normalised_key.startswith(normalised_prefix):
            relative = normalised_key[len(normalised_prefix) :]
            return relative.lstrip("/") or None

    # 3. For ingest_source (filesystem) rows: derive from the absolute path in the row using the ingest root.
    abs_path = row.get("path") or row.get("name")
    if abs_path and ingest_root:
        try:
            rel = str(Path(abs_path).relative_to(ingest_root))
            return rel or None
        except ValueError:
            pass

    return None


class StorageOutputOperator(AbstractOperator):
    """
    Writes pipeline documents to a storage destination.

    Supports three modes:
    - processed_content: write extracted content as .md / .txt / .json
    - refetch_original: re-fetch original binary from source and write to destination
    - comprehensive_export: write original + content + metadata sidecar per document
    """

    short_name: str = "storage_output"
    category: OperatorCategory = OperatorCategory.Storage
    owner = DocpipeConstants.OWNER_DOCPIPE
    # StorageOutputOperator does not produce extracted text content, so the
    # generic empty-document check (which keys off doc_column) must be skipped.
    doc_column: str | None = None

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self.mode: str | None = config.get("mode")
        self._global_config: dict[str, Any] = config
        self.destination_config: dict[str, Any] = config.get("destination_config", {})
        self.output_format: dict[str, Any] = config.get("output_format", {})
        self.output_structure: dict[str, Any] = config.get("output_structure", {})

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate(self, errors: list[str], warnings: list[str], available_features: list[str]) -> None:
        """Validate."""
        super().validate(errors=errors, warnings=warnings, available_features=available_features)

        metadata = self.get_metadata()
        attributes = metadata.get(OperatorConstants.Config.ATTRIBUTES, {})
        validate_config_from_metadata(config=self.config, attributes=attributes, errors=errors)

        if not self.mode:
            errors.append(f"{self.short_name}: 'mode' is required")
            return

        if self.mode not in list(WriteMode):
            errors.append(
                f"{self.short_name}: invalid mode '{self.mode}'. Must be one of: {[m.value for m in WriteMode]}"
            )
            return

        required_cols = _REQUIRED_COLUMNS_BY_MODE.get(self.mode, [])
        for col in required_cols:
            if col not in available_features:
                errors.append(f"{self.short_name}: required column '{col}' not found in available features")

    @staticmethod
    def _get_destination_provider_schemas() -> dict[str, Any]:
        """Return per-provider config schemas for the destination_config.provider_config field.

        Iterates all registered provider names (including aliases such as ibm_cos and onedrive)
        and converts each adapter's Pydantic config model to docpipe metadata vocabulary.
        """
        return {
            name: OperatorUtils.model_schema_to_docpipe(
                schema=DestinationAdapterFactory.create(name).get_config_schema().model_json_schema()
            )
            for name in DestinationAdapterFactory.get_registered_names()
        }

    @staticmethod
    def _get_secret_fields_by_provider() -> dict[str, dict[str, list[str]]]:
        """Aggregate each destination config class's secret-capable declarations per provider."""
        from docpipe.core.operators.secret_fields import build_provider_secret_fields

        return build_provider_secret_fields(
            selector="destination_config.provider",
            prefix="destination_config.provider_config",
            classes={
                name: DestinationAdapterFactory.create(name).get_config_schema()
                for name in DestinationAdapterFactory.get_registered_names()
            },
        )

    @staticmethod
    def get_metadata() -> dict[str, Any]:
        """Return operator metadata for flow validation and discovery."""
        return {
            "secret_fields": ["destination_config.credentials.*"],
            "secret_fields_by_provider": StorageOutputOperator._get_secret_fields_by_provider(),
            OperatorConstants.Misc.IS_OPERATOR_AVAILABLE: StorageOutputOperator.is_available(),
            OperatorConstants.Misc.CATEGORY: StorageOutputOperator.category.value,
            OperatorConstants.Misc.LABEL: "Storage Output",
            OperatorConstants.Config.DESCRIPTION: (
                "Writes pipeline documents to a storage destination. "
                "Supports processed_content, refetch_original, and comprehensive_export modes."
            ),
            OperatorConstants.Config.ATTRIBUTES: {
                "mode": {
                    OperatorConstants.Misc.NAME: "Mode",
                    OperatorConstants.Config.DESCRIPTION: (
                        "Write mode: processed_content writes extracted text, "
                        "refetch_original re-fetches and writes the source binary, "
                        "comprehensive_export writes original + content + metadata sidecar."
                    ),
                    OperatorConstants.Config.REQUIRED: True,
                    OperatorConstants.Misc.TYPE: AttributeDataTypes.STRING,
                    OperatorConstants.Config.VALID_VALUES: [m.value for m in WriteMode],
                },
                "destination_config": {
                    OperatorConstants.Misc.NAME: "Destination Configuration",
                    OperatorConstants.Config.DESCRIPTION: "Storage destination connection configuration.",
                    OperatorConstants.Config.REQUIRED: True,
                    OperatorConstants.Misc.TYPE: AttributeDataTypes.JSON,
                    OperatorConstants.Config.PROPERTIES: {
                        "provider": {
                            OperatorConstants.Misc.NAME: "Provider",
                            OperatorConstants.Config.DESCRIPTION: (
                                "Destination adapter: filesystem, s3, ibm_cos, box, "
                                "sharepoint, onedrive, or google_drive."
                            ),
                            OperatorConstants.Config.REQUIRED: True,
                            OperatorConstants.Misc.TYPE: AttributeDataTypes.STRING,
                            OperatorConstants.Config.VALID_VALUES: DestinationAdapterFactory.get_registered_names(),
                        },
                        "provider_config": {
                            OperatorConstants.Misc.NAME: "Provider Configuration",
                            OperatorConstants.Config.DESCRIPTION: (
                                "Provider-specific connection parameters. "
                                "Fields vary by provider — see the providers schema for details."
                            ),
                            OperatorConstants.Config.REQUIRED: True,
                            OperatorConstants.Misc.TYPE: AttributeDataTypes.JSON,
                            OperatorConstants.Config.PROVIDERS: StorageOutputOperator._get_destination_provider_schemas(),
                        },
                        "credentials": {
                            OperatorConstants.Misc.NAME: "Credentials",
                            OperatorConstants.Config.DESCRIPTION: (
                                "Provider-specific credentials (API keys, secrets, paths to credential files)."
                            ),
                            OperatorConstants.Config.DEFAULT: {},
                            OperatorConstants.Config.REQUIRED: False,
                            OperatorConstants.Misc.TYPE: AttributeDataTypes.JSON,
                            OperatorConstants.Config.SENSITIVE: True,
                        },
                    },
                },
                "output_format": {
                    OperatorConstants.Misc.NAME: "Output Format",
                    OperatorConstants.Config.DESCRIPTION: (
                        "Controls content format and optional metadata sidecar output."
                    ),
                    OperatorConstants.Config.REQUIRED: False,
                    OperatorConstants.Misc.TYPE: AttributeDataTypes.JSON,
                    OperatorConstants.Config.PROPERTIES: {
                        "content_format": {
                            OperatorConstants.Misc.NAME: "Content Format",
                            OperatorConstants.Config.DESCRIPTION: "Output file extension for extracted content.",
                            OperatorConstants.Config.REQUIRED: False,
                            OperatorConstants.Config.DEFAULT: ContentFormat.MD.value,
                            OperatorConstants.Misc.TYPE: AttributeDataTypes.STRING,
                            OperatorConstants.Config.VALID_VALUES: [f.value for f in ContentFormat],
                        },
                        "include_metadata_sidecar": {
                            OperatorConstants.Misc.NAME: "Include Metadata Sidecar",
                            OperatorConstants.Config.DESCRIPTION: (
                                "Write a .meta.json sidecar per document (comprehensive_export mode only)."
                            ),
                            OperatorConstants.Config.REQUIRED: False,
                            OperatorConstants.Config.DEFAULT: False,
                            OperatorConstants.Misc.TYPE: AttributeDataTypes.BOOLEAN,
                        },
                    },
                },
                "output_structure": {
                    OperatorConstants.Misc.NAME: "Output Structure",
                    OperatorConstants.Config.DESCRIPTION: "Controls output directory structure and file naming.",
                    OperatorConstants.Config.REQUIRED: False,
                    OperatorConstants.Misc.TYPE: AttributeDataTypes.JSON,
                    OperatorConstants.Config.PROPERTIES: {
                        "type": {
                            OperatorConstants.Misc.NAME: "Structure Type",
                            OperatorConstants.Config.DESCRIPTION: (
                                "flat writes all files into the root; hierarchical mirrors the source directory tree."
                            ),
                            OperatorConstants.Config.REQUIRED: False,
                            OperatorConstants.Config.DEFAULT: "flat",
                            OperatorConstants.Misc.TYPE: AttributeDataTypes.STRING,
                            OperatorConstants.Config.VALID_VALUES: ["flat", "hierarchical"],
                        },
                        "path_template": {
                            OperatorConstants.Misc.NAME: "Path Template",
                            OperatorConstants.Config.DESCRIPTION: (
                                "Template string for the output file path relative to the destination root. "
                                "Supported variables: {doc_id}, {name}, {ext}, "
                                "{year}, {month}, {day}, {relative_dir}."
                            ),
                            OperatorConstants.Config.REQUIRED: False,
                            OperatorConstants.Misc.TYPE: AttributeDataTypes.STRING,
                        },
                        "overwrite_existing": {
                            OperatorConstants.Misc.NAME: "Overwrite Existing",
                            OperatorConstants.Config.DESCRIPTION: (
                                "When false, existing files are skipped with write_status=skipped."
                            ),
                            OperatorConstants.Config.REQUIRED: False,
                            OperatorConstants.Config.DEFAULT: True,
                            OperatorConstants.Misc.TYPE: AttributeDataTypes.BOOLEAN,
                        },
                    },
                },
            },
        }

    @staticmethod
    def get_required_features() -> list[str]:
        """Get required features."""
        return ["id", "name", "content"]

    # ------------------------------------------------------------------
    # Transform
    # ------------------------------------------------------------------

    def transform(self, table: pa.Table) -> tuple[list[pa.Table], dict[str, Any]]:
        """Transform."""
        span = self._create_operator_span()
        try:
            return self._transform(table)
        except Exception as e:
            self._telemetry.record_exception(e, span=span)
            raise
        finally:
            self._telemetry.end_span(span)

    def _transform(self, table: pa.Table) -> tuple[list[pa.Table], dict[str, Any]]:
        """Execute the write pipeline: validate params, build adapter, iterate rows."""
        # --- parameter validation ---
        if not self.mode:
            msg = f"{self.short_name}: 'mode' is required"
            raise ValueError(msg)
        if not self.destination_config:
            msg = f"{self.short_name}: 'destination_config' is required"
            raise ValueError(msg)
        if self.mode in (WriteMode.REFETCH_ORIGINAL, WriteMode.COMPREHENSIVE_EXPORT):
            if not self._global_config.get(OperatorConstants.Config.INGEST_SOURCE):
                msg = f"{self.short_name}: mode '{self.mode}' requires an upstream 'ingest_source' operator"
                raise ValueError(msg)

        total = table.num_rows if table is not None else 0
        metadata = self.create_base_metadata(total_docs_count=total)

        if total == 0:
            output_table = self._build_output_table(table, [])
            metadata[Metrics.External.NODE_STATUS] = ExecutionStatus.COMPLETED
            return [output_table], metadata

        # --- build adapter + config ---
        provider = self.destination_config.get("provider", "")
        adapter = DestinationAdapterFactory.create(provider)
        try:
            provider_config = self.destination_config.get("provider_config") or {}
            # The UI stores provider-specific fields together in provider_config.
            # Keep the separate credentials field compatible with existing flows.
            credentials = {**provider_config, **(self.destination_config.get("credentials") or {})}
            dest_cfg = adapter.build_config_from_operator_params(
                provider_config=provider_config,
                credentials=credentials,
            )
        except (ValueError, KeyError) as e:
            config_error_msg = sanitize_exception(exc=e, config_key=f"{self.short_name}.destination_config")
            logger.error(
                "destination config error for operator '%s': %s",
                self.short_name,
                config_error_msg,
                extra=self.common_log_arguments,
            )
            write_results = [
                WriteResult(
                    doc_id=str(row.get("id", "")),
                    doc_name=str(row.get("name", "")),
                    success=False,
                    error_message=config_error_msg,
                )
                for row in (table.to_pylist() if table is not None else [])
            ]
            for result in write_results:
                self.record_failed_document(
                    metadata=metadata,
                    doc_id=result.doc_id,
                    doc_name=result.doc_name,
                    reason=config_error_msg,
                )
            metadata[Metrics.External.NODE_STATUS] = ExecutionStatus.FAILED
            output_table = self._build_output_table(table, write_results)
            self._record_operator_metrics(span=None, metadata=metadata)
            return [output_table], metadata

        # --- pre-flight destination check (fail fast before fetching any binaries) ---
        dest_validation_error = adapter.validate_destination(config=dest_cfg)
        if dest_validation_error is not None:
            write_results = [
                WriteResult(
                    doc_id=str(row.get("id", "")),
                    doc_name=str(row.get("name", "")),
                    success=False,
                    error_message=dest_validation_error.error_message,
                )
                for row in (table.to_pylist() if table is not None else [])
            ]
            for result in write_results:
                self.record_failed_document(
                    metadata=metadata,
                    doc_id=result.doc_id,
                    doc_name=result.doc_name,
                    reason=result.error_message or "destination validation failed",
                )
            metadata[Metrics.External.NODE_STATUS] = ExecutionStatus.FAILED
            output_table = self._build_output_table(table, write_results)
            self._record_operator_metrics(span=None, metadata=metadata)
            return [output_table], metadata

        content_format = self.output_format.get("content_format", ContentFormat.MD).lstrip(".")
        path_template = self.output_structure.get("path_template")
        overwrite = self.output_structure.get("overwrite_existing", True)
        hierarchical = self.output_structure.get("type", "flat") == "hierarchical"

        # Derive the ingest source prefix so hierarchical mode can reconstruct
        # relative paths for cloud sources (e.g. S3) that don't store relative_path
        # directly in document metadata.
        ingest_source = self._global_config.get(OperatorConstants.Config.INGEST_SOURCE, {})
        source_config = ingest_source.get(OperatorConstants.Config.PROVIDER_CONFIG, {})
        source_prefix: str | None = source_config.get("prefix")
        # Source paths list — used in hierarchical mode to prefix each root's folder name.
        source_paths: list[str] | None = source_config.get("paths") or None

        # For ingest_source (filesystem) rows there is no metadata column.  Derive the ingest root from
        # the common directory ancestor of all absolute paths in the batch so that the
        # sub-directory structure can be reconstructed at the destination.
        ingest_root: str | None = None
        if (hierarchical or path_template) and "path" in table.schema.names:
            abs_parent_dirs = [str(Path(p).parent) for p in table.column("path").to_pylist() if p]
            if abs_parent_dirs:
                try:
                    import os

                    ingest_root = os.path.commonpath(abs_parent_dirs)
                except (ValueError, TypeError):
                    ingest_root = None

        rows = table.to_pylist()
        row_write_results: list[WriteResult] = []

        for row in rows:
            doc_id = row.get("id", "")
            doc_name = row.get("name", "")
            # For cloud sources (e.g. Box, OneDrive) the `name` column holds the
            # source URL rather than the actual filename.  When the path has no
            # recognisable file extension, prefer the human-readable name stored
            # in the row's metadata (set by the source adapter).
            if doc_name and not Path(doc_name).suffix:
                try:
                    meta = json.loads(row.get("metadata") or "{}")
                    friendly = meta.get("name") or meta.get("box_name")
                    if friendly and Path(friendly).suffix:
                        doc_name = friendly
                except (json.JSONDecodeError, TypeError):
                    pass

            try:
                result = self._write_row(
                    row=row,
                    adapter=adapter,
                    dest_cfg=dest_cfg,
                    content_format=content_format,
                    path_template=path_template,
                    overwrite=overwrite,
                    hierarchical=hierarchical,
                    source_prefix=source_prefix,
                    source_paths=source_paths,
                    ingest_root=ingest_root,
                    doc_id=doc_id,
                    doc_name=doc_name,
                )
                result.doc_id = doc_id
                result.doc_name = doc_name
                row_write_results.append(result)

                if result.success:
                    metadata[Metrics.External.PROCESSED_DOCS] += 1
                elif result.write_status == "skipped":
                    self.record_skipped_document(
                        metadata=metadata,
                        doc_id=doc_id,
                        doc_name=doc_name,
                        reason=result.error_message or "skipped",
                    )
                else:
                    self.record_failed_document(
                        metadata=metadata,
                        doc_id=doc_id,
                        doc_name=doc_name,
                        reason=result.error_message or "unknown error",
                    )

            except Exception as e:
                safe_error = sanitize_exception(exc=e, config_key=f"{self.short_name}.destination_config")
                logger.error(
                    "Unexpected error writing document %s: %s",
                    doc_name,
                    safe_error,
                    extra=self.common_log_arguments,
                )
                row_write_results.append(
                    WriteResult(
                        doc_id=doc_id,
                        doc_name=doc_name,
                        success=False,
                        error_message=safe_error,
                    )
                )
                self.record_failed_document(
                    metadata=metadata,
                    doc_id=doc_id,
                    doc_name=doc_name,
                    reason=safe_error,
                )

        metadata[Metrics.External.NODE_STATUS] = OperatorUtils.determine_execution_status(
            processed_count=metadata[Metrics.External.PROCESSED_DOCS],
            failed_count=metadata[Metrics.External.FAILED_DOCS_COUNT],
            skipped_count=metadata[Metrics.External.SKIPPED_DOCS_COUNT],
        )

        output_table = self._build_output_table(table, row_write_results)
        self._record_operator_metrics(span=None, metadata=metadata)
        return [output_table], metadata

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _write_row(
        self,
        *,
        row: dict[str, Any],
        adapter: Any,
        dest_cfg: Any,
        content_format: str,
        path_template: str | None,
        overwrite: bool,
        hierarchical: bool,
        source_prefix: str | None,
        source_paths: list[str] | None,
        ingest_root: str | None,
        doc_id: str,
        doc_name: str,
    ) -> WriteResult:
        """Dispatch a single row to the correct write method based on mode."""
        if self.mode == WriteMode.PROCESSED_CONTENT:
            return self._write_processed_content(
                row=row,
                adapter=adapter,
                dest_cfg=dest_cfg,
                content_format=content_format,
                path_template=path_template,
                overwrite=overwrite,
                hierarchical=hierarchical,
                source_prefix=source_prefix,
                source_paths=source_paths,
                ingest_root=ingest_root,
                doc_id=doc_id,
                doc_name=doc_name,
            )
        if self.mode == WriteMode.REFETCH_ORIGINAL:
            return self._write_refetch_original(
                row=row,
                adapter=adapter,
                dest_cfg=dest_cfg,
                path_template=path_template,
                overwrite=overwrite,
                hierarchical=hierarchical,
                source_prefix=source_prefix,
                source_paths=source_paths,
                ingest_root=ingest_root,
                doc_id=doc_id,
                doc_name=doc_name,
            )
        if self.mode == WriteMode.COMPREHENSIVE_EXPORT:
            return self._write_comprehensive_export(
                row=row,
                adapter=adapter,
                dest_cfg=dest_cfg,
                content_format=content_format,
                path_template=path_template,
                overwrite=overwrite,
                hierarchical=hierarchical,
                source_prefix=source_prefix,
                source_paths=source_paths,
                ingest_root=ingest_root,
                doc_id=doc_id,
                doc_name=doc_name,
            )
        msg = f"Mode '{self.mode}' not yet implemented"
        raise NotImplementedError(msg)

    def _write_processed_content(
        self,
        *,
        row: dict[str, Any],
        adapter: Any,
        dest_cfg: Any,
        content_format: str,
        path_template: str | None,
        overwrite: bool,
        hierarchical: bool,
        source_prefix: str | None,
        source_paths: list[str] | None,
        ingest_root: str | None,
        doc_id: str,
        doc_name: str,
    ) -> WriteResult:
        """Write extracted text content to the destination in the requested format."""
        content_str: str = row.get("content", "") or ""

        if not content_str:
            result = WriteResult(
                doc_id=doc_id,
                doc_name=doc_name,
                success=False,
                error_message="No extracted content available — document may have been skipped by an upstream operator",
            )
            result.write_status = "skipped"
            return result

        if content_format == ContentFormat.JSON:
            payload = {
                "id": doc_id,
                "name": doc_name,
                "content": content_str,
            }
            content_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        else:
            content_bytes = content_str.encode("utf-8")

        # Resolve base path using the original name, then apply the ".content.<ext>" infix
        # so naming is consistent with comprehensive_export mode.
        relative_path = resolve_path_template(
            template=path_template,
            doc_id=doc_id,
            name=doc_name,
            ext=content_format,
            hierarchical=hierarchical,
            source_relative_path=_extract_source_relative_path(
                row,
                source_prefix=source_prefix,
                source_paths=source_paths,
                ingest_root=ingest_root,
                hierarchical=hierarchical,
            ),
        )
        base_path = Path(adapter.resolve_destination_path(relative_path=relative_path, config=dest_cfg))
        destination_path = str(base_path.with_name(base_path.stem + f".content.{content_format}"))

        return adapter.write_document(
            content=content_bytes,
            destination_path=destination_path,
            overwrite=overwrite,
            config=dest_cfg,
        )

    def _write_refetch_original(
        self,
        *,
        row: dict[str, Any],
        adapter: Any,
        dest_cfg: Any,
        path_template: str | None,
        overwrite: bool,
        hierarchical: bool,
        source_prefix: str | None,
        source_paths: list[str] | None,
        ingest_root: str | None,
        doc_id: str,
        doc_name: str,
    ) -> WriteResult:
        """Re-fetch the original binary from the source and write it to the destination."""
        ext = row.get("document_format", "") or Path(doc_name).suffix.lstrip(".")
        relative_path = resolve_path_template(
            template=path_template,
            doc_id=doc_id,
            name=doc_name,
            ext=ext,
            hierarchical=hierarchical,
            source_relative_path=_extract_source_relative_path(
                row,
                source_prefix=source_prefix,
                source_paths=source_paths,
                ingest_root=ingest_root,
                hierarchical=hierarchical,
            ),
        )
        destination_path = adapter.resolve_destination_path(relative_path=relative_path, config=dest_cfg)

        binary = self._fetch_binary(row=row, doc_name=doc_name)

        if binary is None:
            return WriteResult(
                doc_id=doc_id,
                doc_name=doc_name,
                success=False,
                error_message=f"Could not fetch binary content for '{doc_name}' from source",
            )

        return adapter.write_document(
            content=binary,
            destination_path=destination_path,
            overwrite=overwrite,
            config=dest_cfg,
        )

    def _write_comprehensive_export(
        self,
        *,
        row: dict[str, Any],
        adapter: Any,
        dest_cfg: Any,
        content_format: str,
        path_template: str | None,
        overwrite: bool,
        hierarchical: bool,
        source_prefix: str | None,
        source_paths: list[str] | None,
        ingest_root: str | None,
        doc_id: str,
        doc_name: str,
    ) -> WriteResult:
        """Write original binary, extracted content, and optional metadata sidecar."""
        include_sidecar = self.output_format.get("include_metadata_sidecar", False)

        # 1. Fetch original binary
        binary = self._fetch_binary(row=row, doc_name=doc_name)

        if binary is None:
            return WriteResult(
                doc_id=doc_id,
                doc_name=doc_name,
                success=False,
                error_message=f"Could not fetch binary content for '{doc_name}' from source",
            )

        ext_original = row.get("document_format", "") or Path(doc_name).suffix.lstrip(".")

        # Resolve base path using the template (ext will be replaced per file type)
        base_relative = resolve_path_template(
            template=path_template,
            doc_id=doc_id,
            name=doc_name,
            ext=ext_original,
            hierarchical=hierarchical,
            source_relative_path=_extract_source_relative_path(
                row,
                source_prefix=source_prefix,
                source_paths=source_paths,
                ingest_root=ingest_root,
                hierarchical=hierarchical,
            ),
        )
        base_path = Path(adapter.resolve_destination_path(relative_path=base_relative, config=dest_cfg))

        # 2. Write original binary
        adapter.write_document(
            content=binary,
            destination_path=str(base_path),
            overwrite=overwrite,
            config=dest_cfg,
        )

        # 3. Write extracted content file — always "<stem>.content.<ext>" for consistent naming.
        content_str = row.get("content", "") or ""
        content_bytes = content_str.encode("utf-8")
        content_path = base_path.with_name(base_path.stem + f".content.{content_format}")
        adapter.write_document(
            content=content_bytes,
            destination_path=str(content_path),
            overwrite=overwrite,
            config=dest_cfg,
        )

        # 4. Write metadata sidecar JSON
        if include_sidecar:
            raw_metadata = row.get("metadata", "{}")
            try:
                parsed_metadata = json.loads(raw_metadata) if raw_metadata else {}
            except (json.JSONDecodeError, TypeError):
                parsed_metadata = {}

            # Merge scalar row columns (e.g. size, created_time, modified_time from
            # IngestLocalOperator) into parsed_metadata so the sidecar is always complete.
            _top_level_keys = {"id", "name", "document_format", "metadata", "content", "path"}
            for col, val in row.items():
                if col in _top_level_keys:
                    continue
                if val is not None and isinstance(val, (str, int, float, bool)):
                    parsed_metadata.setdefault(col, val)

            sidecar_payload = {
                "id": doc_id,
                "name": doc_name,
                "document_format": row.get("document_format", ""),
                "metadata": parsed_metadata,
            }
            sidecar_bytes = json.dumps(sidecar_payload, ensure_ascii=False).encode("utf-8")
            # Use ".meta.json" to avoid colliding with a source file that is itself a .json file.
            sidecar_path = base_path.with_name(base_path.stem + ".meta.json")
            adapter.write_document(
                content=sidecar_bytes,
                destination_path=str(sidecar_path),
                overwrite=overwrite,
                config=dest_cfg,
            )

        return WriteResult(
            doc_id=doc_id,
            doc_name=doc_name,
            success=True,
            destination_path=str(base_path.parent),
            bytes_written=len(binary),
        )

    def _fetch_binary(self, *, row: dict[str, Any], doc_name: str) -> bytes | None:
        """Fetch binary content for a row using ingest_source populated by the orchestrator."""
        return get_binary_content(
            doc_metadata={"path": row.get("path", ""), "name": doc_name},
            global_config=self._global_config,
        )

    @staticmethod
    def _build_output_table(
        input_table: pa.Table,
        write_results: list[WriteResult],
    ) -> pa.Table:
        """Append write-result columns to the input table, preserving all input columns."""
        num_rows = input_table.num_rows if input_table is not None else 0

        write_status = [r.write_status for r in write_results]
        destination_path = [r.destination_path for r in write_results]
        bytes_written = [r.bytes_written for r in write_results]
        write_error = [r.error_message for r in write_results]

        new_columns = pa.table(
            {
                "bytes_written": pa.array(bytes_written, type=pa.int64()),
                "write_status": pa.array(write_status, type=pa.string()),
                "write_error": pa.array(write_error, type=pa.string()),
                "destination_path": pa.array(destination_path, type=pa.string()),
            }
        )

        if input_table is None or num_rows == 0:
            return new_columns

        for col_name in new_columns.schema.names:
            input_table = input_table.append_column(
                new_columns.schema.field(col_name),
                new_columns.column(col_name),
            )

        return input_table

# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""KeywordCountOperator — counts keywords and phrases in each document.

Writes a fixed ``keyword_counts`` column of type ``map<string, int64>``
using literal, stemmed, or lemmatized matching.  Results are row-local;
no cross-document or cross-batch accumulation occurs.

See docs/operators/functional/keyword_count_readme.md for usage details.
"""

from __future__ import annotations

from typing import Any

import pyarrow as pa

from docpipe.core.constants.constants import AttributeDataTypes, DocpipeConstants, ExecutionStatus, Metrics
from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.core.operators.abstract_operator import AbstractOperator, OperatorCategory
from docpipe.core.operators.functional.keyword_normalization import (
    _SNOWBALL_LANGUAGES,
    LiteralMatcher,
    StemMatcher,
    _BaseMatcher,
)
from docpipe.core.operators.operator_utils import OperatorUtils
from docpipe.types import FlowConfig
from docpipe.utils.infrastructure.logging import get_logger

logger = get_logger()

# ---------------------------------------------------------------------------
# Constant short-hands
# ---------------------------------------------------------------------------
_KC = OperatorConstants.KeywordCount
_COL = OperatorConstants.Columns
_CFG = OperatorConstants.Config

# Output column is fixed and not configurable
_OUTPUT_COLUMN = _COL.KEYWORD_COUNTS  # "keyword_counts"
_MAP_TYPE = pa.map_(pa.string(), pa.int64())
_INT64_MAX = (1 << 63) - 1

# Valid unicode normalization values
_VALID_UNICODE_FORMS = frozenset([_KC.UNICODE_NFC, _KC.UNICODE_NFKC, _KC.UNICODE_NONE])


class KeywordCountOperator(AbstractOperator):
    """Count keywords in each document and write ``keyword_counts`` map column.

    Configuration is validated at construction time so that flow validation
    catches invalid configurations before execution.

    Attributes:
        short_name: Operator type identifier used in flow JSON.
        category: Functional operator category.
        owner: Built-in docpipe operator.
    """

    short_name: str = OperatorConstants.Operators.KEYWORD_COUNT
    category: OperatorCategory = OperatorCategory.Functional
    owner = DocpipeConstants.OWNER_DOCPIPE

    def __init__(self, config: FlowConfig) -> None:
        super().__init__(config)
        self._matcher: _BaseMatcher | None = None

        # --- Read configuration values ---
        self._keywords: list[str] = config.get(_KC.KEYWORDS, [])
        self._match_mode: str = config.get(_KC.MATCH_MODE, _KC.MATCH_MODE_LITERAL)
        self._language: str = config.get(_KC.LANGUAGE, "english")
        self._lemmatizer_model: str | None = config.get(_KC.LEMMATIZER_MODEL)
        self._case_sensitive: bool = config.get(_KC.CASE_SENSITIVE, False)
        self._whole_word: bool = config.get(_KC.WHOLE_WORD, True)
        self._unicode_normalization: str = config.get(_KC.UNICODE_NORMALIZATION, _KC.UNICODE_NFC)
        self._allow_overlapping: bool = config.get(_KC.ALLOW_OVERLAPPING, False)

        # Perform all configuration validation
        try:
            self._validate_config()
            self._initialize_matcher()
        except Exception:
            self.cleanup()
            raise

    # -----------------------------------------------------------------------
    # Configuration validation (runs in __init__)
    # -----------------------------------------------------------------------

    def _validate_config(self) -> None:
        """Validate all configuration fields; raises ValueError on any error."""
        self._validate_option_types()
        self._validate_match_mode_constraints()
        self._validate_keyword_list()
        self._validate_keyword_values()

    def _validate_option_types(self) -> None:
        """Validate type and value of each option field."""
        if self._match_mode not in {
            _KC.MATCH_MODE_LITERAL,
            _KC.MATCH_MODE_STEM,
            _KC.MATCH_MODE_LEMMA,
        }:
            raise ValueError("match_mode must be one of 'literal', 'stem', or 'lemma'; got an unsupported value")

        if self._unicode_normalization not in _VALID_UNICODE_FORMS:
            raise ValueError("unicode_normalization must be one of 'NFC', 'NFKC', or 'none'; got an unsupported value")

    def _validate_match_mode_constraints(self) -> None:
        """Validate option legality for the selected mode."""
        is_linguistic = self._match_mode in {_KC.MATCH_MODE_STEM, _KC.MATCH_MODE_LEMMA}

        if is_linguistic and self._case_sensitive:
            raise ValueError("case_sensitive must be false for stem and lemma modes")

        if is_linguistic and not self._whole_word:
            raise ValueError("whole_word must be true for stem and lemma modes")

        if self._match_mode != _KC.MATCH_MODE_LEMMA and self._lemmatizer_model is not None:
            raise ValueError("lemmatizer_model may only be supplied when match_mode is 'lemma'")

        if self._match_mode == _KC.MATCH_MODE_STEM:
            if self._language not in _SNOWBALL_LANGUAGES:
                raise ValueError(
                    f"stem mode does not support language '{self._language}'; "
                    f"supported languages: " + ", ".join(sorted(_SNOWBALL_LANGUAGES))
                )

        if self._match_mode == _KC.MATCH_MODE_LEMMA and not self._lemmatizer_model:
            raise ValueError("lemma mode requires lemmatizer_model to be set")

    def _validate_keyword_list(self) -> None:
        """Validate keyword list length and byte budget."""
        if not isinstance(self._keywords, list) or len(self._keywords) == 0:
            raise ValueError(f"keywords must be a non-empty list of strings; received {type(self._keywords).__name__}")

        if len(self._keywords) > _KC.MAX_KEYWORDS:
            raise ValueError(
                f"keywords requires between 1 and {_KC.MAX_KEYWORDS} entries; received {len(self._keywords)}"
            )

        for idx, kw in enumerate(self._keywords):
            if not isinstance(kw, str):
                raise ValueError(f"keyword at index {idx} must be a string; got {type(kw).__name__}")
            cp_len = len(kw)
            if cp_len > _KC.MAX_KEYWORD_CODE_POINTS:
                raise ValueError(f"keyword at index {idx} exceeds the {_KC.MAX_KEYWORD_CODE_POINTS}-code-point limit")

        total_cp = sum(len(kw) for kw in self._keywords)
        if total_cp > _KC.MAX_COMBINED_CODE_POINTS:
            raise ValueError(
                f"combined keyword code points ({total_cp}) exceed the {_KC.MAX_COMBINED_CODE_POINTS}-code-point limit"
            )

    def _validate_keyword_values(self) -> None:
        """Validate individual keyword content (non-empty, no leading/trailing whitespace)."""
        for idx, kw in enumerate(self._keywords):
            if not kw or not kw.strip():
                raise ValueError(f"keyword at index {idx} is empty or whitespace-only")
            if kw != kw.strip():
                raise ValueError(f"keyword at index {idx} has leading or trailing whitespace; remove the whitespace")

    # -----------------------------------------------------------------------
    # Matcher initialization (runs after config validation)
    # -----------------------------------------------------------------------

    def _initialize_matcher(self) -> None:
        """Build the appropriate matching engine and detect keyword collisions."""
        if self._match_mode == _KC.MATCH_MODE_LITERAL:
            matcher = LiteralMatcher(
                keywords=self._keywords,
                case_sensitive=self._case_sensitive,
                whole_word=self._whole_word,
                unicode_normalization=self._unicode_normalization,
                allow_overlapping=self._allow_overlapping,
            )
        elif self._match_mode == _KC.MATCH_MODE_STEM:
            matcher = StemMatcher(
                keywords=self._keywords,
                language=self._language,
                unicode_normalization=self._unicode_normalization,
                allow_overlapping=self._allow_overlapping,
            )
        else:
            # lemma — import deferred inside LemmaMatcher
            from docpipe.core.operators.functional.keyword_normalization import LemmaMatcher

            matcher = LemmaMatcher(
                keywords=self._keywords,
                lemmatizer_model=self._lemmatizer_model,
                unicode_normalization=self._unicode_normalization,
                allow_overlapping=self._allow_overlapping,
            )

        # Collision detection: check canonical keys are unique
        seen: dict[Any, int] = {}
        for idx, key in enumerate(matcher._canonical_keys):
            if key in seen:
                raise ValueError(
                    f"keywords at indices {seen[key]} and {idx} are equivalent after {self._match_mode} normalization"
                )
            seen[key] = idx

        self._matcher = matcher

    # -----------------------------------------------------------------------
    # AbstractOperator overrides
    # -----------------------------------------------------------------------

    def validate(self, errors: list[str], warnings: list[str], available_features: list[str]) -> None:
        """Validate that the configured document column is available upstream.

        Releases validation-only lemma pipeline if validating_flow is True.

        Args:
            errors: List to append validation error messages to.
            warnings: List to append validation warning messages to.
            available_features: Feature names produced by upstream operators.
        """
        try:
            OperatorUtils.validate_columns(available_features, [self.doc_column], self.short_name, errors)
        finally:
            if self.validating_flow and self._matcher is not None:
                self._matcher.cleanup()
                self._matcher = None

    @staticmethod
    def get_required_features() -> list[str]:
        """Return the static default required features (content column).

        Returns:
            List containing the default document column name.
        """
        return [OperatorConstants.Columns.DOC_COLUMN_DEFAULT]

    @staticmethod
    def get_static_required_features() -> list[str]:
        """Return required features without instantiation.

        Returns:
            List containing the default document column name.
        """
        return [OperatorConstants.Columns.DOC_COLUMN_DEFAULT]

    @staticmethod
    def get_metadata() -> dict[str, Any]:
        """Return operator metadata for registry and UI rendering.

        Returns:
            Metadata dict describing attributes and features.
        """
        return {
            OperatorConstants.Misc.SDK: False,
            OperatorConstants.Misc.CATEGORY: KeywordCountOperator.category.value,
            OperatorConstants.Misc.IS_OPERATOR_AVAILABLE: True,
            OperatorConstants.Misc.LABEL: "Keyword Count",
            _CFG.DESCRIPTION: (
                "Count keyword and phrase occurrences in each document and write the "
                "per-document counts to a fixed map column."
            ),
            _CFG.ATTRIBUTES: {
                _KC.KEYWORDS: {
                    OperatorConstants.Misc.NAME: "Keywords",
                    _CFG.DESCRIPTION: "List of keyword strings to count (1-20 entries, each at most 50 code points).",
                    _CFG.REQUIRED: True,
                    _CFG.ITEMS: {OperatorConstants.Misc.TYPE: AttributeDataTypes.STRING},
                    OperatorConstants.Misc.TYPE: "array",
                },
                _KC.MATCH_MODE: {
                    OperatorConstants.Misc.NAME: "Match Mode",
                    _CFG.DESCRIPTION: (
                        "Matching strategy: 'literal' (RE2 literal, default), "
                        "'stem' (Snowball stemming), or 'lemma' (spaCy lemmatization)."
                    ),
                    _CFG.REQUIRED: False,
                    _CFG.DEFAULT: _KC.MATCH_MODE_LITERAL,
                    OperatorConstants.Misc.TYPE: AttributeDataTypes.STRING,
                    _CFG.VALID_VALUES: [_KC.MATCH_MODE_LITERAL, _KC.MATCH_MODE_STEM, _KC.MATCH_MODE_LEMMA],
                },
                _KC.LANGUAGE: {
                    OperatorConstants.Misc.NAME: "Stem Language",
                    _CFG.DESCRIPTION: (
                        "Snowball stemmer language (stem mode only). "
                        "Supported: arabic, danish, dutch, english, finnish, french, "
                        "german, hungarian, italian, norwegian, portuguese, romanian, "
                        "russian, spanish, swedish."
                    ),
                    _CFG.REQUIRED: False,
                    _CFG.DEFAULT: "english",
                    OperatorConstants.Misc.TYPE: AttributeDataTypes.STRING,
                },
                _KC.LEMMATIZER_MODEL: {
                    OperatorConstants.Misc.NAME: "Lemmatizer Model",
                    _CFG.DESCRIPTION: (
                        "Installed spaCy model package name (lemma mode only). "
                        "Must be a plain Python identifier matching an installed package."
                    ),
                    _CFG.REQUIRED: False,
                    OperatorConstants.Misc.TYPE: AttributeDataTypes.STRING,
                },
                _KC.CASE_SENSITIVE: {
                    OperatorConstants.Misc.NAME: "Case Sensitive",
                    _CFG.DESCRIPTION: (
                        "When true, matching is case-sensitive (literal mode only). "
                        "Must be false for stem and lemma modes."
                    ),
                    _CFG.REQUIRED: False,
                    _CFG.DEFAULT: False,
                    OperatorConstants.Misc.TYPE: "bool",
                },
                _KC.WHOLE_WORD: {
                    OperatorConstants.Misc.NAME: "Whole Word",
                    _CFG.DESCRIPTION: (
                        "When true (default), only count matches at word boundaries. "
                        "Must be true for stem and lemma modes."
                    ),
                    _CFG.REQUIRED: False,
                    _CFG.DEFAULT: True,
                    OperatorConstants.Misc.TYPE: "bool",
                },
                _KC.UNICODE_NORMALIZATION: {
                    OperatorConstants.Misc.NAME: "Unicode Normalization",
                    _CFG.DESCRIPTION: (
                        "Unicode normalization form applied to both keywords and document text before matching. "
                        "Options: 'NFC' (default), 'NFKC', 'none'."
                    ),
                    _CFG.REQUIRED: False,
                    _CFG.DEFAULT: _KC.UNICODE_NFC,
                    OperatorConstants.Misc.TYPE: AttributeDataTypes.STRING,
                    _CFG.VALID_VALUES: [_KC.UNICODE_NFC, _KC.UNICODE_NFKC, _KC.UNICODE_NONE],
                },
                _KC.ALLOW_OVERLAPPING: {
                    OperatorConstants.Misc.NAME: "Allow Overlapping",
                    _CFG.DESCRIPTION: (
                        "When true, overlapping matches are counted. "
                        "By default (false) non-overlapping matching resumes after each matched span."
                    ),
                    _CFG.REQUIRED: False,
                    _CFG.DEFAULT: False,
                    OperatorConstants.Misc.TYPE: "bool",
                },
                _COL.DOC_COLUMN: {
                    OperatorConstants.Misc.NAME: "Document Column",
                    _CFG.DESCRIPTION: "Name of the column containing document text. Defaults to 'content'.",
                    _CFG.REQUIRED: False,
                    _CFG.DEFAULT: _COL.DOC_COLUMN_DEFAULT,
                    OperatorConstants.Misc.TYPE: AttributeDataTypes.STRING,
                },
            },
            _CFG.FEATURES: {
                _OUTPUT_COLUMN: {
                    OperatorConstants.Misc.NAME: "Keyword Counts",
                    _CFG.DESCRIPTION: (
                        "Map of configured keyword strings to per-document occurrence counts. "
                        "Type: map<string, int64>. Not filterable or vector-database eligible."
                    ),
                    _CFG.AVAILABLE_FOR_FILTER: False,
                    _CFG.AVAILABLE_FOR_VECTOR_DB: False,
                    OperatorConstants.Misc.TYPE: AttributeDataTypes.JSON,
                    OperatorConstants.Misc.TAGS: ["keyword_count"],
                },
            },
        }

    # -----------------------------------------------------------------------
    # transform()
    # -----------------------------------------------------------------------

    def transform(self, table: pa.Table) -> tuple[list[pa.Table], dict[str, Any]]:
        """Count keywords in each row and write/merge the ``keyword_counts`` column.

        Args:
            table: Input PyArrow table.

        Returns:
            Tuple of (output tables list, execution metadata dict).

        Raises:
            FlowExecutionFailedException: When the input table is missing the
                document column or the column has an incompatible type.
        """
        # Validate input column before any row processing
        OperatorUtils.validate_columns(table, [self.doc_column], self.short_name)

        col_idx = table.schema.get_field_index(self.doc_column)
        col_field = table.schema.field(col_idx)
        if col_field.type not in (pa.string(), pa.large_string()):
            from docpipe.exceptions.docpipe_exceptions import FlowExecutionFailedException

            raise FlowExecutionFailedException(
                f"{self.short_name}: requires a string column '{self.doc_column}'; received {col_field.type}"
            )

        # Empty table shortcut — still need to add/validate the output column
        total_docs = len(table)
        metadata = self.create_base_metadata(total_docs_count=total_docs)

        if total_docs == 0:
            output_table = self._add_empty_map_column(table)
            metadata[Metrics.External.PROCESSED_DOCS] = 0
            metadata[_KC.DOCUMENTS_WITH_MATCHES] = 0
            metadata[_KC.TOTAL_MATCHES] = 0
            metadata[_KC.MATCH_MODE_KEY] = self._match_mode
            return [output_table], metadata

        # Check/validate existing keyword_counts column if present
        existing_col_idx = table.schema.get_field_index(_OUTPUT_COLUMN)
        if existing_col_idx >= 0:
            self._check_existing_column_type(table=table, col_idx=existing_col_idx)

        # --- Row loop ---
        content_column = table.column(self.doc_column)
        existing_column = table.column(_OUTPUT_COLUMN) if existing_col_idx >= 0 else None

        # Pre-compute id/name columns for failure tracking
        id_col = table.column("id") if "id" in table.schema.names else None
        name_col = table.column("name") if "name" in table.schema.names else None

        # Per-row result: None = skipped/failed, list[int] = counts
        row_counts: list[list[int] | None] = []
        current_status = ExecutionStatus.COMPLETED

        for row_idx in range(total_docs):
            cell = content_column[row_idx]
            doc_id = str(id_col[row_idx].as_py()) if id_col is not None else f"row_{row_idx}"
            doc_name = str(name_col[row_idx].as_py()) if name_col is not None else f"row_{row_idx}"

            cell_value = cell.as_py()

            if cell_value is None:
                # Null content: skip
                row_counts.append(None)
                self.record_skipped_document(metadata=metadata, doc_id=doc_id, doc_name=doc_name, reason="null content")
                continue

            is_linguistic = self._match_mode in {_KC.MATCH_MODE_STEM, _KC.MATCH_MODE_LEMMA}
            if is_linguistic and len(cell_value) > _KC.MAX_DOCUMENT_CHARS_LINGUISTIC:
                row_counts.append(None)
                self.record_failed_document(
                    metadata=metadata,
                    doc_id=doc_id,
                    doc_name=doc_name,
                    reason="document exceeds linguistic character limit",
                )
                current_status = OperatorUtils.merge_status(current_status, ExecutionStatus.COMPLETED_WITH_ERRORS)
                continue

            try:
                assert self._matcher is not None, "matcher must be set before transform"
                counts = self._matcher.count(text=cell_value, keywords=self._keywords)
                row_counts.append(counts)
                metadata[Metrics.External.PROCESSED_DOCS] += 1
            except Exception as exc:
                row_counts.append(None)
                self.record_failed_document(
                    metadata=metadata,
                    doc_id=doc_id,
                    doc_name=doc_name,
                    reason=type(exc).__name__,
                )
                current_status = OperatorUtils.merge_status(current_status, ExecutionStatus.COMPLETED_WITH_ERRORS)

        # Aggregate execution metadata (from this invocation only)
        documents_with_matches = 0
        total_matches = 0
        for counts in row_counts:
            if counts is not None:
                row_total = sum(counts)
                total_matches += row_total
                if row_total > 0:
                    documents_with_matches += 1

        metadata[_KC.DOCUMENTS_WITH_MATCHES] = documents_with_matches
        metadata[_KC.TOTAL_MATCHES] = total_matches
        metadata[_KC.MATCH_MODE_KEY] = self._match_mode
        metadata[Metrics.External.NODE_STATUS] = current_status.value

        # --- Build / merge the output column ---
        output_table = self._build_output_table(
            table=table,
            row_counts=row_counts,
            existing_col_idx=existing_col_idx,
            existing_column=existing_column,
            metadata=metadata,
            current_status=current_status,
        )

        logger.debug(
            "keyword_count: processed %d rows, %d with matches, %d total matches",
            metadata[Metrics.External.PROCESSED_DOCS],
            documents_with_matches,
            total_matches,
        )

        return [output_table], metadata

    # -----------------------------------------------------------------------
    # Output construction helpers
    # -----------------------------------------------------------------------

    def _add_empty_map_column(self, table: pa.Table) -> pa.Table:
        """Add an empty map column (or validate existing) to a zero-row table.

        Args:
            table: Input table with zero rows.

        Returns:
            Table with keyword_counts column of the correct type.
        """
        existing_idx = table.schema.get_field_index(_OUTPUT_COLUMN)
        if existing_idx >= 0:
            self._check_existing_column_type(table=table, col_idx=existing_idx)
            return table

        empty_map = pa.array([], type=_MAP_TYPE)
        return table.append_column(pa.field(_OUTPUT_COLUMN, _MAP_TYPE), empty_map)

    @staticmethod
    def _check_existing_column_type(*, table: pa.Table, col_idx: int) -> None:
        """Raise if an existing keyword_counts column has the wrong type.

        Args:
            table: Input table.
            col_idx: Index of the existing column.

        Raises:
            FlowExecutionFailedException: When the type is not map<string, int64>.
        """
        from docpipe.exceptions.docpipe_exceptions import FlowExecutionFailedException

        field = table.schema.field(col_idx)
        col_type = field.type
        if not (
            isinstance(col_type, pa.MapType) and col_type.key_type == pa.string() and col_type.item_type == pa.int64()
        ):
            raise FlowExecutionFailedException(
                f"existing '{_OUTPUT_COLUMN}' column must have type map<string, int64>; got {col_type}"
            )

        # Check for duplicate/null keys in every row
        col = table.column(col_idx)
        for row_idx in range(len(col)):
            cell = col[row_idx]
            if cell.as_py() is None:
                continue
            seen_keys: set[str] = set()
            for key, _val in cell.as_py():
                if key is None:
                    raise FlowExecutionFailedException(
                        f"existing '{_OUTPUT_COLUMN}' column contains null map keys at row {row_idx}"
                    )
                if key in seen_keys:
                    raise FlowExecutionFailedException(
                        f"existing '{_OUTPUT_COLUMN}' column contains duplicate map keys at row {row_idx}"
                    )
                seen_keys.add(key)

    def _build_output_table(
        self,
        *,
        table: pa.Table,
        row_counts: list[list[int] | None],
        existing_col_idx: int,
        existing_column: pa.ChunkedArray | None,
        metadata: dict[str, Any],
        current_status: ExecutionStatus,
    ) -> pa.Table:
        """Build the final output table with keyword_counts column.

        When no existing column is present, appends a new column.
        When an existing column is present, merges counts in-place.

        Args:
            table: Input table.
            row_counts: Per-row count lists (None = skipped/failed).
            existing_col_idx: Index of the existing column (-1 if absent).
            existing_column: Existing column array if present.
            metadata: Execution metadata dict (may be updated on overflow).
            current_status: Current node status.

        Returns:
            Output table with keyword_counts column.
        """
        if existing_col_idx < 0:
            new_column = self._build_new_column(row_counts=row_counts)
            return table.append_column(pa.field(_OUTPUT_COLUMN, _MAP_TYPE), new_column)

        # Merge mode: build merged rows
        merged_rows = self._merge_rows(
            existing_column=existing_column,
            row_counts=row_counts,
            metadata=metadata,
            current_status=current_status,
        )
        new_column = pa.array(merged_rows, type=_MAP_TYPE)
        return table.set_column(existing_col_idx, pa.field(_OUTPUT_COLUMN, _MAP_TYPE), new_column)

    def _build_new_column(self, *, row_counts: list[list[int] | None]) -> pa.Array:
        """Build a new map array from per-row count lists.

        Args:
            row_counts: Per-row count lists (None = null map entry).

        Returns:
            PyArrow array of type map<string, int64>.
        """
        rows: list[dict[str, int] | None] = []
        for counts in row_counts:
            if counts is None:
                rows.append(None)
            else:
                rows.append(dict(zip(self._keywords, counts, strict=True)))
        return pa.array(rows, type=_MAP_TYPE)

    def _merge_rows(
        self,
        *,
        existing_column: pa.ChunkedArray,
        row_counts: list[list[int] | None],
        metadata: dict[str, Any],
        current_status: ExecutionStatus,
    ) -> list[dict[str, int] | None]:
        """Merge current row counts into the existing column.

        Truth table:
        - existing null + current valid → current map
        - existing valid + current None → existing map (preserved)
        - both None/null → null

        On overflow: the row is failed, existing map is preserved unchanged.

        Args:
            existing_column: Existing keyword_counts column.
            row_counts: Per-row count lists from this invocation.
            metadata: Execution metadata dict (updated on overflow failures).
            current_status: Running node status.

        Returns:
            List of merged map dicts (None = null output).
        """
        result: list[dict[str, int] | None] = []
        existing_flat = (
            existing_column.combine_chunks() if hasattr(existing_column, "combine_chunks") else existing_column
        )

        for row_idx, current_counts in enumerate(row_counts):
            existing_cell = existing_flat[row_idx].as_py()

            if current_counts is None:
                # Failed or skipped: preserve existing (may be None)
                if existing_cell is None:
                    result.append(None)
                else:
                    result.append(dict(existing_cell))
                continue

            current_map = dict(zip(self._keywords, current_counts, strict=True))

            if existing_cell is None:
                result.append(current_map)
                continue

            # Merge: existing pairs first (in order), then append new keys
            merged: dict[str, int] = {}
            overflow = False

            for ex_key, ex_val in existing_cell:
                if ex_key in current_map:
                    added = current_map[ex_key]
                    new_val = ex_val + added
                    if new_val > _INT64_MAX:
                        # Record overflow failure without wrapping
                        self.record_failed_document(
                            metadata=metadata,
                            doc_id=f"row_{row_idx}",
                            doc_name=f"row_{row_idx}",
                            reason="int64 overflow during map merge",
                        )
                        overflow = True
                        break
                    merged[ex_key] = new_val
                else:
                    merged[ex_key] = ex_val

            if overflow:
                # Preserve existing map unchanged on overflow
                result.append(dict(existing_cell))
                continue

            # Append new keys in configuration order
            for kw, cnt in current_map.items():
                if kw not in merged:
                    merged[kw] = cnt

            result.append(merged)

        return result

    # -----------------------------------------------------------------------
    # cleanup
    # -----------------------------------------------------------------------

    def cleanup(self) -> None:
        """Release matcher resources.  Idempotent; safe to call multiple times."""
        if self._matcher is not None:
            self._matcher.cleanup()
            self._matcher = None

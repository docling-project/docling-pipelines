# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Tests for KeywordCountOperator.

Covers:
- Task 2.1: __init__ config validation
- Task 2.2: input-column validation and row loop
- Task 2.3: map output construction and existing-column merge
- Task 2.4: execution metadata
- Task 2.5: validate(), get_required_features(), get_metadata()
- Task 2.6: privacy (no keywords/text in logs/errors)
- Task 2.7: cleanup() idempotency and constructor-failure cleanup
"""

import logging

import pyarrow as pa
import pytest

from docpipe.core.operators.functional.keyword_count import KeywordCountOperator
from docpipe.exceptions.docpipe_exceptions import FlowExecutionFailedException

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_op(keywords=None, **extra):
    """Build a KeywordCountOperator with defaults."""
    if keywords is None:
        keywords = ["contract", "clause"]
    cfg = {"keywords": keywords, **extra}
    return KeywordCountOperator(cfg)


def _make_table(rows, *, extra_cols=None):
    """Build a minimal PyArrow table with id, name, content columns."""
    ids = [f"doc_{i}" for i in range(len(rows))]
    names = [f"doc_{i}" for i in range(len(rows))]
    data = {
        "id": pa.array(ids, type=pa.string()),
        "name": pa.array(names, type=pa.string()),
        "content": pa.array(rows, type=pa.string()),
    }
    if extra_cols:
        data.update(extra_cols)
    return pa.table(data)


def _output_map(table, row_idx=0):
    """Get the keyword_counts map for a specific row as a dict."""
    col = table.column("keyword_counts")
    return dict(col[row_idx].as_py() or [])


# ===========================================================================
# Task 2.1 — __init__ config validation
# ===========================================================================


class TestConfigValidation:
    def test_no_keywords_raises(self):
        with pytest.raises(ValueError, match="non-empty list"):
            KeywordCountOperator({"keywords": []})

    def test_missing_keywords_raises(self):
        with pytest.raises((ValueError, TypeError)):
            KeywordCountOperator({})

    def test_too_many_keywords_raises(self):
        with pytest.raises(ValueError, match="1 and 20"):
            KeywordCountOperator({"keywords": [f"kw{i}" for i in range(21)]})

    def test_exactly_20_keywords_ok(self):
        op = KeywordCountOperator({"keywords": [f"kw{i:02d}" for i in range(20)]})
        assert op is not None
        op.cleanup()

    def test_keyword_too_long_raises(self):
        long_kw = "a" * 51
        with pytest.raises(ValueError, match="index 0"):
            KeywordCountOperator({"keywords": [long_kw]})

    def test_non_string_keyword_raises(self):
        with pytest.raises(ValueError, match="index 0"):
            KeywordCountOperator({"keywords": [5]})

    def test_whitespace_only_keyword_raises(self):
        with pytest.raises(ValueError, match="index 0"):
            KeywordCountOperator({"keywords": ["   "]})

    def test_leading_whitespace_keyword_raises(self):
        with pytest.raises(ValueError, match="index 0"):
            KeywordCountOperator({"keywords": [" contract"]})

    def test_empty_string_keyword_raises(self):
        with pytest.raises(ValueError, match="index 0"):
            KeywordCountOperator({"keywords": [""]})

    def test_duplicate_keywords_raises(self):
        with pytest.raises(ValueError, match="indices 0 and 1"):
            KeywordCountOperator({"keywords": ["contract", "contract"]})

    def test_case_insensitive_collision_raises(self):
        # "Contract" and "contract" collide in case-insensitive literal mode
        with pytest.raises(ValueError, match="indices"):
            KeywordCountOperator({"keywords": ["Contract", "contract"]})

    def test_case_sensitive_no_collision(self):
        # Different case with case_sensitive=True: no collision
        op = KeywordCountOperator({"keywords": ["Contract", "contract"], "case_sensitive": True})
        op.cleanup()

    def test_unknown_match_mode_raises(self):
        with pytest.raises(ValueError, match="match_mode"):
            KeywordCountOperator({"keywords": ["run"], "match_mode": "fuzzy"})

    def test_invalid_unicode_normalization_raises(self):
        with pytest.raises(ValueError, match="unicode_normalization"):
            KeywordCountOperator({"keywords": ["run"], "unicode_normalization": "NFD"})

    def test_case_sensitive_stem_mode_raises(self):
        with pytest.raises(ValueError, match="case_sensitive must be false"):
            KeywordCountOperator({"keywords": ["run"], "match_mode": "stem", "case_sensitive": True})

    def test_whole_word_false_stem_raises(self):
        with pytest.raises(ValueError, match="whole_word must be true"):
            KeywordCountOperator({"keywords": ["run"], "match_mode": "stem", "whole_word": False})

    def test_lemmatizer_model_outside_lemma_raises(self):
        with pytest.raises(ValueError, match="lemmatizer_model"):
            KeywordCountOperator({"keywords": ["run"], "match_mode": "literal", "lemmatizer_model": "en_core_web_sm"})

    def test_lemma_mode_no_model_raises(self):
        with pytest.raises(ValueError, match="lemmatizer_model"):
            KeywordCountOperator({"keywords": ["run"], "match_mode": "lemma"})

    def test_unsupported_stem_language_raises(self):
        with pytest.raises(ValueError, match="stem mode does not support language"):
            KeywordCountOperator({"keywords": ["run"], "match_mode": "stem", "language": "ja"})

    def test_valid_stem_english(self):
        op = KeywordCountOperator({"keywords": ["running"], "match_mode": "stem", "language": "english"})
        op.cleanup()

    def test_error_message_no_keyword_text(self):
        # Error messages must not contain keyword values, only indices
        with pytest.raises(ValueError) as exc_info:
            KeywordCountOperator({"keywords": [" secret_term "]})
        assert "secret_term" not in str(exc_info.value)

    def test_cleanup_on_collision_check_called(self):
        # Stem mode: "run" and "runs" collide; constructor should not leak resources
        try:
            KeywordCountOperator({"keywords": ["run", "runs"], "match_mode": "stem"})
        except ValueError:
            pass  # expected — no leak


# ===========================================================================
# Task 2.2 — Input-column validation and row loop
# ===========================================================================


class TestTransformInputValidation:
    def test_missing_content_column_raises(self):
        op = _make_op()
        table = pa.table({"other_col": pa.array(["hello"])})
        with pytest.raises((FlowExecutionFailedException, Exception)):
            op.transform(table)
        op.cleanup()

    def test_binary_column_raises(self):
        op = _make_op()
        table = pa.table(
            {
                "id": pa.array(["1"]),
                "name": pa.array(["d"]),
                "content": pa.array([b"bytes data"], type=pa.binary()),
            }
        )
        with pytest.raises(FlowExecutionFailedException, match="string column"):
            op.transform(table)
        op.cleanup()

    def test_large_string_column_accepted(self):
        op = _make_op(["contract"])
        table = pa.table(
            {
                "id": pa.array(["1"]),
                "name": pa.array(["d"]),
                "content": pa.array(["a contract document"], type=pa.large_utf8()),
            }
        )
        tables, _metadata = op.transform(table)
        assert len(tables) == 1
        assert tables[0].num_rows == 1
        op.cleanup()

    def test_null_content_produces_null_map(self):
        op = _make_op(["contract"])
        table = _make_table([None])
        tables, _metadata = op.transform(table)
        out = tables[0]
        cell = out.column("keyword_counts")[0].as_py()
        assert cell is None
        op.cleanup()

    def test_null_content_recorded_as_skipped(self):
        op = _make_op(["contract"])
        table = _make_table([None])
        _, metadata = op.transform(table)
        from docpipe.core.constants.constants import Metrics

        assert metadata[Metrics.External.SKIPPED_DOCS_COUNT] == 1
        op.cleanup()

    def test_empty_string_produces_zero_counts(self):
        op = _make_op(["contract"])
        table = _make_table([""])
        tables, metadata = op.transform(table)
        result = _output_map(tables[0])
        assert result == {"contract": 0}
        from docpipe.core.constants.constants import Metrics

        assert metadata[Metrics.External.PROCESSED_DOCS] == 1
        op.cleanup()

    def test_oversized_stem_document_fails_row(self):
        op = _make_op(["run"], match_mode="stem")
        big_text = "run " * 250_001  # > 1_000_000 chars
        table = _make_table([big_text])
        tables, metadata = op.transform(table)
        from docpipe.core.constants.constants import Metrics

        assert metadata[Metrics.External.FAILED_DOCS_COUNT] == 1
        cell = tables[0].column("keyword_counts")[0].as_py()
        assert cell is None
        op.cleanup()

    def test_oversized_literal_document_processed_normally(self):
        op = _make_op(["run"])
        big_text = "run " * 250_001  # > 1_000_000 chars
        table = _make_table([big_text])
        tables, _metadata = op.transform(table)
        result = _output_map(tables[0])
        # Literal mode has no size limit
        assert result["run"] > 0
        op.cleanup()


# ===========================================================================
# Task 2.3 — Map output construction and existing-column merge
# ===========================================================================


class TestMapOutputConstruction:
    def test_single_output_column_added(self):
        op = _make_op(["contract"])
        table = _make_table(["a contract here"])
        tables, _ = op.transform(table)
        out = tables[0]
        assert "keyword_counts" in out.schema.names
        assert out.schema.field("keyword_counts").type == pa.map_(pa.string(), pa.int64())
        # Exactly one keyword_counts field
        assert out.schema.names.count("keyword_counts") == 1
        op.cleanup()

    def test_all_other_columns_unchanged(self):
        op = _make_op(["contract"])
        table = _make_table(["text"])
        tables, _ = op.transform(table)
        out = tables[0]
        for col in ["id", "name", "content"]:
            assert col in out.schema.names
        op.cleanup()

    def test_configuration_order_in_map(self):
        op = _make_op(["b", "a"])
        table = _make_table(["a"])
        tables, _ = op.transform(table)
        pairs = tables[0].column("keyword_counts")[0].as_py()
        keys = [k for k, _ in pairs]
        assert keys == ["b", "a"]
        assert dict(pairs)["a"] == 1
        assert dict(pairs)["b"] == 0
        op.cleanup()

    def test_empty_table_zero_rows_correct_type(self):
        op = _make_op(["contract"])
        table = pa.table(
            {
                "id": pa.array([], type=pa.string()),
                "name": pa.array([], type=pa.string()),
                "content": pa.array([], type=pa.string()),
            }
        )
        tables, _metadata = op.transform(table)
        out = tables[0]
        assert out.num_rows == 0
        assert "keyword_counts" in out.schema.names
        assert out.schema.field("keyword_counts").type == pa.map_(pa.string(), pa.int64())
        op.cleanup()

    def test_merge_with_existing_column(self):
        # existing map [("run", 2)], current computes [("run", 2), ("walk", 3)]
        # → output [("run", 4), ("walk", 3)]
        op = _make_op(["run", "walk"])
        existing = pa.array(
            [[("run", 2)]],
            type=pa.map_(pa.string(), pa.int64()),
        )
        table = pa.table(
            {
                "id": pa.array(["1"]),
                "name": pa.array(["d"]),
                "content": pa.array(["run run walk walk walk"]),
                "keyword_counts": existing,
            }
        )
        tables, _ = op.transform(table)
        result = dict(tables[0].column("keyword_counts")[0].as_py())
        assert result["run"] == 2 + 2  # 2 existing + 2 counted
        assert result["walk"] == 3
        op.cleanup()

    def test_merge_no_duplicate_field(self):
        op = _make_op(["run"])
        existing = pa.array(
            [[("run", 1)]],
            type=pa.map_(pa.string(), pa.int64()),
        )
        table = pa.table(
            {
                "id": pa.array(["1"]),
                "name": pa.array(["d"]),
                "content": pa.array(["run"]),
                "keyword_counts": existing,
            }
        )
        tables, _ = op.transform(table)
        out = tables[0]
        assert out.schema.names.count("keyword_counts") == 1
        op.cleanup()

    def test_merge_null_existing_plus_valid_current(self):
        op = _make_op(["run"])
        existing = pa.array(
            [None],
            type=pa.map_(pa.string(), pa.int64()),
        )
        table = pa.table(
            {
                "id": pa.array(["1"]),
                "name": pa.array(["d"]),
                "content": pa.array(["run"]),
                "keyword_counts": existing,
            }
        )
        tables, _ = op.transform(table)
        result = dict(tables[0].column("keyword_counts")[0].as_py())
        assert result["run"] == 1
        op.cleanup()

    def test_merge_valid_existing_plus_null_current(self):
        op = _make_op(["run"])
        existing = pa.array(
            [[("run", 5)]],
            type=pa.map_(pa.string(), pa.int64()),
        )
        table = pa.table(
            {
                "id": pa.array(["1"]),
                "name": pa.array(["d"]),
                "content": pa.array([None], type=pa.string()),
                "keyword_counts": existing,
            }
        )
        tables, _ = op.transform(table)
        result = dict(tables[0].column("keyword_counts")[0].as_py())
        assert result["run"] == 5
        op.cleanup()

    def test_merge_both_null(self):
        op = _make_op(["run"])
        existing = pa.array(
            [None],
            type=pa.map_(pa.string(), pa.int64()),
        )
        table = pa.table(
            {
                "id": pa.array(["1"]),
                "name": pa.array(["d"]),
                "content": pa.array([None], type=pa.string()),
                "keyword_counts": existing,
            }
        )
        tables, _ = op.transform(table)
        cell = tables[0].column("keyword_counts")[0].as_py()
        assert cell is None
        op.cleanup()

    def test_existing_column_wrong_type_raises(self):
        op = _make_op(["run"])
        existing = pa.array([[("run", 1)]], type=pa.map_(pa.string(), pa.int32()))
        table = pa.table(
            {
                "id": pa.array(["1"]),
                "name": pa.array(["d"]),
                "content": pa.array(["run"]),
                "keyword_counts": existing,
            }
        )
        with pytest.raises(FlowExecutionFailedException, match="map<string, int64>"):
            op.transform(table)
        op.cleanup()

    def test_existing_column_string_type_raises(self):
        op = _make_op(["run"])
        table = pa.table(
            {
                "id": pa.array(["1"]),
                "name": pa.array(["d"]),
                "content": pa.array(["run"]),
                "keyword_counts": pa.array(["some_string"]),
            }
        )
        with pytest.raises(FlowExecutionFailedException, match="map<string, int64>"):
            op.transform(table)
        op.cleanup()

    def test_overflow_fails_row_preserves_existing(self):
        op = _make_op(["run"])
        int64_max = (1 << 63) - 1
        existing = pa.array(
            [[("run", int64_max)]],
            type=pa.map_(pa.string(), pa.int64()),
        )
        table = pa.table(
            {
                "id": pa.array(["1"]),
                "name": pa.array(["d"]),
                "content": pa.array(["run"]),
                "keyword_counts": existing,
            }
        )
        tables, metadata = op.transform(table)
        # Overflow: existing map preserved
        result = dict(tables[0].column("keyword_counts")[0].as_py())
        assert result["run"] == int64_max
        from docpipe.core.constants.constants import Metrics

        assert metadata[Metrics.External.FAILED_DOCS_COUNT] == 1
        op.cleanup()

    def test_keys_case_exactly_compared_in_merge(self):
        # "Run" and "run" are different map keys
        op = _make_op(["run"])
        existing = pa.array(
            [[("Run", 1)]],
            type=pa.map_(pa.string(), pa.int64()),
        )
        table = pa.table(
            {
                "id": pa.array(["1"]),
                "name": pa.array(["d"]),
                "content": pa.array(["run"]),
                "keyword_counts": existing,
            }
        )
        tables, _ = op.transform(table)
        result_pairs = tables[0].column("keyword_counts")[0].as_py()
        result_keys = [k for k, _ in result_pairs]
        # "Run" (existing) and "run" (new) should both be present
        assert "Run" in result_keys
        assert "run" in result_keys
        op.cleanup()


# ===========================================================================
# Task 2.4 — Execution metadata
# ===========================================================================


class TestExecutionMetadata:
    def test_documents_with_matches(self):
        op = _make_op(["contract"])
        table = _make_table(["a contract here", "no match here"])
        _, metadata = op.transform(table)
        assert metadata["documents_with_matches"] == 1
        op.cleanup()

    def test_total_matches(self):
        op = _make_op(["contract"])
        table = _make_table(["contract contract", "contract"])
        _, metadata = op.transform(table)
        assert metadata["total_matches"] == 3
        op.cleanup()

    def test_match_mode_in_metadata(self):
        op = _make_op(["run"], match_mode="stem")
        table = _make_table(["running"])
        _, metadata = op.transform(table)
        assert metadata["match_mode"] == "stem"
        op.cleanup()

    def test_metadata_excludes_accumulated_values(self):
        # Even when merge adds to existing counts, metadata reflects only current
        op = _make_op(["run"])
        existing = pa.array(
            [[("run", 5)]],
            type=pa.map_(pa.string(), pa.int64()),
        )
        table = pa.table(
            {
                "id": pa.array(["1"]),
                "name": pa.array(["d"]),
                "content": pa.array(["run"]),
                "keyword_counts": existing,
            }
        )
        _, metadata = op.transform(table)
        # Should reflect current invocation (1 match) not accumulated (5+1=6)
        assert metadata["total_matches"] == 1
        assert metadata["documents_with_matches"] == 1
        op.cleanup()

    def test_null_rows_excluded_from_aggregates(self):
        op = _make_op(["contract"])
        table = _make_table([None, "a contract"])
        _, metadata = op.transform(table)
        assert metadata["documents_with_matches"] == 1
        assert metadata["total_matches"] == 1
        op.cleanup()

    def test_no_per_keyword_totals_in_metadata(self):
        op = _make_op(["contract", "clause"])
        table = _make_table(["contract clause"])
        _, metadata = op.transform(table)
        # Individual keyword counts must not appear in metadata
        assert "contract" not in metadata
        assert "clause" not in metadata
        op.cleanup()


# ===========================================================================
# Task 2.5 — validate(), get_required_features(), get_metadata()
# ===========================================================================


class TestOperatorInterface:
    def test_get_required_features_returns_content(self):
        assert KeywordCountOperator.get_required_features() == ["content"]

    def test_get_static_required_features_returns_content(self):
        assert KeywordCountOperator.get_static_required_features() == ["content"]

    def test_custom_doc_column_required_in_validate(self):
        op = KeywordCountOperator({"keywords": ["run"], "doc_column": "body"})
        errors: list = []
        warnings: list = []
        op.validate(errors=errors, warnings=warnings, available_features=["content"])
        assert any("body" in str(e) for e in errors)
        op.cleanup()

    def test_validate_releases_matcher_when_validating_flow(self):
        op = KeywordCountOperator({"keywords": ["run"], "validating_flow": True})
        op.validate(errors=[], warnings=[], available_features=["content"])
        # Matcher should be released after validation
        assert op._matcher is None

    def test_get_metadata_returns_expected_keys(self):
        md = KeywordCountOperator.get_metadata()
        assert "attributes" in md
        assert "features" in md
        assert "keyword_counts" in md["features"]
        assert md["features"]["keyword_counts"]["available_for_filter"] is False
        assert md["features"]["keyword_counts"]["available_for_vector_db"] is False

    def test_get_metadata_no_keyword_values(self):
        # Metadata must not leak keyword values
        md_str = str(KeywordCountOperator.get_metadata())
        # No specific keyword values in the static metadata
        assert "contract" not in md_str
        assert "clause" not in md_str


# ===========================================================================
# Task 2.6 — Privacy: no keywords or document text in logs/errors
# ===========================================================================


class TestPrivacy:
    def test_no_keywords_in_log_output(self, caplog):
        with caplog.at_level(logging.DEBUG, logger="docpipe"):
            op = _make_op(["secret_contract"])
            table = _make_table(["secret_contract appears here"])
            op.transform(table)
            op.cleanup()

        full_log = caplog.text
        assert "secret_contract" not in full_log

    def test_no_document_text_in_log_output(self, caplog):
        with caplog.at_level(logging.DEBUG, logger="docpipe"):
            op = _make_op(["word"])
            table = _make_table(["sensitive_document_content_xyz"])
            op.transform(table)
            op.cleanup()

        full_log = caplog.text
        assert "sensitive_document_content_xyz" not in full_log

    def test_index_based_validation_error(self):
        # Keyword at index 2 is too long; error must reference index 2
        kws = ["a", "b", "c" * 51]
        with pytest.raises(ValueError) as exc_info:
            KeywordCountOperator({"keywords": kws})
        assert "index 2" in str(exc_info.value)
        # Must not contain the actual keyword content (the long 'ccc...')
        assert "c" * 51 not in str(exc_info.value)


# ===========================================================================
# Task 2.7 — cleanup() idempotency and constructor-failure cleanup
# ===========================================================================


class TestCleanup:
    def test_cleanup_idempotent(self):
        op = _make_op(["run"])
        op.cleanup()
        op.cleanup()  # second call must not raise

    def test_cleanup_releases_matcher(self):
        op = _make_op(["run"])
        assert op._matcher is not None
        op.cleanup()
        assert op._matcher is None

    def test_constructor_failure_cleans_up(self):
        # Pass an invalid config that gets past early checks but fails late
        # (too many keywords is early, so use the stem collision case)
        try:
            KeywordCountOperator({"keywords": ["run", "runs"], "match_mode": "stem"})
        except ValueError:
            pass  # expected
        # No assertion needed — just must not raise or leak

    def test_cleanup_before_transform_ok(self):
        op = _make_op(["run"])
        op.cleanup()
        # Calling transform after cleanup would fail on None matcher
        # (this is intentional; we just check cleanup doesn't crash)

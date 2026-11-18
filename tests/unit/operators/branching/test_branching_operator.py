#!/usr/bin/env python3
"""
Unit tests for BranchingOperator.

Tests branching data into multiple output tables based on SQL filter conditions.
Also includes a regression test verifying that BranchingOperator is correctly
registered by OperatorFactory (the primary bug that was previously fixed).
"""

import pyarrow as pa
import pytest

from docpipe.core.constants.constants import Metrics, OrchestratorType
from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.core.operators.functional.branching_operator import BranchingOperator

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_table(num_rows: int = 6) -> pa.Table:
    """
    Create a standard test PyArrow table with an 'id' column and several
    filterable columns.
    """
    return pa.table(
        {
            "id": [str(i) for i in range(1, num_rows + 1)],
            "name": [f"doc_{i}.txt" for i in range(1, num_rows + 1)],
            "content": [f"Document content {i}" for i in range(1, num_rows + 1)],
            "score": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0][:num_rows],
            "language": ["en", "fr", "en", "de", "en", "fr"][:num_rows],
            "word_count": [100, 200, 50, 300, 150, 250][:num_rows],
        }
    )


def make_branch(
    link_id: str,
    link_name: str,
    criteria_list=None,
    criteria_json=None,
    logical_operator: str = "AND",
) -> dict:
    """
    Build a branch configuration dict as expected by BranchingOperator.
    Pass neither criteria_list nor criteria_json for unconditional branching.
    """
    branch = {
        OperatorConstants.Misc.LINK_ID: link_id,
        OperatorConstants.Misc.LINK_NAME: link_name,
        OperatorConstants.Filtering.FILTER_LOGICAL_OPERATOR_KEY: logical_operator,
    }
    if criteria_list is not None:
        branch[OperatorConstants.Filtering.FILTER_CRITERIA_LIST] = criteria_list
    if criteria_json is not None:
        branch[OperatorConstants.Filtering.FILTER_CRITERIA_JSON] = criteria_json
    return branch


def make_operator(branches: list) -> BranchingOperator:
    """Create a BranchingOperator with the given branch list."""
    return BranchingOperator({"branches": branches})


# ---------------------------------------------------------------------------
# 1. OperatorFactory registration — primary regression test
# ---------------------------------------------------------------------------


class TestOperatorFactoryRegistration:
    """
    Regression tests: BranchingOperator must be loadable and registered by
    OperatorFactory under its short_name.  These tests catch the broken-import
    bug that previously prevented the operator from being discovered.
    """

    def test_branching_operator_registered_in_python_factory(self):
        """
        OperatorFactory for the Python orchestrator must contain BranchingOperator
        under the key OperatorConstants.Operators.BRANCHING ('branching').
        """
        from docpipe.core.orchestration.operator_factory import OperatorFactory

        factory = OperatorFactory(orchestrator=OrchestratorType.PYTHON)
        operator_class = factory.get_operator(operator_name=OperatorConstants.Operators.BRANCHING)

        assert operator_class is not None, (
            f"BranchingOperator was not registered in OperatorFactory. "
            f"Registered operators: {list(factory.operators.keys())}"
        )

    def test_branching_operator_class_is_branching_operator(self):
        """
        The class returned by OperatorFactory for 'branching' must be named
        'BranchingOperator'.

        Note: OperatorFactory reloads modules, so the class object may differ
        from the one imported at the top of this file. We compare by name
        rather than identity/issubclass to avoid false failures from module
        reloading.
        """
        from docpipe.core.orchestration.operator_factory import OperatorFactory

        factory = OperatorFactory(orchestrator=OrchestratorType.PYTHON)
        operator_class = factory.get_operator(operator_name=OperatorConstants.Operators.BRANCHING)

        assert operator_class is not None
        assert operator_class.__name__ == "BranchingOperator", (
            f"Expected class named 'BranchingOperator', got {operator_class.__name__}"
        )

    def test_branching_operator_can_be_instantiated_via_factory(self):
        """
        The class retrieved from OperatorFactory can be instantiated with a
        minimal config dict without raising an exception.
        """
        from docpipe.core.orchestration.operator_factory import OperatorFactory

        factory = OperatorFactory(orchestrator=OrchestratorType.PYTHON)
        operator_class = factory.get_operator(operator_name=OperatorConstants.Operators.BRANCHING)

        assert operator_class is not None
        instance = operator_class({"branches": []})
        assert instance is not None


# ---------------------------------------------------------------------------
# 2. short_name attribute
# ---------------------------------------------------------------------------


class TestShortName:
    def test_short_name_equals_branching_constant(self):
        """BranchingOperator.short_name == OperatorConstants.Operators.BRANCHING."""
        assert BranchingOperator.short_name == OperatorConstants.Operators.BRANCHING

    def test_short_name_value_is_branching_string(self):
        """BranchingOperator.short_name is the string 'branching'."""
        assert BranchingOperator.short_name == "branching"

    def test_short_name_is_class_attribute(self):
        """short_name is accessible as a class attribute (not just instance)."""
        assert hasattr(BranchingOperator, "short_name")
        assert BranchingOperator.short_name == "branching"


# ---------------------------------------------------------------------------
# 3. Unconditional branching (no filter criteria — all rows pass to every branch)
# ---------------------------------------------------------------------------


class TestUnconditionalBranching:
    """
    When a branch has no criteria_list and no criteria_json, all rows are
    forwarded to that branch unchanged.
    """

    def test_single_unconditional_branch_returns_full_table(self):
        """One unconditional branch returns the full input table."""
        table = make_table()
        branches = [make_branch(link_id="b1", link_name="all")]
        operator = make_operator(branches)

        result_tables, _ = operator.runner(table)

        assert len(result_tables) == 1
        assert result_tables[0].num_rows == table.num_rows

    def test_two_unconditional_branches_both_get_full_table(self):
        """Two unconditional branches each receive the full input table."""
        table = make_table()
        branches = [
            make_branch(link_id="b1", link_name="branch_a"),
            make_branch(link_id="b2", link_name="branch_b"),
        ]
        operator = make_operator(branches)

        result_tables, _ = operator.runner(table)

        assert len(result_tables) == 2
        assert result_tables[0].num_rows == table.num_rows
        assert result_tables[1].num_rows == table.num_rows

    def test_unconditional_branch_preserves_schema(self):
        """Unconditional branch output has the same columns as the input."""
        table = make_table()
        branches = [make_branch(link_id="b1", link_name="all")]
        operator = make_operator(branches)

        result_tables, _ = operator.runner(table)

        assert set(result_tables[0].column_names) == set(table.column_names)

    def test_unconditional_branch_metadata_has_branches_key(self):
        """Metadata from unconditional branching contains a 'branches' dict."""
        table = make_table()
        branches = [make_branch(link_id="b1", link_name="all")]
        operator = make_operator(branches)

        _, metadata = operator.runner(table)

        assert "branches" in metadata
        assert "b1" in metadata["branches"]

    def test_unconditional_branch_metadata_remaining_docs(self):
        """Metadata for unconditional branch reports remaining_docs == total rows."""
        table = make_table()
        branches = [make_branch(link_id="b1", link_name="all")]
        operator = make_operator(branches)

        _, metadata = operator.runner(table)

        # Verify branch metadata exists
        assert "b1" in metadata["branches"]
        assert metadata["branches"]["b1"]["processed_docs"] == table.num_rows


# ---------------------------------------------------------------------------
# 4. Conditional branching — criteria_list
# ---------------------------------------------------------------------------


class TestConditionalBranchingCriteriaList:
    """
    Tests for branches that use criteria_list (SQL WHERE clause strings).
    """

    def test_two_branches_split_rows_correctly(self):
        """
        Branch A: score <= 3  → rows 1,2,3
        Branch B: score > 3   → rows 4,5,6
        """
        table = make_table()
        branches = [
            make_branch(link_id="low", link_name="low_score", criteria_list=["score <= 3"]),
            make_branch(link_id="high", link_name="high_score", criteria_list=["score > 3"]),
        ]
        operator = make_operator(branches)

        result_tables, _ = operator.runner(table)

        assert len(result_tables) == 2
        low_scores = result_tables[0]["score"].to_pylist()
        high_scores = result_tables[1]["score"].to_pylist()
        assert all(s <= 3 for s in low_scores), f"Low branch has unexpected scores: {low_scores}"
        assert all(s > 3 for s in high_scores), f"High branch has unexpected scores: {high_scores}"

    def test_branch_with_language_filter(self):
        """Branch filters rows by language = 'en'."""
        table = make_table()
        branches = [
            make_branch(link_id="en", link_name="english", criteria_list=["language = 'en'"]),
        ]
        operator = make_operator(branches)

        result_tables, _ = operator.runner(table)

        langs = result_tables[0]["language"].to_pylist()
        assert all(lang == "en" for lang in langs)

    def test_branch_all_rows_match(self):
        """Branch where all rows match returns the full table."""
        table = make_table()
        branches = [
            make_branch(link_id="all", link_name="all_rows", criteria_list=["score > 0"]),
        ]
        operator = make_operator(branches)

        result_tables, _ = operator.runner(table)

        assert result_tables[0].num_rows == table.num_rows

    def test_branch_no_rows_match_returns_empty_table(self):
        """Branch where no rows match returns an empty table."""
        table = make_table()
        branches = [
            make_branch(link_id="none", link_name="no_match", criteria_list=["score > 9999"]),
        ]
        operator = make_operator(branches)

        result_tables, _ = operator.runner(table)

        assert result_tables[0].num_rows == 0

    def test_branch_no_rows_match_preserves_schema(self):
        """Empty branch result still has the correct column schema."""
        table = make_table()
        branches = [
            make_branch(link_id="none", link_name="no_match", criteria_list=["score > 9999"]),
        ]
        operator = make_operator(branches)

        result_tables, _ = operator.runner(table)

        assert set(result_tables[0].column_names) == set(table.column_names)

    def test_three_branches_disjoint_split(self):
        """
        Three branches with disjoint criteria:
          A: score <= 2  → rows 1,2
          B: score > 2 AND score <= 4  → rows 3,4
          C: score > 4  → rows 5,6
        """
        table = make_table()
        branches = [
            make_branch(link_id="low", link_name="low", criteria_list=["score <= 2"]),
            make_branch(
                link_id="mid",
                link_name="mid",
                criteria_list=["score > 2", "score <= 4"],
                logical_operator="AND",
            ),
            make_branch(link_id="high", link_name="high", criteria_list=["score > 4"]),
        ]
        operator = make_operator(branches)

        result_tables, _ = operator.runner(table)

        assert len(result_tables) == 3
        assert result_tables[0].num_rows == 2
        assert result_tables[1].num_rows == 2
        assert result_tables[2].num_rows == 2

    def test_or_logical_operator_in_branch(self):
        """Branch with OR logical operator: language = 'fr' OR language = 'de'."""
        table = make_table()
        branches = [
            make_branch(
                link_id="non_en",
                link_name="non_english",
                criteria_list=["language = 'fr'", "language = 'de'"],
                logical_operator="OR",
            ),
        ]
        operator = make_operator(branches)

        result_tables, _ = operator.runner(table)

        langs = result_tables[0]["language"].to_pylist()
        assert all(lang in ("fr", "de") for lang in langs)


# ---------------------------------------------------------------------------
# 5. Conditional branching — criteria_json
# ---------------------------------------------------------------------------


class TestConditionalBranchingCriteriaJson:
    """
    Tests for branches that use criteria_json (structured JSON filter).
    """

    def test_branch_with_simple_json_criteria(self):
        """Branch using criteria_json with a single condition."""
        table = make_table()
        criteria_json = {
            "variable": "score",
            "operator": ">",
            "value": 3,
        }
        branches = [
            make_branch(link_id="high", link_name="high_score", criteria_json=criteria_json),
        ]
        operator = make_operator(branches)

        result_tables, _ = operator.runner(table)

        scores = result_tables[0]["score"].to_pylist()
        assert all(s > 3 for s in scores)

    def test_branch_with_nested_and_json_criteria(self):
        """Branch using criteria_json with nested AND conditions."""
        table = make_table()
        criteria_json = {
            "logical_operator": "AND",
            "criteria_list": [
                {"variable": "score", "operator": ">", "value": 2},
                {"variable": "language", "operator": "=", "value": "en"},
            ],
        }
        branches = [
            make_branch(link_id="en_high", link_name="english_high", criteria_json=criteria_json),
        ]
        operator = make_operator(branches)

        result_tables, _ = operator.runner(table)

        for row_idx in range(result_tables[0].num_rows):
            score = result_tables[0]["score"][row_idx].as_py()
            lang = result_tables[0]["language"][row_idx].as_py()
            assert score > 2
            assert lang == "en"

    def test_two_branches_with_json_criteria(self):
        """Two branches each using criteria_json split rows correctly."""
        table = make_table()
        branches = [
            make_branch(
                link_id="low",
                link_name="low_score",
                criteria_json={"variable": "score", "operator": "<=", "value": 3},
            ),
            make_branch(
                link_id="high",
                link_name="high_score",
                criteria_json={"variable": "score", "operator": ">", "value": 3},
            ),
        ]
        operator = make_operator(branches)

        result_tables, _ = operator.runner(table)

        assert len(result_tables) == 2
        low_scores = result_tables[0]["score"].to_pylist()
        high_scores = result_tables[1]["score"].to_pylist()
        assert all(s <= 3 for s in low_scores)
        assert all(s > 3 for s in high_scores)


# ---------------------------------------------------------------------------
# 6. Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_empty_table_unconditional_branch_raises(self):
        """
        Empty input table with an unconditional branch raises ValueError.

        PyArrow's Table.from_batches() requires at least one RecordBatch or an
        explicit schema when the table is empty.  The BranchingOperator's
        unconditional path calls pa.Table.from_batches(table.to_batches()),
        which fails for a zero-row table because to_batches() returns [].

        This test documents the known limitation so that if the operator is
        ever fixed to handle empty tables gracefully, the test will need to be
        updated accordingly.
        """
        table = pa.table(
            {
                "id": pa.array([], type=pa.string()),
                "name": pa.array([], type=pa.string()),
                "content": pa.array([], type=pa.string()),
                "score": pa.array([], type=pa.float64()),
                "language": pa.array([], type=pa.string()),
                "word_count": pa.array([], type=pa.int64()),
            }
        )
        branches = [make_branch(link_id="b1", link_name="all")]
        operator = make_operator(branches)

        with pytest.raises(ValueError, match="Must pass schema"):
            operator.runner(table)

    def test_empty_table_conditional_branch(self):
        """Empty input table with conditional branch returns empty output table."""
        table = pa.table(
            {
                "id": pa.array([], type=pa.string()),
                "name": pa.array([], type=pa.string()),
                "content": pa.array([], type=pa.string()),
                "score": pa.array([], type=pa.float64()),
                "language": pa.array([], type=pa.string()),
                "word_count": pa.array([], type=pa.int64()),
            }
        )
        branches = [
            make_branch(link_id="b1", link_name="high", criteria_list=["score > 3"]),
        ]
        operator = make_operator(branches)

        result_tables, _ = operator.runner(table)

        assert len(result_tables) == 1
        assert result_tables[0].num_rows == 0

    def test_single_row_table_matches_branch(self):
        """Single-row table where the row matches the branch condition."""
        table = pa.table(
            {
                "id": ["1"],
                "name": ["doc_1.txt"],
                "content": ["hello"],
                "score": [5.0],
                "language": ["en"],
                "word_count": [100],
            }
        )
        branches = [
            make_branch(link_id="b1", link_name="high", criteria_list=["score > 3"]),
        ]
        operator = make_operator(branches)

        result_tables, _ = operator.runner(table)

        assert result_tables[0].num_rows == 1

    def test_single_row_table_no_match(self):
        """Single-row table where the row does not match the branch condition."""
        table = pa.table(
            {
                "id": ["1"],
                "name": ["doc_1.txt"],
                "content": ["hello"],
                "score": [1.0],
                "language": ["en"],
                "word_count": [100],
            }
        )
        branches = [
            make_branch(link_id="b1", link_name="high", criteria_list=["score > 3"]),
        ]
        operator = make_operator(branches)

        result_tables, _ = operator.runner(table)

        assert result_tables[0].num_rows == 0

    def test_all_rows_match_one_branch_none_match_other(self):
        """
        Two branches where all rows match branch A and none match branch B.
        """
        table = make_table()
        branches = [
            make_branch(link_id="all", link_name="all_rows", criteria_list=["score > 0"]),
            make_branch(link_id="none", link_name="no_rows", criteria_list=["score > 9999"]),
        ]
        operator = make_operator(branches)

        result_tables, _ = operator.runner(table)

        assert result_tables[0].num_rows == table.num_rows
        assert result_tables[1].num_rows == 0

    def test_overlapping_branches_both_get_matching_rows(self):
        """
        Two branches with overlapping criteria both receive the rows that
        satisfy their respective conditions (branching is independent per branch).
        """
        table = make_table()
        # Branch A: score > 2  → rows 3,4,5,6
        # Branch B: score > 4  → rows 5,6  (subset of A)
        branches = [
            make_branch(link_id="a", link_name="above_2", criteria_list=["score > 2"]),
            make_branch(link_id="b", link_name="above_4", criteria_list=["score > 4"]),
        ]
        operator = make_operator(branches)

        result_tables, _ = operator.runner(table)

        assert result_tables[0].num_rows == 4  # score > 2: rows 3,4,5,6
        assert result_tables[1].num_rows == 2  # score > 4: rows 5,6


# ---------------------------------------------------------------------------
# 7. Metadata structure
# ---------------------------------------------------------------------------


class TestMetadata:
    def test_metadata_contains_branches_key(self):
        """runner() metadata always contains a 'branches' dict."""
        table = make_table()
        branches = [
            make_branch(link_id="b1", link_name="high", criteria_list=["score > 3"]),
        ]
        operator = make_operator(branches)

        _, metadata = operator.runner(table)

        assert "branches" in metadata

    def test_metadata_branches_keyed_by_link_id(self):
        """Each branch's metadata is keyed by its link_id."""
        table = make_table()
        branches = [
            make_branch(link_id="low_id", link_name="low", criteria_list=["score <= 3"]),
            make_branch(link_id="high_id", link_name="high", criteria_list=["score > 3"]),
        ]
        operator = make_operator(branches)

        _, metadata = operator.runner(table)

        assert "low_id" in metadata["branches"]
        assert "high_id" in metadata["branches"]

    def test_metadata_branch_contains_expected_keys(self):
        """Each branch metadata entry contains the expected keys."""
        table = make_table()
        branches = [
            make_branch(link_id="b1", link_name="high", criteria_list=["score > 3"]),
        ]
        operator = make_operator(branches)

        _, metadata = operator.runner(table)

        branch_meta = metadata["branches"]["b1"]
        assert "processed_docs" in branch_meta

    def test_metadata_contains_total_docs(self):
        """runner() metadata contains documents_in_scope."""
        table = make_table()
        branches = [make_branch(link_id="b1", link_name="all")]
        operator = make_operator(branches)

        _, metadata = operator.runner(table)

        assert Metrics.External.TOTAL_DOCS in metadata
        assert metadata[Metrics.External.TOTAL_DOCS] == table.num_rows

    def test_metadata_contains_skipped_docs_count(self):
        """runner() metadata contains skipped_docs_count key."""
        table = make_table()
        branches = [
            make_branch(link_id="b1", link_name="high", criteria_list=["score > 3"]),
        ]
        operator = make_operator(branches)

        _, metadata = operator.runner(table)

        assert Metrics.External.SKIPPED_DOCS_COUNT in metadata

    def test_metadata_contains_failed_docs_count(self):
        """runner() metadata contains failed_docs_count key."""
        table = make_table()
        branches = [
            make_branch(link_id="b1", link_name="high", criteria_list=["score > 3"]),
        ]
        operator = make_operator(branches)

        _, metadata = operator.runner(table)

        assert Metrics.External.FAILED_DOCS_COUNT in metadata

    def test_branch_skipped_docs_count_equals_docs_filtered_for_each_branch(self):
        """
        With 5 docs (2 md, 3 txt), two non-overlapping branches must each report
        skipped_docs_count == total_docs - processed_docs for that branch.
        Branch 1 keeps 2 docs  → skipped_docs_count must be 3.
        Branch 2 keeps 3 docs  → skipped_docs_count must be 2 (was incorrectly 0).
        """
        table = pa.table(
            {
                "id": ["1", "2", "3", "4", "5"],
                "name": ["a.md", "b.md", "c.txt", "d.txt", "e.txt"],
                "content": ["md1", "md2", "txt1", "txt2", "txt3"],
                "score": [1.0, 2.0, 3.0, 4.0, 5.0],
                "language": ["en", "en", "en", "en", "en"],
                "word_count": [10, 20, 30, 40, 50],
                "ext": ["md", "md", "txt", "txt", "txt"],
            }
        )
        branches = [
            make_branch(link_id="md_branch", link_name="md_files", criteria_list=["ext = 'md'"]),
            make_branch(link_id="txt_branch", link_name="txt_files", criteria_list=["ext = 'txt'"]),
        ]
        operator = make_operator(branches)

        _, metadata = operator.runner(table)

        md_meta = metadata["branches"]["md_branch"]
        txt_meta = metadata["branches"]["txt_branch"]

        assert md_meta["processed_docs"] == 2
        assert md_meta["skipped_docs_count"] == 3, (
            f"md branch: expected skipped_docs_count=3, got {md_meta['skipped_docs_count']}"
        )

        assert txt_meta["processed_docs"] == 3
        assert txt_meta["skipped_docs_count"] == 2, (
            f"txt branch: expected skipped_docs_count=2, got {txt_meta['skipped_docs_count']}"
        )


# ---------------------------------------------------------------------------
# 8. get_metadata()
# ---------------------------------------------------------------------------


class TestGetMetadata:
    def test_get_metadata_returns_dict(self):
        """get_metadata() returns a dictionary."""
        operator = make_operator([])
        meta = operator.get_metadata()
        assert isinstance(meta, dict)

    def test_get_metadata_label(self):
        """get_metadata() label is 'Branching Operator'."""
        operator = make_operator([])
        meta = operator.get_metadata()
        assert meta[OperatorConstants.Misc.LABEL] == "Branching Operator"

    def test_get_metadata_contains_expected_keys(self):
        """get_metadata() contains CATEGORY, LABEL, ATTRIBUTES, IS_OPERATOR_AVAILABLE."""
        operator = make_operator([])
        meta = operator.get_metadata()
        assert OperatorConstants.Misc.CATEGORY in meta
        assert OperatorConstants.Misc.LABEL in meta
        assert OperatorConstants.Config.ATTRIBUTES in meta
        assert OperatorConstants.Misc.IS_OPERATOR_AVAILABLE in meta

    def test_get_metadata_attributes_has_branch_criteria(self):
        """get_metadata() attributes contain 'branch_criteria' key."""
        operator = make_operator([])
        meta = operator.get_metadata()
        assert "branch_criteria" in meta[OperatorConstants.Config.ATTRIBUTES]

    def test_get_metadata_sdk_true(self):
        """get_metadata() SDK flag is True."""
        operator = make_operator([])
        meta = operator.get_metadata()
        assert meta[OperatorConstants.Misc.SDK] is True

    def test_get_metadata_branch_criteria_items_schema(self):
        """branch_criteria exposes an items schema with properties for all branch object fields."""
        meta = BranchingOperator.get_metadata()
        branch_criteria = meta[OperatorConstants.Config.ATTRIBUTES]["branch_criteria"]
        assert OperatorConstants.Config.ITEMS in branch_criteria
        items = branch_criteria[OperatorConstants.Config.ITEMS]
        assert OperatorConstants.Config.PROPERTIES in items
        properties = items[OperatorConstants.Config.PROPERTIES]
        assert OperatorConstants.Misc.LINK_ID in properties
        assert OperatorConstants.Misc.LINK_NAME in properties
        assert OperatorConstants.Filtering.FILTER_CRITERIA_LIST in properties
        assert OperatorConstants.Filtering.FILTER_CRITERIA_JSON in properties
        assert OperatorConstants.Filtering.FILTER_LOGICAL_OPERATOR_KEY in properties

    def test_get_metadata_branch_criteria_logical_operator_has_valid_values(self):
        """logical_operator item property exposes AND and OR as valid_values."""
        meta = BranchingOperator.get_metadata()
        logical_op = meta[OperatorConstants.Config.ATTRIBUTES]["branch_criteria"][OperatorConstants.Config.ITEMS][
            OperatorConstants.Config.PROPERTIES
        ][OperatorConstants.Filtering.FILTER_LOGICAL_OPERATOR_KEY]
        assert OperatorConstants.Config.VALID_VALUES in logical_op
        assert set(logical_op[OperatorConstants.Config.VALID_VALUES]) == {"AND", "OR"}


# ---------------------------------------------------------------------------
# 9. validate()
# ---------------------------------------------------------------------------


class TestValidate:
    def test_validate_warns_when_only_one_branch(self):
        """validate() warns when there is only one branch (use Filter instead)."""
        branches = [
            make_branch(link_id="b1", link_name="only_branch", criteria_list=["score > 3"]),
        ]
        operator = make_operator(branches)
        errors: list[str] = []
        warnings: list[str] = []
        operator.validate(
            errors,
            warnings,
            available_features=[
                "id",
                "name",
                "content",
                "score",
                "language",
                "word_count",
            ],
        )

        assert len(warnings) > 0, "Expected a warning for single-branch configuration"

    def test_validate_no_errors_for_valid_two_branch_config(self):
        """validate() produces no errors for a valid two-branch configuration."""
        branches = [
            make_branch(link_id="b1", link_name="low", criteria_list=["score <= 3"]),
            make_branch(link_id="b2", link_name="high", criteria_list=["score > 3"]),
        ]
        operator = make_operator(branches)
        errors: list[str] = []
        warnings: list[str] = []
        operator.validate(
            errors,
            warnings,
            available_features=[
                "id",
                "name",
                "content",
                "score",
                "language",
                "word_count",
            ],
        )

        assert len(errors) == 0, f"Unexpected errors: {errors}"

    def test_validate_error_when_branch_missing_link_id(self):
        """validate() adds an error when a branch is missing its link_id."""
        branches = [
            {
                OperatorConstants.Misc.LINK_NAME: "no_id_branch",
                OperatorConstants.Filtering.FILTER_CRITERIA_LIST: ["score > 3"],
                OperatorConstants.Filtering.FILTER_LOGICAL_OPERATOR_KEY: "AND",
                # No LINK_ID
            },
            make_branch(link_id="b2", link_name="other", criteria_list=["score <= 3"]),
        ]
        operator = make_operator(branches)
        errors: list[str] = []
        warnings: list[str] = []
        operator.validate(
            errors,
            warnings,
            available_features=[
                "id",
                "name",
                "content",
                "score",
                "language",
                "word_count",
            ],
        )

        assert len(errors) > 0, "Expected an error for missing link_id"
        error_messages = [str(e) for e in errors]
        assert any("Branch Id" in msg or "branch" in msg.lower() for msg in error_messages)

    def test_validate_error_for_invalid_logical_operator(self):
        """validate() adds an error for an invalid logical operator."""
        branches = [
            {
                OperatorConstants.Misc.LINK_ID: "b1",
                OperatorConstants.Misc.LINK_NAME: "bad_op",
                "logical_operator": "XOR",  # invalid
                OperatorConstants.Filtering.FILTER_CRITERIA_LIST: ["score > 3"],
            },
            make_branch(link_id="b2", link_name="other", criteria_list=["score <= 3"]),
        ]
        operator = make_operator(branches)
        errors: list[str] = []
        warnings: list[str] = []
        operator.validate(
            errors,
            warnings,
            available_features=[
                "id",
                "name",
                "content",
                "score",
                "language",
                "word_count",
            ],
        )

        assert len(errors) > 0, "Expected an error for invalid logical operator 'XOR'"

    def test_validate_unconditional_branching_no_errors(self):
        """validate() produces no errors for valid unconditional branching."""
        branches = [
            make_branch(link_id="b1", link_name="copy_a"),
            make_branch(link_id="b2", link_name="copy_b"),
        ]
        operator = make_operator(branches)
        errors: list[str] = []
        warnings: list[str] = []
        operator.validate(errors, warnings, available_features=["id", "name", "content", "score"])

        assert len(errors) == 0, f"Unexpected errors: {errors}"


# ---------------------------------------------------------------------------
# 10. transform() — delegates to runner()
# ---------------------------------------------------------------------------


class TestTransform:
    def test_transform_returns_same_result_as_runner(self):
        """transform() produces the same output as runner() for the same input."""
        table = make_table()
        branches = [
            make_branch(link_id="b1", link_name="high", criteria_list=["score > 3"]),
        ]
        operator = make_operator(branches)

        runner_tables, _ = operator.runner(table)
        transform_tables, _ = operator.transform(table)

        assert len(runner_tables) == len(transform_tables)
        assert runner_tables[0].num_rows == transform_tables[0].num_rows

    def test_transform_returns_list_of_tables_and_dict(self):
        """transform() returns (list[pa.Table], dict)."""
        table = make_table()
        branches = [make_branch(link_id="b1", link_name="all")]
        operator = make_operator(branches)

        result = operator.transform(table)

        assert isinstance(result, tuple)
        assert len(result) == 2
        tables, metadata = result
        assert isinstance(tables, list)
        assert isinstance(metadata, dict)
        assert all(isinstance(t, pa.Table) for t in tables)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


# ---------------------------------------------------------------------------
# 11. validate() — remaining rules
# ---------------------------------------------------------------------------

FEATURES = ["id", "name", "content", "score", "language", "word_count"]


def _validate(operator: BranchingOperator) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    operator.validate(errors, warnings, available_features=FEATURES)
    return errors, warnings


class TestValidateRules:
    def test_validation_is_deferred_while_validating_the_flow(self):
        operator = BranchingOperator({"validating_flow": True, "branches": []})

        assert _validate(operator) == ([], [])

    def test_missing_branches_is_an_error(self):
        errors, _ = _validate(make_operator([]))

        assert errors == ["branch_criteria parameter is missing"]

    def test_unconditional_branches_with_empty_json_criteria_skip_criteria_checks(self):
        branches = [
            make_branch(link_id="b1", link_name="copy_a", criteria_json={"criteria_list": []}),
            make_branch(link_id="b2", link_name="copy_b", criteria_json={"criteria_list": []}),
        ]

        assert _validate(make_operator(branches)) == ([], [])

    def test_json_criteria_with_unknown_column(self):
        branches = [
            make_branch(
                link_id="b1", link_name="high", criteria_json={"variable": "rank", "operator": ">", "value": 3}
            ),
            make_branch(link_id="b2", link_name="rest", criteria_list=["score <= 3"]),
        ]

        errors, _ = _validate(make_operator(branches))

        assert len(errors) == 1
        assert errors[0].startswith("Invalid features in filter criteria - rank.")

    def test_blank_criteria_entries_are_ignored(self):
        branches = [
            make_branch(link_id="b1", link_name="high", criteria_list=["  ", "score > 3"]),
            make_branch(link_id="b2", link_name="low", criteria_list=["score <= 3"]),
        ]

        assert _validate(make_operator(branches))[0] == []

    @pytest.mark.parametrize(
        ("criteria", "message"),
        [
            ("rank > 3", "invalid features found: {'rank'}"),
            ("score > 3; DROP TABLE t", "Please use valid criteria expression"),
            ("score%2 = 0", "Please use valid criteria expression"),
            ("score >", "Please use valid criteria expression"),
        ],
        ids=["unknown-column", "statement-separator", "modulo", "parse-error"],
    )
    def test_invalid_criteria_expression(self, criteria, message):
        branches = [
            make_branch(link_id="b1", link_name="first", criteria_list=[criteria]),
            make_branch(link_id="b2", link_name="second", criteria_list=["score <= 3"]),
        ]

        errors, _ = _validate(make_operator(branches))

        assert len(errors) == 1
        assert errors[0].startswith(f"Invalid branching criteria expression: {criteria},")
        assert message in errors[0]


class TestAnalyzeWhereClause:
    @pytest.mark.parametrize(
        ("clause", "expected"),
        [
            ("score > 3 AND language = 'en'", (True, ["score", "language"])),
            ("t.score > 3 AND score < 9", (True, ["score"])),
            ("   ", (False, [])),
            (f"{'x' * 129} = 1", (True, [])),
        ],
        ids=["columns", "qualified-and-duplicate", "blank", "name-too-long"],
    )
    def test_analyze_where_clause(self, clause, expected):
        assert make_operator([]).analyze_where_clause(clause_str=clause) == expected


# ---------------------------------------------------------------------------
# 12. Skipped and failed documents across branches
# ---------------------------------------------------------------------------


class TestSkippedAndFailedDocsAcrossBranches:
    """A document counts as skipped or failed only if every branch skipped or failed it."""

    def test_doc_skipped_by_one_branch_but_kept_by_another_is_not_skipped(self):
        branches = [
            make_branch(link_id="b1", link_name="high", criteria_list=["score > 3"]),
            make_branch(link_id="b2", link_name="all", criteria_list=["score > 0"]),
        ]

        _, metadata = make_operator(branches).runner(make_table())

        assert metadata[Metrics.External.SKIPPED_DOCS_COUNT] == 0

    # Without a "name" column the SQL filter cannot list the documents it filters out, so a
    # branch that drops rows fails all of its documents; a branch that keeps every row does not.

    def test_docs_failing_in_every_branch_are_failed(self):
        branches = [
            make_branch(link_id="b1", link_name="high", criteria_list=["score > 3"]),
            make_branch(link_id="b2", link_name="low", criteria_list=["score <= 3"]),
        ]

        _, metadata = make_operator(branches).runner(make_table().drop_columns(["name"]))

        assert metadata[Metrics.External.FAILED_DOCS_COUNT] == 6

    def test_docs_failing_in_only_one_branch_are_not_failed(self):
        branches = [
            make_branch(link_id="b1", link_name="high", criteria_list=["score > 3"]),
            make_branch(link_id="b2", link_name="all", criteria_list=["score > 0"]),
        ]

        _, metadata = make_operator(branches).runner(make_table().drop_columns(["name"]))

        assert metadata[Metrics.External.FAILED_DOCS_COUNT] == 0


# ---------------------------------------------------------------------------
# 13. Tables without an id column
# ---------------------------------------------------------------------------


class TestTablesWithoutIdColumn:
    @pytest.mark.parametrize(
        "branch",
        [
            make_branch(link_id="b1", link_name="copy"),
            make_branch(link_id="b1", link_name="high", criteria_list=["score > 3"]),
        ],
        ids=["unconditional", "conditional"],
    )
    def test_branches_without_id_column_count_no_processed_docs(self, branch):
        table = make_table().drop_columns(["id"])

        result_tables, metadata = make_operator([branch]).runner(table)

        assert result_tables[0].num_rows > 0
        assert metadata[Metrics.External.PROCESSED_DOCS] == 0

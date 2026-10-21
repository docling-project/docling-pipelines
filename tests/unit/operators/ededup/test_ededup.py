"""Ededup operator, shared admission, and storage configuration unit tests."""

import ast
import inspect
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pyarrow as pa
import pytest
import yaml
from data_processing.test_support import get_tables_in_folder
from data_processing.test_support.transform import AbstractTableTransformTest
from dpk_ededup import (
    EdedupTransform,
    HashFilter,
    doc_column_name_key,
    int_column_name_key,
)

from docpipe.core.constants.constants import Metrics
from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.core.incremental_metadata import FilesystemIncrementalMetadataStore
from docpipe.core.models.session_info import SessionInfo, session_info_var
from docpipe.core.operators.quality import ededup
from docpipe.core.operators.quality.ededup import EdedupOperator
from docpipe.core.operators.quality.ededup_storage import factory
from docpipe.core.operators.quality.ededup_storage.adapters.filesystem_store import FilesystemEdedupStore
from docpipe.core.operators.quality.ededup_storage.factory import EdedupStoreFactory
from docpipe.exceptions.docpipe_exceptions import DocpipeException, FlowExecutionFailedException

# from dpk_ededup.transform_python import EdedupTransform
# from docpipe_core.operators.quality.ededup import EdedupOperator


@pytest.fixture(autouse=True)
def isolate_session_info():
    """Prevent job/run context from leaking in from other test modules."""
    token = session_info_var.set(SessionInfo())
    yield
    session_info_var.reset(token)


class TestEdedupTransformFromParquetFile(AbstractTableTransformTest):
    """
    Extends the super-class to define the test data for the tests defined there.
    The name of this class MUST begin with the word Test so that pytest recognizes it as a test class.
    """

    def get_test_transform_fixtures(self) -> list[tuple]:
        # Use the correct path relative to the test file location
        basedir = Path(__file__).resolve().parent / "../../../fixtures"
        input_dir = str(basedir / "ededup_input")
        expected_dir = str(basedir / "ededup_expected")

        # Create directories if they don't exist
        Path(input_dir).mkdir(parents=True, exist_ok=True)
        Path(expected_dir).mkdir(parents=True, exist_ok=True)

        input_tables = get_tables_in_folder(input_dir)
        expected_tables = get_tables_in_folder(expected_dir)

        # Ensure fixture files are present — fail fast with a clear message if not
        assert len(input_tables) > 0, f"No input parquet files found in {input_dir}"
        assert len(expected_tables) > 0, f"No expected parquet files found in {expected_dir}"
        expected_metadata_list = [
            {
                "result_documents": 3,
                "source_documents": 5,
                "removed_documents": [
                    "c86996cf20920d0955a38580abb650b00d0e1df5f7bd98646669561fd89c1627",
                    "3e4d6c6c89dd166c88d79a6cbe3d90c8db2c9847fca19893409ec29434643c3d",
                ],
            },
            {},
        ]  # pragma: allowlist secret
        # Expected metadata should be produced for each transform call plus a final flush
        assert len(expected_metadata_list) == len(input_tables) + 1, (
            f"Expected metadata list length ({len(expected_metadata_list)}) does not match number of input tables plus flush ({len(input_tables) + 1})"
        )
        config = {
            doc_column_name_key: "contents",
            int_column_name_key: "document_id",
            "filter": HashFilter({}),
        }
        return [
            (
                EdedupTransform(config),
                input_tables,
                expected_tables,
                expected_metadata_list,
            ),
        ]


class TestDocpipeEdedupOperator(unittest.TestCase):
    def test_init(self):
        config = {"doc_column": "content", "doc_id_hash_column": "doc_id_hash"}
        operator = EdedupOperator(config)
        self.assertIsNotNone(operator, "Ededup Operator is not None")

    def test_ededup_transform_from_table(self):
        # 1. Create a Pyarrow table
        content = ["Document content 1", "Document content 1", "Document content 3"]
        doc_id_hash = [str(101), str(102), str(103)]
        name = ["Doc 1", "Doc 2", "Doc 3"]

        data = {
            OperatorConstants.Columns.ID: doc_id_hash,
            OperatorConstants.Columns.DOC_COLUMN_DEFAULT: content,
            OperatorConstants.Columns.DOC_ID_HASH_DEFAULT: doc_id_hash,
            OperatorConstants.Columns.NAME: name,
        }
        input_table = pa.table(data)

        # 2. Using the output of local ingest into the ededup_input for the ededup transform
        ededup_operator = EdedupOperator(
            {
                OperatorConstants.Columns.DOC_COLUMN: OperatorConstants.Columns.DOC_COLUMN_DEFAULT,
                OperatorConstants.Columns.DOC_ID_HASH_DEFAULT: OperatorConstants.Columns.DOC_ID_HASH_DEFAULT,
            }
        )

        # 3. Create Expected MetaData
        expected_metadata = {
            Metrics.External.TOTAL_DOCS: 3,
            Metrics.External.PROCESSED_DOCS: 2,
            Metrics.External.FAILED_DOCS_COUNT: 0,
            Metrics.External.FAILED_DOCS: [],
            Metrics.External.SKIPPED_DOCS: [
                {
                    "id": "102",
                    "name": "Doc 2",
                    "reason": "This document was identified as a duplicate and removed.",
                    "document_url": "",
                }
            ],
            Metrics.External.SKIPPED_DOCS_COUNT: 1,
            Metrics.External.REMOVED_DOCUMENTS: 1,
            Metrics.External.NODE_STATUS: "Completed",
        }

        _, metadata = ededup_operator.transform(input_table)

        # 4. Perform Assertions
        assert metadata == expected_metadata


def test_operator_metadata():
    """Test that operator returns correct metadata"""
    ededup_operator = EdedupOperator({})

    operator_metadata = ededup_operator.get_metadata()

    expected_operator_metadata = {
        "category": "Quality",
        "description": "Exact deduplication operator that removes duplicate documents based on content hash",
        "is_operator_available": True,
        "label": "De-duplicator",
    }

    assert operator_metadata == expected_operator_metadata, "Ededup Operator metadata mismatch"


class TestEdedupOperatorEdgeCases(unittest.TestCase):
    """Test edge cases and error handling for EdedupOperator"""

    def test_empty_table(self):
        """Test deduplication with an empty table"""
        # Create empty table with correct schema
        data: dict[str, list] = {
            OperatorConstants.Columns.ID: [],
            OperatorConstants.Columns.DOC_COLUMN_DEFAULT: [],
            OperatorConstants.Columns.DOC_ID_HASH_DEFAULT: [],
            OperatorConstants.Columns.NAME: [],
        }
        empty_table = pa.table(data)

        operator = EdedupOperator(
            {
                OperatorConstants.Columns.DOC_COLUMN: OperatorConstants.Columns.DOC_COLUMN_DEFAULT,
                OperatorConstants.Columns.DOC_ID_HASH_DEFAULT: OperatorConstants.Columns.DOC_ID_HASH_DEFAULT,
            }
        )

        result_tables, metadata = operator.transform(empty_table)

        # Should return empty table
        self.assertEqual(result_tables[0].num_rows, 0)
        self.assertEqual(metadata[Metrics.External.TOTAL_DOCS], 0)
        self.assertEqual(metadata[Metrics.External.PROCESSED_DOCS], 0)

    def test_no_duplicates(self):
        """Test when all documents are unique (no duplicates)"""
        content = ["Document 1", "Document 2", "Document 3", "Document 4"]
        doc_id_hash = [str(i) for i in range(101, 105)]
        name = [f"Doc {i}" for i in range(1, 5)]

        data = {
            OperatorConstants.Columns.ID: doc_id_hash,
            OperatorConstants.Columns.DOC_COLUMN_DEFAULT: content,
            OperatorConstants.Columns.DOC_ID_HASH_DEFAULT: doc_id_hash,
            OperatorConstants.Columns.NAME: name,
        }
        input_table = pa.table(data)

        operator = EdedupOperator(
            {
                OperatorConstants.Columns.DOC_COLUMN: OperatorConstants.Columns.DOC_COLUMN_DEFAULT,
                OperatorConstants.Columns.DOC_ID_HASH_DEFAULT: OperatorConstants.Columns.DOC_ID_HASH_DEFAULT,
            }
        )

        result_tables, metadata = operator.transform(input_table)

        # All documents should remain
        self.assertEqual(result_tables[0].num_rows, 4)
        self.assertEqual(metadata[Metrics.External.TOTAL_DOCS], 4)
        self.assertEqual(metadata[Metrics.External.PROCESSED_DOCS], 4)
        self.assertEqual(metadata[Metrics.External.SKIPPED_DOCS_COUNT], 0)
        self.assertEqual(metadata[Metrics.External.REMOVED_DOCUMENTS], 0)

    def test_all_duplicates(self):
        """Test when all documents are identical"""
        content = ["Same content"] * 5
        doc_id_hash = [str(i) for i in range(101, 106)]
        name = [f"Doc {i}" for i in range(1, 6)]

        data = {
            OperatorConstants.Columns.ID: doc_id_hash,
            OperatorConstants.Columns.DOC_COLUMN_DEFAULT: content,
            OperatorConstants.Columns.DOC_ID_HASH_DEFAULT: doc_id_hash,
            OperatorConstants.Columns.NAME: name,
        }
        input_table = pa.table(data)

        operator = EdedupOperator(
            {
                OperatorConstants.Columns.DOC_COLUMN: OperatorConstants.Columns.DOC_COLUMN_DEFAULT,
                OperatorConstants.Columns.DOC_ID_HASH_DEFAULT: OperatorConstants.Columns.DOC_ID_HASH_DEFAULT,
            }
        )

        result_tables, metadata = operator.transform(input_table)

        # Only first occurrence should remain
        self.assertEqual(result_tables[0].num_rows, 1)
        self.assertEqual(metadata[Metrics.External.TOTAL_DOCS], 5)
        self.assertEqual(metadata[Metrics.External.PROCESSED_DOCS], 1)
        self.assertEqual(metadata[Metrics.External.SKIPPED_DOCS_COUNT], 4)
        self.assertEqual(metadata[Metrics.External.REMOVED_DOCUMENTS], 4)

    def test_none_table(self):
        """Test handling of None table input"""
        operator = EdedupOperator(
            {
                OperatorConstants.Columns.DOC_COLUMN: OperatorConstants.Columns.DOC_COLUMN_DEFAULT,
                OperatorConstants.Columns.DOC_ID_HASH_DEFAULT: OperatorConstants.Columns.DOC_ID_HASH_DEFAULT,
            }
        )

        result_tables, _ = operator.transform(None)

        # Should handle gracefully and return None in output
        self.assertIsNone(result_tables[0])

    def test_custom_column_names(self):
        """Test with custom column names"""
        custom_doc_col = "my_content"
        custom_hash_col = "my_hash"

        content = ["Doc 1", "Doc 1", "Doc 2"]
        doc_id_hash = ["hash1", "hash2", "hash3"]
        name = ["Name 1", "Name 2", "Name 3"]

        data = {
            OperatorConstants.Columns.ID: doc_id_hash,
            custom_doc_col: content,
            custom_hash_col: doc_id_hash,
            OperatorConstants.Columns.NAME: name,
        }
        input_table = pa.table(data)

        operator = EdedupOperator(
            {
                OperatorConstants.Columns.DOC_COLUMN: custom_doc_col,
                OperatorConstants.Columns.DOC_ID_HASH: custom_hash_col,
            }
        )

        result_tables, metadata = operator.transform(input_table)

        # Should process with custom columns
        self.assertEqual(result_tables[0].num_rows, 2)
        self.assertEqual(metadata[Metrics.External.TOTAL_DOCS], 3)
        self.assertEqual(metadata[Metrics.External.PROCESSED_DOCS], 2)

    def test_output_table_structure(self):
        """Test that output table maintains correct structure"""
        content = ["Doc 1", "Doc 2"]
        doc_id_hash = ["101", "102"]
        name = ["Name 1", "Name 2"]

        data = {
            OperatorConstants.Columns.ID: doc_id_hash,
            OperatorConstants.Columns.DOC_COLUMN_DEFAULT: content,
            OperatorConstants.Columns.DOC_ID_HASH_DEFAULT: doc_id_hash,
            OperatorConstants.Columns.NAME: name,
        }
        input_table = pa.table(data)

        operator = EdedupOperator(
            {
                OperatorConstants.Columns.DOC_COLUMN: OperatorConstants.Columns.DOC_COLUMN_DEFAULT,
                OperatorConstants.Columns.DOC_ID_HASH_DEFAULT: OperatorConstants.Columns.DOC_ID_HASH_DEFAULT,
            }
        )

        result_tables, _ = operator.transform(input_table)
        result_table = result_tables[0]

        # Verify output table has same columns as input
        self.assertEqual(set(result_table.column_names), set(input_table.column_names))
        # Verify output table has correct schema
        self.assertEqual(result_table.schema, input_table.schema)

    def test_metadata_completeness(self):
        """Test that all required metadata fields are present"""
        content = ["Doc 1", "Doc 1", "Doc 2"]
        doc_id_hash = ["101", "102", "103"]
        name = ["Name 1", "Name 2", "Name 3"]

        data = {
            OperatorConstants.Columns.ID: doc_id_hash,
            OperatorConstants.Columns.DOC_COLUMN_DEFAULT: content,
            OperatorConstants.Columns.DOC_ID_HASH_DEFAULT: doc_id_hash,
            OperatorConstants.Columns.NAME: name,
        }
        input_table = pa.table(data)

        operator = EdedupOperator(
            {
                OperatorConstants.Columns.DOC_COLUMN: OperatorConstants.Columns.DOC_COLUMN_DEFAULT,
                OperatorConstants.Columns.DOC_ID_HASH_DEFAULT: OperatorConstants.Columns.DOC_ID_HASH_DEFAULT,
            }
        )

        _, metadata = operator.transform(input_table)

        # Verify all required metadata fields are present
        required_fields = [
            Metrics.External.TOTAL_DOCS,
            Metrics.External.PROCESSED_DOCS,
            Metrics.External.FAILED_DOCS_COUNT,
            Metrics.External.FAILED_DOCS,
            Metrics.External.SKIPPED_DOCS_COUNT,
            Metrics.External.SKIPPED_DOCS,
            Metrics.External.REMOVED_DOCUMENTS,
            Metrics.External.NODE_STATUS,
        ]

        for field in required_fields:
            self.assertIn(field, metadata, f"Missing required metadata field: {field}")

    def test_single_document(self):
        """Test with a single document (edge case)"""
        content = ["Single document"]
        doc_id_hash = ["101"]
        name = ["Doc 1"]

        data = {
            OperatorConstants.Columns.ID: doc_id_hash,
            OperatorConstants.Columns.DOC_COLUMN_DEFAULT: content,
            OperatorConstants.Columns.DOC_ID_HASH_DEFAULT: doc_id_hash,
            OperatorConstants.Columns.NAME: name,
        }
        input_table = pa.table(data)

        operator = EdedupOperator(
            {
                OperatorConstants.Columns.DOC_COLUMN: OperatorConstants.Columns.DOC_COLUMN_DEFAULT,
                OperatorConstants.Columns.DOC_ID_HASH_DEFAULT: OperatorConstants.Columns.DOC_ID_HASH_DEFAULT,
            }
        )

        result_tables, metadata = operator.transform(input_table)

        # Single document should pass through
        self.assertEqual(result_tables[0].num_rows, 1)
        self.assertEqual(metadata[Metrics.External.TOTAL_DOCS], 1)
        self.assertEqual(metadata[Metrics.External.PROCESSED_DOCS], 1)
        self.assertEqual(metadata[Metrics.External.SKIPPED_DOCS_COUNT], 0)

    def test_multiple_duplicate_groups(self):
        """Test with multiple groups of duplicates"""
        content = ["Doc A", "Doc A", "Doc B", "Doc B", "Doc C"]
        doc_id_hash = [str(i) for i in range(101, 106)]
        name = [f"Name {i}" for i in range(1, 6)]

        data = {
            OperatorConstants.Columns.ID: doc_id_hash,
            OperatorConstants.Columns.DOC_COLUMN_DEFAULT: content,
            OperatorConstants.Columns.DOC_ID_HASH_DEFAULT: doc_id_hash,
            OperatorConstants.Columns.NAME: name,
        }
        input_table = pa.table(data)

        operator = EdedupOperator(
            {
                OperatorConstants.Columns.DOC_COLUMN: OperatorConstants.Columns.DOC_COLUMN_DEFAULT,
                OperatorConstants.Columns.DOC_ID_HASH_DEFAULT: OperatorConstants.Columns.DOC_ID_HASH_DEFAULT,
            }
        )

        result_tables, metadata = operator.transform(input_table)

        # Should keep first of each duplicate group: Doc A, Doc B, Doc C
        self.assertEqual(result_tables[0].num_rows, 3)
        self.assertEqual(metadata[Metrics.External.TOTAL_DOCS], 5)
        self.assertEqual(metadata[Metrics.External.PROCESSED_DOCS], 3)
        self.assertEqual(metadata[Metrics.External.SKIPPED_DOCS_COUNT], 2)
        self.assertEqual(metadata[Metrics.External.REMOVED_DOCUMENTS], 2)

    def test_cross_batch_deduplication(self):
        """Test that duplicates are detected across multiple transform() calls (cross-batch ededup).
        This verifies that _ededup_transform is reused across calls and hash state is preserved.
        """
        operator = EdedupOperator(
            {
                OperatorConstants.Columns.DOC_COLUMN: OperatorConstants.Columns.DOC_COLUMN_DEFAULT,
                OperatorConstants.Columns.DOC_ID_HASH_DEFAULT: OperatorConstants.Columns.DOC_ID_HASH_DEFAULT,
            }
        )

        # Batch 1: Doc A, Doc B — both unique
        batch1 = pa.table(
            {
                OperatorConstants.Columns.ID: ["101", "102"],
                OperatorConstants.Columns.DOC_COLUMN_DEFAULT: ["Doc A", "Doc B"],
                OperatorConstants.Columns.DOC_ID_HASH_DEFAULT: ["101", "102"],
                OperatorConstants.Columns.NAME: ["Name 1", "Name 2"],
            }
        )
        result1, _ = operator.transform(batch1)
        self.assertEqual(result1[0].num_rows, 2, "Batch 1: both docs should pass through")

        # Batch 2: Doc C (new), Doc A (duplicate of Batch 1)
        batch2 = pa.table(
            {
                OperatorConstants.Columns.ID: ["103", "104"],
                OperatorConstants.Columns.DOC_COLUMN_DEFAULT: ["Doc C", "Doc A"],
                OperatorConstants.Columns.DOC_ID_HASH_DEFAULT: ["103", "104"],
                OperatorConstants.Columns.NAME: ["Name 3", "Name 4"],
            }
        )
        result2, metadata2 = operator.transform(batch2)
        self.assertEqual(result2[0].num_rows, 1, "Batch 2: Doc A is a cross-batch duplicate and should be removed")
        self.assertEqual(metadata2[Metrics.External.SKIPPED_DOCS_COUNT], 1)
        self.assertEqual(metadata2[Metrics.External.REMOVED_DOCUMENTS], 1)

        # Batch 3: Doc B (duplicate of Batch 1), Doc D (new)
        batch3 = pa.table(
            {
                OperatorConstants.Columns.ID: ["105", "106"],
                OperatorConstants.Columns.DOC_COLUMN_DEFAULT: ["Doc B", "Doc D"],
                OperatorConstants.Columns.DOC_ID_HASH_DEFAULT: ["105", "106"],
                OperatorConstants.Columns.NAME: ["Name 5", "Name 6"],
            }
        )
        result3, metadata3 = operator.transform(batch3)
        self.assertEqual(result3[0].num_rows, 1, "Batch 3: Doc B is a cross-batch duplicate and should be removed")
        self.assertEqual(metadata3[Metrics.External.SKIPPED_DOCS_COUNT], 1)
        self.assertEqual(metadata3[Metrics.External.REMOVED_DOCUMENTS], 1)

    def test_standalone_instances_do_not_share_hashes(self):
        """Context-free library callers must not collide in a shared null run."""
        operator = EdedupOperator({})

        batch = pa.table(
            {
                OperatorConstants.Columns.ID: ["101"],
                OperatorConstants.Columns.DOC_COLUMN_DEFAULT: ["Doc A"],
                OperatorConstants.Columns.DOC_ID_HASH_DEFAULT: ["101"],
                OperatorConstants.Columns.NAME: ["Name 1"],
            }
        )
        assert operator.transform(batch)[0][0].num_rows == 1
        assert operator.transform(batch)[0][0].num_rows == 0
        assert EdedupOperator({}).transform(batch)[0][0].num_rows == 1


def _table(*, ids, contents):
    return pa.table({"id": ids, "name": ids, "doc_id_hash": ids, "content": contents})


def _operator(*, run="run-a", node="ededup-a", job="job"):
    return EdedupOperator({"job_id": job, "job_run_id": run, "id": node})


@pytest.fixture
def shared_store(tmp_path, monkeypatch):
    store = FilesystemEdedupStore(config={"base_dir": str(tmp_path)})
    factory = Mock()
    factory.get_store.return_value = store
    monkeypatch.setattr("docpipe.core.operators.quality.ededup.get_default_ededup_factory", lambda: factory)
    return store


def test_independent_batches_and_scopes(shared_store):
    first = _table(ids=["old.txt", "copy.txt"], contents=["Hello, world!", "hello world"])
    assert _operator().transform(first)[0][0]["id"].to_pylist() == ["old.txt"]
    renamed = _table(ids=["new.txt"], contents=["Hello, world!"])
    assert _operator().transform(renamed)[0][0].num_rows == 0
    assert _operator(run="run-b").transform(renamed)[0][0].num_rows == 1
    # A later batch in A remains a duplicate even after B has admitted the hash.
    assert _operator().transform(renamed)[0][0].num_rows == 0
    assert _operator(node="ededup-b").transform(renamed)[0][0].num_rows == 1
    assert _operator(job="another-job").transform(renamed)[0][0].num_rows == 1


def test_parallel_instances_admit_one_representative(shared_store):
    def execute(index):
        return _operator().transform(_table(ids=[str(index)], contents=["same"]))[0][0].num_rows

    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(execute, range(16))) == 1


def test_repeated_document_ids_use_row_identity(shared_store):
    result, metadata = _operator().transform(_table(ids=["same-id"] * 3, contents=["a", "a", "b"]))
    assert result[0]["content"].to_pylist() == ["a", "b"]
    assert metadata[Metrics.External.SKIPPED_DOCS_COUNT] == 1
    assert len(metadata[Metrics.External.SKIPPED_DOCS]) == 1


def test_store_error_propagates(shared_store, monkeypatch):
    def fail(**kwargs):
        raise RuntimeError("storage unavailable")

    monkeypatch.setattr(shared_store, "check_and_register_hashes", fail)
    with pytest.raises(RuntimeError, match="storage unavailable"):
        _operator().transform(_table(ids=["a"], contents=["a"]))


def test_partial_scope_fails_instead_of_falling_back():
    operator = EdedupOperator({"job_id": "job", "job_run_id": "run"})
    with pytest.raises(ValueError, match="flow node id"):
        operator.transform(_table(ids=["a"], contents=["a"]))


def test_local_duplicates_are_sent_as_one_bulk_call(shared_store, monkeypatch):
    register = Mock(wraps=shared_store.check_and_register_hashes)
    monkeypatch.setattr(shared_store, "check_and_register_hashes", register)
    _operator().transform(_table(ids=["a", "b", "c"], contents=["one", "one", "two"]))
    register.assert_called_once()
    assert len(register.call_args.kwargs["records"]) == 2


def test_invalid_backend_configuration_is_not_silently_local(tmp_path, monkeypatch):
    from docpipe.core.operators.quality.ededup_storage.factory import EdedupStoreFactory
    from docpipe.exceptions.docpipe_exceptions import DocpipeException

    config = tmp_path / "config.yaml"
    config.write_text("ededup:\n  storage:\n    type: misspelled-postgres\n")
    monkeypatch.setenv("DOCPIPE_CONFIG_PATH", str(config))
    with pytest.raises(DocpipeException, match="Invalid storage backend"):
        EdedupStoreFactory.from_default_sources()


@pytest.mark.parametrize("config", [{"job_id": "job", "id": "node"}, {"job_run_id": "run", "id": "node"}])
def test_incomplete_job_run_context(config):
    with pytest.raises(ValueError, match="Shared ededup requires"):
        EdedupOperator(config).transform(_table(ids=["a"], contents=["a"]))


def test_empty_shared_batch_does_not_register(shared_store, monkeypatch):
    register = Mock(wraps=shared_store.check_and_register_hashes)
    monkeypatch.setattr(shared_store, "check_and_register_hashes", register)
    table = _table(ids=[], contents=[])
    result, metadata = _operator().transform(table)
    assert result[0].equals(table)
    assert metadata[Metrics.External.REMOVED_DOCUMENTS] == 0
    register.assert_not_called()


def test_output_order_schema_and_skipped_source_metadata(shared_store):
    table = _table(ids=["first", "copy", "last"], contents=["Hello!", "hello", "other"])
    table = table.append_column("path", pa.array(["/first", "/copy", "/last"]))
    result, metadata = _operator().transform(table)
    assert result[0].equals(table.take([0, 2]))
    assert metadata[Metrics.External.TOTAL_DOCS] == 3
    assert metadata[Metrics.External.PROCESSED_DOCS] == 2
    assert metadata[Metrics.External.SKIPPED_DOCS_COUNT] == 1
    skipped = metadata[Metrics.External.SKIPPED_DOCS][0]
    assert skipped["document_url"] == "/copy"


def test_downstream_failure_does_not_release_admission(shared_store):
    table = _table(ids=["a"], contents=["content"])
    with pytest.raises(RuntimeError, match="downstream"):
        assert _operator().transform(table)[0][0].num_rows == 1
        raise RuntimeError("downstream failed after admission")
    assert _operator().transform(table)[0][0].num_rows == 0
    assert _operator(run="retry-run").transform(table)[0][0].num_rows == 1


def test_filesystem_reopen_retains_branch_run_and_job_records(tmp_path):
    import pyarrow.parquet as pq

    config = {"base_dir": str(tmp_path)}
    store = FilesystemEdedupStore(config=config)
    scopes = [
        {"job_id": "job", "node_id": "branch-a", "job_run_id": "run-a"},
        {"job_id": "job", "node_id": "branch-b", "job_run_id": "run-a"},
        {"job_id": "job", "node_id": "branch-a", "job_run_id": "run-b"},
        {"job_id": "other", "node_id": "branch-a", "job_run_id": "run-a"},
    ]
    for index, scope in enumerate(scopes):
        assert store.check_and_register_hashes(**scope, records={"h": f"original-{index}"}) == {"h"}
    reopened = FilesystemEdedupStore(config=config)
    for scope in scopes:
        assert reopened.check_and_register_hashes(**scope, records={"h": "renamed"}) == set()
    records = [
        row for path in tmp_path.glob("ededup_registry/hashes_*.parquet") for row in pq.read_table(path).to_pylist()
    ]
    assert len(records) == 4
    assert {row["doc_id"] for row in records} == {f"original-{index}" for index in range(4)}
    assert reopened.check_and_register_hashes(
        job_id="job", node_id="branch-b", job_run_id="run-b", records={"h": "renamed"}
    ) == {"h"}


def test_config_precedence_and_nested_defaults(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "global_storage": {"type": "postgresql", "config": {"postgres": {"host": "shared", "schema": "old"}}},
                "ededup": {"storage": {"config": {"postgres": {"schema": "ededup"}}}},
                "incremental_metadata": {"storage": {"type": "invalid"}},
            }
        )
    )
    selected = EdedupStoreFactory.from_config_file(str(path))
    assert selected.backend == "postgresql"
    assert selected.config == {"postgres": {"host": "shared", "schema": "ededup"}}
    path.write_text(
        yaml.safe_dump(
            {
                "global_storage": {"type": "postgresql"},
                "ededup": {"storage": {"type": "filesystem", "config": {"base_dir": str(tmp_path / "ededup")}}},
            }
        )
    )
    selected = EdedupStoreFactory.from_config_file(str(path))
    assert isinstance(selected.get_store(), FilesystemEdedupStore)


@pytest.mark.parametrize("content", ["", "{}", "incremental_metadata:\n  storage:\n    type: invalid"])
def test_defaults_ignore_incremental_settings(tmp_path, content):
    path = tmp_path / "config.yaml"
    path.write_text(content)
    assert EdedupStoreFactory.from_config_file(str(path)).backend == "filesystem"
    assert EdedupStoreFactory.from_config_file(str(tmp_path / "missing")).backend == "filesystem"


@pytest.mark.parametrize(
    "content",
    [
        "[",
        "[]",
        "ededup: false",
        "ededup:\n  storage: []",
        "ededup:\n  storage:\n    type: unknown",
        "ededup:\n  storage:\n    type: null",
        "ededup:\n  storage:\n    config:\n      postgres: nope",
    ],
)
def test_invalid_configuration_fails(tmp_path, content):
    path = tmp_path / "config.yaml"
    path.write_text(content)
    with pytest.raises(DocpipeException):
        EdedupStoreFactory.from_config_file(str(path))


def test_default_sources_and_lazy_thread_safe_store(tmp_path, monkeypatch):
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump({"ededup": {"storage": {"config": {"base_dir": str(tmp_path)}}}}))
    monkeypatch.setenv("DOCPIPE_CONFIG_PATH", str(path))
    selected = EdedupStoreFactory.from_default_sources()
    with ThreadPoolExecutor(max_workers=8) as pool:
        stores = list(pool.map(lambda _: selected.get_store(), range(16)))
    assert all(store is stores[0] for store in stores)


def test_filesystem_lifecycles_do_not_create_each_others_records(tmp_path, monkeypatch):
    monkeypatch.setenv("DOCPIPE_INCREMENTAL_BASE_DIR", str(tmp_path / "incremental"))
    store = FilesystemEdedupStore(config={"base_dir": str(tmp_path / "ededup")})
    assert store.check_and_register_hashes(job_id="j", node_id="n", job_run_id="r", records={"h": "d"}) == {"h"}
    assert not (tmp_path / "incremental").exists()
    assert [p.name for p in (tmp_path / "ededup").iterdir()] == ["ededup_registry"]
    incremental = FilesystemIncrementalMetadataStore()
    assert not hasattr(incremental, "check_and_register_hashes")
    assert not (tmp_path / "incremental" / "ededup_registry").exists()


def test_ededup_modules_do_not_import_incremental_metadata():
    paths = [Path(inspect.getfile(ededup)), *Path(inspect.getfile(factory)).parent.rglob("*.py")]
    for path in paths:
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.ImportFrom):
                assert "incremental_metadata" not in (node.module or ""), path
            elif isinstance(node, ast.Import):
                assert all("incremental_metadata" not in alias.name for alias in node.names), path


def test_postgres_common_environment_and_ededup_override(monkeypatch):
    from docpipe.core.operators.quality.ededup_storage.adapters import postgres_store

    for key, value in {
        "HOST": "envhost",
        "PORT": "5544",
        "DB": "envdb",
        "USER": "envuser",
        "PASSWORD": "testpass",  # pragma: allowlist secret - dummy test credential
    }.items():
        monkeypatch.setenv("DOCPIPE_POSTGRES_" + key, value)
    engine = Mock()
    engine.begin.return_value.__enter__ = Mock(return_value=Mock())
    engine.begin.return_value.__exit__ = Mock(return_value=False)
    with patch.object(postgres_store, "create_postgres_engine", return_value=engine) as create:
        with patch.object(postgres_store.MetaData, "__init__", side_effect=RuntimeError("stop before DDL")):
            with pytest.raises(RuntimeError, match="stop before DDL"):
                postgres_store.PostgresEdedupStore(config={"postgres": {"host": "deduphost"}})
    assert create.call_args.kwargs["connection_string"] == (
        "postgresql+psycopg2://envuser:testpass@deduphost:5544/envdb"  # pragma: allowlist secret - dummy test URL
    )
    engine.dispose.assert_called_once()


@pytest.fixture
def mocked_postgres_store(monkeypatch):
    """Construct a PostgreSQL ededup store with a mocked SQLAlchemy engine."""
    from docpipe.core.operators.quality.ededup_storage.adapters import postgres_store

    engine = MagicMock()
    connection = MagicMock()
    engine.begin.return_value.__enter__.return_value = connection
    engine.dialect.identifier_preparer.quote_schema.return_value = '"test_schema"'
    monkeypatch.setattr(postgres_store, "get_postgres_connection_string", lambda *, config: "postgresql://test")
    monkeypatch.setattr(postgres_store, "create_postgres_engine", lambda *, connection_string, config: engine)
    monkeypatch.setattr(postgres_store.Table, "create", Mock())
    store = postgres_store.PostgresEdedupStore(config={"schema": "test_schema"})
    return store, engine, connection


def test_postgres_store_requires_connection(monkeypatch):
    from docpipe.core.operators.quality.ededup_storage.adapters import postgres_store

    monkeypatch.setattr(postgres_store, "get_postgres_connection_string", lambda *, config: None)
    create_engine = Mock()
    monkeypatch.setattr(postgres_store, "create_postgres_engine", create_engine)
    with pytest.raises(DocpipeException, match="connection not configured"):
        postgres_store.PostgresEdedupStore()
    create_engine.assert_not_called()


def test_postgres_store_initialization_creates_schema_and_table(mocked_postgres_store):
    store, engine, connection = mocked_postgres_store
    assert store._ededup_table.schema == "test_schema"
    assert connection.execute.call_count == 2
    assert connection.execute.call_args_list[0].args[0].text == "SELECT pg_advisory_xact_lock(hashtext(:key))"
    assert connection.execute.call_args_list[0].args[1] == {"key": "test_schema.hashes"}
    assert "CREATE SCHEMA IF NOT EXISTS" in connection.execute.call_args_list[1].args[0].text
    store.close()
    engine.dispose.assert_called_once()


def test_postgres_store_disposes_engine_when_initialization_fails(monkeypatch):
    from docpipe.core.operators.quality.ededup_storage.adapters import postgres_store

    engine = MagicMock()
    engine.begin.return_value.__enter__.return_value = MagicMock()
    monkeypatch.setattr(postgres_store, "get_postgres_connection_string", lambda *, config: "postgresql://test")
    monkeypatch.setattr(postgres_store, "create_postgres_engine", lambda *, connection_string, config: engine)
    monkeypatch.setattr(postgres_store.Table, "create", Mock(side_effect=RuntimeError("DDL failed")))
    with pytest.raises(RuntimeError, match="DDL failed"):
        postgres_store.PostgresEdedupStore(config={"schema": "test_schema"})
    engine.dispose.assert_called_once()


def test_postgres_store_bulk_registers_in_chunks_and_returns_inserted_hashes(mocked_postgres_store):
    store, _, connection = mocked_postgres_store
    records = {f"hash-{index:04}": f"doc-{index}" for index in range(1001)}
    execute_result = Mock()
    execute_result.scalars.return_value.all.side_effect = [list(sorted(records)[:1000]), [sorted(records)[1000]]]
    connection.execute.return_value = execute_result
    accepted = store.check_and_register_hashes(job_id="job", node_id="node", job_run_id="run", records=records)
    assert accepted == set(records)
    assert connection.execute.call_count == 4  # lock, schema, and two insert chunks


def test_postgres_store_empty_registration_skips_transaction(mocked_postgres_store):
    store, engine, _ = mocked_postgres_store
    assert store.check_and_register_hashes(job_id="job", node_id="node", job_run_id="run", records={}) == set()
    engine.begin.assert_called_once()  # Only initialization opened a transaction.


def test_postgres_store_wraps_registration_errors(mocked_postgres_store):
    store, _, connection = mocked_postgres_store
    connection.execute.side_effect = RuntimeError("database unavailable")
    with pytest.raises(FlowExecutionFailedException, match="Failed to register deduplication hashes"):
        store.check_and_register_hashes(job_id="job", node_id="node", job_run_id="run", records={"hash": "doc"})


@pytest.mark.parametrize("schema", [None, "existing_registry"])
def test_postgres_schema_default_and_override(*, mocked_postgres_store, schema):
    from docpipe.core.operators.quality.ededup_storage.adapters.postgres_store import PostgresEdedupStore

    config = {} if schema is None else {"schema": schema}
    store = PostgresEdedupStore(config=config)
    try:
        assert store._ededup_table.schema == (schema or "ededup_registry")
    finally:
        store.close()

"""
Unit tests for JobReportGenerator

Tests cover:
- Report data generation
- CSV content generation
- Node identification (ingest, destination, extract)
- Batch number extraction
- Document status determination
- Processing time calculation
- Page count extraction
- Failure/skip reason extraction
"""

import csv
import io
from unittest.mock import patch

import pytest

from docpipe.core.constants.constants import ExecutionStatus
from docpipe.core.job_management.application.services.report_generator import (
    GENERIC_FAILURE_MESSAGE,
    JobReportGenerator,
    _build_node_metadata_list,
)
from docpipe.core.job_management.domain.models import JobStats, NodeStats

# Test constants
JOB_ID = "test-job-123"
JOB_RUN_ID = "test-run-456"
INGEST_NODE_ID = "ingest-node-1"
EXTRACT_NODE_ID = "extract-node-2"
DEST_NODE_ID = "dest-node-3"


class TestJobReportGeneratorInitialization:
    """Test report generator initialization."""

    def test_init_with_minimal_params(self):
        """Initialize with only required parameters."""
        job_stats = JobStats(
            job_id=JOB_ID,
            job_run_id=JOB_RUN_ID,
            status=ExecutionStatus.COMPLETED,
            node_stats={},
        )

        generator = JobReportGenerator(job_stats=job_stats)

        assert generator.job_stats == job_stats
        assert generator.dag_nodes == []
        assert generator.node_metadata_list == []
        assert generator.node_id_to_name == {}

    def test_init_with_dag_nodes(self):
        """Initialize with DAG nodes builds node name map."""
        job_stats = JobStats(
            job_id=JOB_ID,
            job_run_id=JOB_RUN_ID,
            status=ExecutionStatus.COMPLETED,
            node_stats={},
        )

        dag_nodes = [
            {"id": INGEST_NODE_ID, "name": "IngestLocal"},
            {"id": EXTRACT_NODE_ID, "name": "Extract"},
        ]

        generator = JobReportGenerator(job_stats=job_stats, dag_nodes=dag_nodes)

        assert len(generator.node_id_to_name) == 2
        assert generator.node_id_to_name[INGEST_NODE_ID] == "IngestLocal"
        assert generator.node_id_to_name[EXTRACT_NODE_ID] == "Extract"


class TestNodeIdentification:
    """Test node identification methods."""

    def test_get_ingest_node_id_no_input_edges(self):
        """Ingest node is identified by having no input edges."""
        job_stats = JobStats(
            job_id=JOB_ID,
            job_run_id=JOB_RUN_ID,
            status=ExecutionStatus.COMPLETED,
            node_stats={},
        )

        dag_nodes = [
            {"id": INGEST_NODE_ID, "name": "Ingest", "input_edges": []},
            {"id": EXTRACT_NODE_ID, "name": "Extract", "input_edges": [INGEST_NODE_ID]},
        ]

        generator = JobReportGenerator(job_stats=job_stats, dag_nodes=dag_nodes)
        ingest_id = generator._get_ingest_node_id()

        assert ingest_id == INGEST_NODE_ID

    def test_get_destination_node_ids_no_output_edges(self):
        """Destination nodes are identified by having no output edges."""
        job_stats = JobStats(
            job_id=JOB_ID,
            job_run_id=JOB_RUN_ID,
            status=ExecutionStatus.COMPLETED,
            node_stats={},
        )

        dag_nodes = [
            {"id": INGEST_NODE_ID, "name": "Ingest", "output_edges": [EXTRACT_NODE_ID]},
            {"id": EXTRACT_NODE_ID, "name": "Extract", "output_edges": [DEST_NODE_ID]},
            {"id": DEST_NODE_ID, "name": "VectorDB", "output_edges": []},
        ]

        generator = JobReportGenerator(job_stats=job_stats, dag_nodes=dag_nodes)
        dest_ids = generator._get_destination_node_ids()

        assert dest_ids == [DEST_NODE_ID]

    def test_find_extract_operator_by_op_field(self):
        """Extract operator is found by checking 'op' field."""
        job_stats = JobStats(
            job_id=JOB_ID,
            job_run_id=JOB_RUN_ID,
            status=ExecutionStatus.COMPLETED,
            node_stats={},
        )

        dag_nodes = [
            {"id": INGEST_NODE_ID, "op": "ingest_source"},
            {"id": EXTRACT_NODE_ID, "op": "extract", "name": "ExtractOp"},
        ]

        generator = JobReportGenerator(job_stats=job_stats, dag_nodes=dag_nodes)
        extract_id, extract_name = generator._find_extract_operator()

        assert extract_id == EXTRACT_NODE_ID
        assert extract_name == "ExtractOp"

    def test_find_extract_operator_by_operator_field(self):
        """Extract operator is found by checking 'operator' field."""
        job_stats = JobStats(
            job_id=JOB_ID,
            job_run_id=JOB_RUN_ID,
            status=ExecutionStatus.COMPLETED,
            node_stats={},
        )

        dag_nodes = [
            {"id": EXTRACT_NODE_ID, "operator": "extract_cpd", "name": "Extract"},
        ]

        generator = JobReportGenerator(job_stats=job_stats, dag_nodes=dag_nodes)
        extract_id, extract_name = generator._find_extract_operator()

        assert extract_id == EXTRACT_NODE_ID
        assert extract_name == "Extract"


class TestBatchNumberExtraction:
    """Test batch number extraction from batch_node_stats."""

    def test_get_batch_nums_from_stats(self):
        """Extract batch numbers from batch_node_stats."""
        batch_stats_1 = NodeStats(
            id=EXTRACT_NODE_ID,
            name="Extract",
            batch_id="batch-1",
            batch_num=0,
        )
        batch_stats_2 = NodeStats(
            id=EXTRACT_NODE_ID,
            name="Extract",
            batch_id="batch-2",
            batch_num=1,
        )

        job_stats = JobStats(
            job_id=JOB_ID,
            job_run_id=JOB_RUN_ID,
            status=ExecutionStatus.COMPLETED,
            node_stats={},
            batch_node_stats={
                EXTRACT_NODE_ID: {
                    "batch-1": batch_stats_1,
                    "batch-2": batch_stats_2,
                }
            },
        )

        generator = JobReportGenerator(job_stats=job_stats)
        batch_nums = generator._get_actual_batch_nums(EXTRACT_NODE_ID)

        assert batch_nums == {0, 1}

    def test_get_actual_batch_nums_with_batch_stats(self):
        """Get actual batch numbers when batch_node_stats exists."""
        batch_stats = NodeStats(
            id=EXTRACT_NODE_ID,
            name="Extract",
            batch_id="batch-1",
            batch_num=0,
        )

        job_stats = JobStats(
            job_id=JOB_ID,
            job_run_id=JOB_RUN_ID,
            status=ExecutionStatus.COMPLETED,
            node_stats={},
            batch_node_stats={EXTRACT_NODE_ID: {"batch-1": batch_stats}},
        )

        generator = JobReportGenerator(job_stats=job_stats)
        batch_nums = generator._get_actual_batch_nums(EXTRACT_NODE_ID)

        assert batch_nums == {0}

    def test_get_actual_batch_nums_without_batch_stats(self):
        """Return {None} when no batch_node_stats (non-batched flow)."""
        job_stats = JobStats(
            job_id=JOB_ID,
            job_run_id=JOB_RUN_ID,
            status=ExecutionStatus.COMPLETED,
            node_stats={},
        )

        generator = JobReportGenerator(job_stats=job_stats)
        batch_nums = generator._get_actual_batch_nums(EXTRACT_NODE_ID)

        assert batch_nums == {None}


class TestDocumentStatusDetermination:
    """Test document status determination logic."""

    def test_build_status_lookup_sets(self):
        """Build lookup sets for failed, skipped, and destination completed docs."""
        node_stats_1 = NodeStats(
            id=INGEST_NODE_ID,
            name="Ingest",
            failed_docs=["doc1"],
            skipped_docs=["doc2"],
        )
        node_stats_2 = NodeStats(
            id=DEST_NODE_ID,
            name="VectorDB",
            node_status=ExecutionStatus.COMPLETED,
            docs_completed=["doc3", "doc4"],
        )

        job_stats = JobStats(
            job_id=JOB_ID,
            job_run_id=JOB_RUN_ID,
            status=ExecutionStatus.COMPLETED,
            node_stats={
                INGEST_NODE_ID: node_stats_1,
                DEST_NODE_ID: node_stats_2,
            },
        )

        dag_nodes = [
            {"id": INGEST_NODE_ID, "output_edges": [DEST_NODE_ID]},
            {"id": DEST_NODE_ID, "output_edges": []},
        ]

        generator = JobReportGenerator(job_stats=job_stats, dag_nodes=dag_nodes)
        failed, skipped, dest_completed = generator._build_status_lookup_sets()

        assert failed == {"doc1"}
        assert skipped == {"doc2"}
        assert dest_completed == {"doc3", "doc4"}


class TestCSVGeneration:
    """Test CSV content generation."""

    def test_generate_csv_content_empty_report(self):
        """Returns empty string and logs a warning when no document data is available."""
        job_stats = JobStats(
            job_id=JOB_ID,
            job_run_id=JOB_RUN_ID,
            status=ExecutionStatus.COMPLETED,
            node_stats={},
        )

        generator = JobReportGenerator(job_stats=job_stats)

        with patch.object(generator, "generate_report_data", return_value=[]):
            csv_content = generator.generate_csv_content()

        assert csv_content == ""

    def test_generate_csv_content_with_data(self):
        """Generate CSV with document data."""
        job_stats = JobStats(
            job_id=JOB_ID,
            job_run_id=JOB_RUN_ID,
            status=ExecutionStatus.COMPLETED,
            node_stats={},
        )

        generator = JobReportGenerator(job_stats=job_stats)

        mock_data = [
            {
                "GUID": "doc1",
                "File name": "test.pdf",
                "Status": "Ingested",
                "Status reason": "",
                "Time stamp": "2024-01-01T00:00:00Z",
                "Pages": "10",
                "Processing time (in seconds)": "45",
            }
        ]

        with patch.object(generator, "generate_report_data", return_value=mock_data):
            csv_content = generator.generate_csv_content()

        # Parse CSV to verify content
        csv_reader = csv.DictReader(io.StringIO(csv_content))
        rows = list(csv_reader)

        assert len(rows) == 1
        assert rows[0]["GUID"] == "doc1"
        assert rows[0]["File name"] == "test.pdf"
        assert rows[0]["Status"] == "Ingested"
        assert rows[0]["Pages"] == "10"

    def test_save_report_to_file(self, tmp_path):
        """Save report delegates to the storage adapter."""
        from unittest.mock import Mock

        job_stats = JobStats(
            job_id=JOB_ID,
            job_run_id=JOB_RUN_ID,
            status=ExecutionStatus.COMPLETED,
            node_stats={},
        )

        generator = JobReportGenerator(job_stats=job_stats)

        from docpipe.core.models.session_info import create_session_info

        create_session_info(job_id=JOB_ID, job_run_id=JOB_RUN_ID)

        mock_csv = "GUID,File name,Status\ndoc1,test.pdf,Ingested\n"
        mock_adapter = Mock()
        mock_adapter.write_text.return_value = str(tmp_path / "job_report.csv")

        with (
            patch.object(generator, "generate_csv_content", return_value=mock_csv),
            patch(
                "docpipe.core.job_management.adapters.config.report_storage_factory.get_report_storage",
                return_value=mock_adapter,
            ),
        ):
            saved_path = generator.save_report_to_file()

        mock_adapter.write_text.assert_called_once_with(
            collection=f"{JOB_ID}/{JOB_RUN_ID}",
            file_name=f"job_report_{JOB_RUN_ID}.csv",
            content=mock_csv,
        )
        assert saved_path == str(tmp_path / "job_report.csv")


class TestTimestampConversion:
    """Test timestamp conversion methods."""

    def test_get_timestamp_from_modified_time_integer(self):
        """Convert integer timestamp to YYYY-MM-DD:HH:MM:SS format."""
        job_stats = JobStats(
            job_id=JOB_ID,
            job_run_id=JOB_RUN_ID,
            status=ExecutionStatus.COMPLETED,
            node_stats={},
        )

        generator = JobReportGenerator(job_stats=job_stats)

        # Unix timestamp for 2024-01-01 00:00:00 UTC
        timestamp = 1704067200
        result = generator._get_timestamp_from_modified_time(timestamp, "doc1")

        # Should match the CSV format: YYYY-MM-DD:HH:MM:SS
        assert result == "2024-01-01:00:00:00"

    def test_get_timestamp_from_modified_time_epoch_ms(self):
        """Convert epoch-millisecond timestamp to YYYY-MM-DD:HH:MM:SS format."""
        job_stats = JobStats(
            job_id=JOB_ID,
            job_run_id=JOB_RUN_ID,
            status=ExecutionStatus.COMPLETED,
            node_stats={},
        )

        generator = JobReportGenerator(job_stats=job_stats)

        # Epoch-ms timestamp (≥ 1e10): 1704067200000
        # Should divide by 1000 to get seconds: 1704067200 = 2024-01-01 00:00:00 UTC
        timestamp_ms = 1704067200000
        result = generator._get_timestamp_from_modified_time(timestamp_ms, "doc1")

        # Should match the CSV format: YYYY-MM-DD:HH:MM:SS
        assert result == "2024-01-01:00:00:00"

    def test_get_timestamp_from_modified_time_string(self):
        """Return string timestamp as-is."""
        job_stats = JobStats(
            job_id=JOB_ID,
            job_run_id=JOB_RUN_ID,
            status=ExecutionStatus.COMPLETED,
            node_stats={},
        )

        generator = JobReportGenerator(job_stats=job_stats)

        timestamp_str = "2024-01-01T00:00:00Z"
        result = generator._get_timestamp_from_modified_time(timestamp_str, "doc1")

        assert result == timestamp_str

    def test_get_timestamp_from_modified_time_none(self):
        """Return empty string for None timestamp."""
        job_stats = JobStats(
            job_id=JOB_ID,
            job_run_id=JOB_RUN_ID,
            status=ExecutionStatus.COMPLETED,
            node_stats={},
        )

        generator = JobReportGenerator(job_stats=job_stats)

        result = generator._get_timestamp_from_modified_time(None, "doc1")

        assert result == ""


class TestBatchAttributeAccess:
    """Test _get_batch_attr helper for dict/object compatibility."""

    def test_get_batch_attr_from_dict(self):
        """Get attribute from dictionary batch_stats."""
        job_stats = JobStats(
            job_id=JOB_ID,
            job_run_id=JOB_RUN_ID,
            status=ExecutionStatus.COMPLETED,
            node_stats={},
        )

        generator = JobReportGenerator(job_stats=job_stats)

        batch_stats_dict = {"batch_num": 0, "name": "Extract"}
        result = generator._get_batch_attr(batch_stats_dict, "batch_num")

        assert result == 0

    def test_get_batch_attr_from_object(self):
        """Get attribute from NodeStats object."""
        job_stats = JobStats(
            job_id=JOB_ID,
            job_run_id=JOB_RUN_ID,
            status=ExecutionStatus.COMPLETED,
            node_stats={},
        )

        generator = JobReportGenerator(job_stats=job_stats)

        batch_stats_obj = NodeStats(
            id=EXTRACT_NODE_ID,
            name="Extract",
            batch_num=1,
        )
        result = generator._get_batch_attr(batch_stats_obj, "batch_num")

        assert result == 1

    def test_get_batch_attr_with_default(self):
        """Return default value when attribute not found."""
        job_stats = JobStats(
            job_id=JOB_ID,
            job_run_id=JOB_RUN_ID,
            status=ExecutionStatus.COMPLETED,
            node_stats={},
        )

        generator = JobReportGenerator(job_stats=job_stats)

        batch_stats_dict = {"name": "Extract"}
        result = generator._get_batch_attr(batch_stats_dict, "missing_attr", default="default_value")

        assert result == "default_value"


class TestStaticMethodConversion:
    """Verify per-document helpers are staticmethods callable without an instance."""

    def test_get_timestamp_from_modified_time_is_static(self):
        import inspect

        assert isinstance(inspect.getattr_static(JobReportGenerator, "_get_timestamp_from_modified_time"), staticmethod)

    def test_create_doc_entry_is_static(self):
        import inspect

        assert isinstance(inspect.getattr_static(JobReportGenerator, "_create_doc_entry"), staticmethod)

    def test_get_timestamp_from_modified_time_class_call(self):
        """Static call converts epoch seconds without needing an instance."""
        result = JobReportGenerator._get_timestamp_from_modified_time(1704067200, "doc1")

        assert result == "2024-01-01:00:00:00"

    def test_create_doc_entry_class_call(self):
        """Static call builds the expected document entry dict."""
        entry = JobReportGenerator._create_doc_entry(
            doc_name="report.pdf", modified_time=1704067200, timestamp_str="2024-01-01:00:00:00"
        )

        assert entry == {
            "name": "report.pdf",
            "status": "",
            "reason": "",
            "timestamp": "2024-01-01:00:00:00",
            "pages": "",
            "processing_time": "",
            "modified_time": 1704067200,
        }

    def test_instance_and_class_calls_agree(self):
        """Instance access and class access return identical results."""
        job_stats = JobStats(
            job_id=JOB_ID,
            job_run_id=JOB_RUN_ID,
            status=ExecutionStatus.COMPLETED,
            node_stats={},
        )
        generator = JobReportGenerator(job_stats=job_stats)

        assert generator._get_timestamp_from_modified_time(
            1704067200, "doc1"
        ) == JobReportGenerator._get_timestamp_from_modified_time(1704067200, "doc1")


class TestReasonExtraction:
    """Test failure/skip reason extraction."""

    def test_extract_reason_from_docs_list(self):
        """Extract reason from document list with reason field."""
        job_stats = JobStats(
            job_id=JOB_ID,
            job_run_id=JOB_RUN_ID,
            status=ExecutionStatus.COMPLETED,
            node_stats={},
        )

        generator = JobReportGenerator(job_stats=job_stats)

        docs_list = [
            {"id": "doc1", "reason": "File not found"},
            {"id": "doc2", "reason": "Invalid format"},
        ]

        reason = generator._extract_reason_from_docs_list(docs_list, "doc1")

        assert reason == "File not found"

    def test_extract_reason_from_docs_list_not_found(self):
        """Return None when document not in list."""
        job_stats = JobStats(
            job_id=JOB_ID,
            job_run_id=JOB_RUN_ID,
            status=ExecutionStatus.COMPLETED,
            node_stats={},
        )

        generator = JobReportGenerator(job_stats=job_stats)

        docs_list = [{"id": "doc1", "reason": "Error"}]

        reason = generator._extract_reason_from_docs_list(docs_list, "doc2")

        assert reason is None


class TestBuildNodeMetadataList:
    """Test _build_node_metadata_list used by the on-demand report path."""

    def test_builds_list_from_node_stats_objects(self):
        """NodeStats objects: node_metadata dict is appended directly."""
        node_metadata_item = {
            "id": "uuid-1",
            "operator": "store_in_opensearch",
            "node_metadata": {
                "failed_docs": [{"id": "doc-a", "reason": "Connection timeout"}],
                "skipped_docs": [],
            },
        }
        node_stats = {
            "uuid-1": NodeStats(
                id="uuid-1",
                name="store_in_opensearch",
                node_metadata=node_metadata_item,
            )
        }

        result = _build_node_metadata_list(node_stats=node_stats)

        assert len(result) == 1
        # Entry IS the NodeMetadataItem dict; failed_docs reachable via ["node_metadata"]
        assert result[0]["node_metadata"]["failed_docs"][0]["reason"] == "Connection timeout"

    def test_builds_list_from_dict_node_stats(self):
        """Dict-style node_stats are also handled."""
        node_metadata_item = {
            "id": "uuid-1",
            "operator": "store_in_opensearch",
            "node_metadata": {
                "failed_docs": [{"id": "doc-b", "reason": "Index not found"}],
                "skipped_docs": [],
            },
        }
        node_stats = {
            "uuid-1": {
                "name": "store_in_opensearch",
                "node_metadata": node_metadata_item,
            }
        }

        result = _build_node_metadata_list(node_stats=node_stats)

        assert len(result) == 1
        assert result[0]["node_metadata"]["failed_docs"][0]["reason"] == "Index not found"

    def test_on_demand_path_retrieves_failure_reason_not_generic(self):
        """On-demand report generator retrieves the real reason, not the generic fallback."""
        failure_reason = "Failed to create index: ConnectionTimeout"

        node_metadata_item = {
            "id": "uuid-os",
            "operator": "store_in_opensearch",
            "node_metadata": {
                "failed_docs": [{"id": "doc-1", "reason": failure_reason}],
                "skipped_docs": [],
            },
        }
        node_stats = {
            "uuid-os": NodeStats(
                id="uuid-os",
                name="store_in_opensearch",
                node_metadata=node_metadata_item,
            )
        }

        node_metadata_list = _build_node_metadata_list(node_stats=node_stats)
        generator = JobReportGenerator(
            job_stats=JobStats(job_id=JOB_ID, job_run_id=JOB_RUN_ID, status=ExecutionStatus.FAILED),
            node_metadata_list=node_metadata_list,
        )

        reason = generator._find_failure_reason("doc-1")

        assert reason == failure_reason
        assert reason != GENERIC_FAILURE_MESSAGE


class TestInitializeDocsFromIngest:
    """Tests for _initialize_docs_from_ingest behavior changed in this PR."""

    def test_returns_empty_dict_when_ingest_data_is_empty(self):
        """When the ingest parquet file contains no rows, returns an empty dict instead of raising."""
        job_stats = JobStats(
            job_id=JOB_ID,
            job_run_id=JOB_RUN_ID,
            status=ExecutionStatus.COMPLETED,
            node_stats={},
        )
        dag_nodes = [
            {"id": INGEST_NODE_ID, "name": "ingest_local", "input_edges": [], "output_edges": [EXTRACT_NODE_ID]},
            {"id": EXTRACT_NODE_ID, "name": "extract", "input_edges": [INGEST_NODE_ID], "output_edges": []},
        ]
        generator = JobReportGenerator(job_stats=job_stats, dag_nodes=dag_nodes)

        with patch.object(generator, "_read_parquet_file", return_value={}):
            result = generator._initialize_docs_from_ingest()

        assert result == {}

    def test_returns_empty_dict_when_no_ingest_node_in_dag(self):
        """When the DAG has no ingest node (all nodes have input_edges), returns an empty dict."""
        job_stats = JobStats(
            job_id=JOB_ID,
            job_run_id=JOB_RUN_ID,
            status=ExecutionStatus.COMPLETED,
            node_stats={},
        )
        # All nodes have input_edges — no ingest node can be identified
        dag_nodes = [
            {"id": EXTRACT_NODE_ID, "name": "extract", "input_edges": [INGEST_NODE_ID], "output_edges": []},
        ]
        generator = JobReportGenerator(job_stats=job_stats, dag_nodes=dag_nodes)

        result = generator._initialize_docs_from_ingest()

        assert result == {}

    def test_generate_report_data_returns_empty_list_when_ingest_data_missing(self):
        """generate_report_data returns [] (not a ValueError) when ingest parquet has no rows."""
        job_stats = JobStats(
            job_id=JOB_ID,
            job_run_id=JOB_RUN_ID,
            status=ExecutionStatus.COMPLETED,
            node_stats={},
        )
        dag_nodes = [
            {"id": INGEST_NODE_ID, "name": "ingest_local", "input_edges": [], "output_edges": [EXTRACT_NODE_ID]},
            {"id": EXTRACT_NODE_ID, "name": "extract", "input_edges": [INGEST_NODE_ID], "output_edges": []},
        ]
        generator = JobReportGenerator(job_stats=job_stats, dag_nodes=dag_nodes)

        with patch.object(generator, "_read_parquet_file", return_value={}):
            report_data = generator.generate_report_data()

        assert report_data == []


class TestCreateDocEntry:
    """Tests for _create_doc_entry."""

    def test_creates_entry_with_expected_keys(self):
        """_create_doc_entry returns a dict with all required keys."""
        job_stats = JobStats(job_id=JOB_ID, job_run_id=JOB_RUN_ID, status=ExecutionStatus.COMPLETED, node_stats={})
        generator = JobReportGenerator(job_stats=job_stats)

        entry = generator._create_doc_entry(
            doc_name="file.pdf", modified_time=1704067200, timestamp_str="2024-01-01:00:00:00"
        )

        assert entry["name"] == "file.pdf"
        assert entry["timestamp"] == "2024-01-01:00:00:00"
        assert entry["status"] == ""
        assert entry["reason"] == ""
        assert entry["pages"] == ""
        assert entry["processing_time"] == ""


class TestCreateReportRows:
    """Tests for _create_report_rows."""

    def test_maps_all_fields_to_csv_columns(self):
        """Each all_docs entry becomes one row with all 7 CSV columns."""
        job_stats = JobStats(job_id=JOB_ID, job_run_id=JOB_RUN_ID, status=ExecutionStatus.COMPLETED, node_stats={})
        generator = JobReportGenerator(job_stats=job_stats)

        all_docs = {
            "doc-1": {
                "name": "test.pdf",
                "status": "Ingested",
                "reason": "",
                "timestamp": "2024-01-01:00:00:00",
                "pages": "5",
                "processing_time": "12",
            }
        }

        rows = generator._create_report_rows(all_docs)

        assert len(rows) == 1
        assert rows[0]["GUID"] == "doc-1"
        assert rows[0]["File name"] == "test.pdf"
        assert rows[0]["Status"] == "Ingested"
        assert rows[0]["Pages"] == "5"
        assert rows[0]["Processing time (in seconds)"] == "12"

    def test_empty_status_defaults_to_unknown_in_row(self):
        """An empty status string in all_docs is written as 'Unknown' in the CSV row."""
        job_stats = JobStats(job_id=JOB_ID, job_run_id=JOB_RUN_ID, status=ExecutionStatus.COMPLETED, node_stats={})
        generator = JobReportGenerator(job_stats=job_stats)

        all_docs = {
            "doc-1": {"name": "f.pdf", "status": "", "reason": "", "timestamp": "", "pages": "", "processing_time": ""}
        }

        rows = generator._create_report_rows(all_docs)

        assert rows[0]["Status"] == "Unknown"


class TestUpdateDocumentStatus:
    """Tests for _update_document_status."""

    def _make_generator(self, dag_nodes, node_stats_dict, status=ExecutionStatus.COMPLETED, node_metadata_list=None):
        job_stats = JobStats(job_id=JOB_ID, job_run_id=JOB_RUN_ID, status=status, node_stats=node_stats_dict)
        return JobReportGenerator(job_stats=job_stats, dag_nodes=dag_nodes, node_metadata_list=node_metadata_list or [])

    def test_marks_failed_docs(self):
        """Documents in failed_docs get status=Failed."""
        node_stats = NodeStats(id=INGEST_NODE_ID, name="ingest", failed_docs=["doc-1"])
        dag_nodes = [
            {"id": INGEST_NODE_ID, "output_edges": [DEST_NODE_ID]},
            {"id": DEST_NODE_ID, "output_edges": []},
        ]
        generator = self._make_generator(dag_nodes, {INGEST_NODE_ID: node_stats})

        all_docs = {
            "doc-1": {"name": "f.pdf", "status": "", "reason": "", "timestamp": "", "pages": "", "processing_time": ""}
        }
        generator._update_document_status(all_docs)

        assert all_docs["doc-1"]["status"] == "Failed"

    def test_marks_skipped_docs(self):
        """Documents in skipped_docs get status=Skipped."""
        node_stats = NodeStats(id=INGEST_NODE_ID, name="ingest", skipped_docs=["doc-2"])
        dag_nodes = [
            {"id": INGEST_NODE_ID, "output_edges": [DEST_NODE_ID]},
            {"id": DEST_NODE_ID, "output_edges": []},
        ]
        generator = self._make_generator(dag_nodes, {INGEST_NODE_ID: node_stats})

        all_docs = {
            "doc-2": {"name": "f.pdf", "status": "", "reason": "", "timestamp": "", "pages": "", "processing_time": ""}
        }
        generator._update_document_status(all_docs)

        assert all_docs["doc-2"]["status"] == "Skipped"

    def test_marks_completed_docs_at_destination(self):
        """Documents in dest docs_completed get status=Ingested."""
        dest_stats = NodeStats(
            id=DEST_NODE_ID, name="vectordb", docs_completed=["doc-3"], node_status=ExecutionStatus.COMPLETED
        )
        dag_nodes = [
            {"id": INGEST_NODE_ID, "output_edges": [DEST_NODE_ID]},
            {"id": DEST_NODE_ID, "output_edges": []},
        ]
        generator = self._make_generator(dag_nodes, {DEST_NODE_ID: dest_stats})

        all_docs = {
            "doc-3": {"name": "f.pdf", "status": "", "reason": "", "timestamp": "", "pages": "", "processing_time": ""}
        }
        generator._update_document_status(all_docs)

        assert all_docs["doc-3"]["status"] == "Ingested"

    def test_unclassified_doc_in_failed_job_gets_failed_status(self):
        """Unclassified doc in a FAILED job gets status=Failed."""
        dag_nodes = [
            {"id": INGEST_NODE_ID, "output_edges": [DEST_NODE_ID]},
            {"id": DEST_NODE_ID, "output_edges": []},
        ]
        generator = self._make_generator(dag_nodes, {}, status=ExecutionStatus.FAILED)

        all_docs = {
            "doc-4": {"name": "f.pdf", "status": "", "reason": "", "timestamp": "", "pages": "", "processing_time": ""}
        }
        generator._update_document_status(all_docs)

        assert all_docs["doc-4"]["status"] == "Failed"

    def test_unclassified_doc_in_completed_job_gets_unknown_status(self):
        """Unclassified doc in a COMPLETED job gets status=Unknown."""
        dag_nodes = [
            {"id": INGEST_NODE_ID, "output_edges": [DEST_NODE_ID]},
            {"id": DEST_NODE_ID, "output_edges": []},
        ]
        generator = self._make_generator(dag_nodes, {}, status=ExecutionStatus.COMPLETED)

        all_docs = {
            "doc-5": {"name": "f.pdf", "status": "", "reason": "", "timestamp": "", "pages": "", "processing_time": ""}
        }
        generator._update_document_status(all_docs)

        assert all_docs["doc-5"]["status"] == "Unknown"


class TestFindSkipReason:
    """Tests for _find_skip_reason."""

    def test_returns_reason_from_node_metadata(self):
        """Returns skip reason found in node_metadata_list."""
        node_metadata_item = {
            "id": "uuid-1",
            "operator": "lang_detect",
            "node_metadata": {
                "skipped_docs": [{"id": "doc-1", "reason": "Language not supported"}],
                "failed_docs": [],
            },
        }
        node_stats = {"uuid-1": NodeStats(id="uuid-1", name="lang_detect", node_metadata=node_metadata_item)}
        node_metadata_list = _build_node_metadata_list(node_stats=node_stats)
        job_stats = JobStats(job_id=JOB_ID, job_run_id=JOB_RUN_ID, status=ExecutionStatus.COMPLETED)
        generator = JobReportGenerator(job_stats=job_stats, node_metadata_list=node_metadata_list)

        reason = generator._find_skip_reason("doc-1")

        assert reason == "Language not supported"

    def test_returns_generic_skip_message_when_not_found(self):
        """Returns GENERIC_SKIP_MESSAGE when no reason is found."""
        from docpipe.core.job_management.application.services.report_generator import GENERIC_SKIP_MESSAGE

        job_stats = JobStats(job_id=JOB_ID, job_run_id=JOB_RUN_ID, status=ExecutionStatus.COMPLETED)
        generator = JobReportGenerator(job_stats=job_stats)

        assert generator._find_skip_reason("unknown-doc") == GENERIC_SKIP_MESSAGE


class TestGetRequiredColumns:
    """Tests for _get_required_columns column projection."""

    def _generator_with_dag(self, dag_nodes):
        job_stats = JobStats(job_id=JOB_ID, job_run_id=JOB_RUN_ID, status=ExecutionStatus.COMPLETED, node_stats={})
        return JobReportGenerator(job_stats=job_stats, dag_nodes=dag_nodes)

    def test_ingest_node_returns_metadata_columns(self):
        """Ingest node returns id, name, modified_time columns."""
        dag_nodes = [
            {"id": INGEST_NODE_ID, "name": "ingest_local", "input_edges": []},
            {"id": EXTRACT_NODE_ID, "name": "extract", "op": "extract", "input_edges": [INGEST_NODE_ID]},
        ]
        generator = self._generator_with_dag(dag_nodes)

        cols = generator._get_required_columns(INGEST_NODE_ID)

        assert cols == ["id", "name", "modified_time"]

    def test_extract_node_returns_page_columns(self):
        """Extract node returns id, pages_processed columns."""
        dag_nodes = [
            {"id": INGEST_NODE_ID, "name": "ingest_local", "input_edges": []},
            {"id": EXTRACT_NODE_ID, "name": "extract_op", "op": "extract", "input_edges": [INGEST_NODE_ID]},
        ]
        generator = self._generator_with_dag(dag_nodes)

        cols = generator._get_required_columns(EXTRACT_NODE_ID)

        assert cols == ["id", "pages_processed"]

    def test_other_node_returns_id_only(self):
        """Any non-ingest, non-extract node returns only ['id']."""
        dag_nodes = [
            {"id": INGEST_NODE_ID, "name": "ingest_local", "input_edges": []},
            {"id": DEST_NODE_ID, "name": "vectordb", "op": "vectordb", "input_edges": [INGEST_NODE_ID]},
        ]
        generator = self._generator_with_dag(dag_nodes)

        cols = generator._get_required_columns(DEST_NODE_ID)

        assert cols == ["id"]


class TestGetIngestStartTime:
    """Tests for _get_ingest_start_time."""

    def test_returns_ingest_start_time_from_node_stats(self):
        """Returns start_time from the ingest node's NodeStats."""
        ingest_stats = NodeStats(id=INGEST_NODE_ID, name="ingest_local", start_time=1000)
        job_stats = JobStats(
            job_id=JOB_ID,
            job_run_id=JOB_RUN_ID,
            status=ExecutionStatus.COMPLETED,
            node_stats={INGEST_NODE_ID: ingest_stats},
        )
        dag_nodes = [
            {"id": INGEST_NODE_ID, "name": "ingest_local", "input_edges": []},
            {"id": EXTRACT_NODE_ID, "name": "extract", "input_edges": [INGEST_NODE_ID]},
        ]
        generator = JobReportGenerator(job_stats=job_stats, dag_nodes=dag_nodes)

        assert generator._get_ingest_start_time() == pytest.approx(1000.0)

    def test_returns_zero_when_ingest_node_not_in_node_stats(self):
        """Returns 0.0 when ingest node ID is not present in node_stats."""
        job_stats = JobStats(job_id=JOB_ID, job_run_id=JOB_RUN_ID, status=ExecutionStatus.COMPLETED, node_stats={})
        dag_nodes = [{"id": INGEST_NODE_ID, "name": "ingest_local", "input_edges": []}]
        generator = JobReportGenerator(job_stats=job_stats, dag_nodes=dag_nodes)

        assert generator._get_ingest_start_time() == pytest.approx(0.0)


class TestBuildDocToBatchMappingFallback:
    """Tests for _build_doc_to_batch_mapping_fallback (node-level timing)."""

    def test_calculates_processing_time_from_destination_node(self):
        """Processing time = dest end_time - ingest start_time."""
        ingest_stats = NodeStats(id=INGEST_NODE_ID, name="ingest_local", start_time=1000)
        dest_stats = NodeStats(
            id=DEST_NODE_ID,
            name="vectordb",
            docs_completed=["doc-1"],
            end_time=1045,
        )
        job_stats = JobStats(
            job_id=JOB_ID,
            job_run_id=JOB_RUN_ID,
            status=ExecutionStatus.COMPLETED,
            node_stats={INGEST_NODE_ID: ingest_stats, DEST_NODE_ID: dest_stats},
        )
        dag_nodes = [
            {"id": INGEST_NODE_ID, "name": "ingest_local", "input_edges": [], "output_edges": [DEST_NODE_ID]},
            {"id": DEST_NODE_ID, "name": "vectordb", "input_edges": [INGEST_NODE_ID], "output_edges": []},
        ]
        generator = JobReportGenerator(job_stats=job_stats, dag_nodes=dag_nodes)

        mapping = generator._build_doc_to_batch_mapping_fallback()

        assert mapping["doc-1"] == "45"

    def test_returns_empty_when_no_docs_in_any_node(self):
        """Returns {} when node_stats has no document lists."""
        job_stats = JobStats(job_id=JOB_ID, job_run_id=JOB_RUN_ID, status=ExecutionStatus.COMPLETED, node_stats={})
        generator = JobReportGenerator(job_stats=job_stats, dag_nodes=[])

        mapping = generator._build_doc_to_batch_mapping_fallback()

        assert mapping == {}


class TestBuildDocToBatchMapping:
    """Tests for _build_doc_to_batch_mapping dispatch logic."""

    def test_uses_fallback_when_no_batch_node_stats(self):
        """Falls back to node-level timing when batch_node_stats is absent."""
        job_stats = JobStats(job_id=JOB_ID, job_run_id=JOB_RUN_ID, status=ExecutionStatus.COMPLETED, node_stats={})
        generator = JobReportGenerator(job_stats=job_stats)

        with patch.object(
            generator, "_build_doc_to_batch_mapping_fallback", return_value={"doc-1": "10"}
        ) as mock_fallback:
            result = generator._build_doc_to_batch_mapping()

        mock_fallback.assert_called_once()
        assert result == {"doc-1": "10"}

    def test_uses_fallback_when_find_first_batching_operator_returns_none(self):
        """Falls back when _find_first_batching_operator returns None."""
        job_stats = JobStats(
            job_id=JOB_ID,
            job_run_id=JOB_RUN_ID,
            status=ExecutionStatus.COMPLETED,
            node_stats={},
            batch_node_stats={},
        )
        generator = JobReportGenerator(job_stats=job_stats, dag_nodes=[])

        with (
            patch.object(generator, "_find_first_batching_operator", return_value=None),
            patch.object(generator, "_build_doc_to_batch_mapping_fallback", return_value={}) as mock_fallback,
        ):
            generator._build_doc_to_batch_mapping()

        mock_fallback.assert_called_once()


class TestFindFirstBatchingOperator:
    """Tests for _find_first_batching_operator."""

    def test_returns_none_when_no_batch_node_stats(self):
        """Returns None when batch_node_stats is not set."""
        job_stats = JobStats(job_id=JOB_ID, job_run_id=JOB_RUN_ID, status=ExecutionStatus.COMPLETED, node_stats={})
        generator = JobReportGenerator(job_stats=job_stats)

        assert generator._find_first_batching_operator() is None

    def test_returns_first_dag_node_with_batch_stats(self):
        """Returns the first DAG node that has batch stats."""
        batch_stat = NodeStats(id=INGEST_NODE_ID, name="ingest_local", batch_num=0)
        job_stats = JobStats(
            job_id=JOB_ID,
            job_run_id=JOB_RUN_ID,
            status=ExecutionStatus.COMPLETED,
            node_stats={},
            batch_node_stats={INGEST_NODE_ID: {"batch-1": batch_stat}},
        )
        dag_nodes = [
            {"id": INGEST_NODE_ID, "name": "ingest_local", "input_edges": []},
            {"id": DEST_NODE_ID, "name": "vectordb", "input_edges": [INGEST_NODE_ID]},
        ]
        generator = JobReportGenerator(job_stats=job_stats, dag_nodes=dag_nodes)

        result = generator._find_first_batching_operator()

        assert result == INGEST_NODE_ID


class TestGenerateReportDataEndToEnd:
    """End-to-end tests for generate_report_data using mocked parquet reads."""

    def test_full_pipeline_with_ingested_doc(self):
        """A doc in docs_completed at destination → status=Ingested in report."""
        ingest_stats = NodeStats(id=INGEST_NODE_ID, name="ingest_local", start_time=1000)
        dest_stats = NodeStats(id=DEST_NODE_ID, name="vectordb", docs_completed=["doc-1"], end_time=1010)
        job_stats = JobStats(
            job_id=JOB_ID,
            job_run_id=JOB_RUN_ID,
            status=ExecutionStatus.COMPLETED,
            node_stats={INGEST_NODE_ID: ingest_stats, DEST_NODE_ID: dest_stats},
        )
        dag_nodes = [
            {"id": INGEST_NODE_ID, "name": "ingest_local", "input_edges": [], "output_edges": [DEST_NODE_ID]},
            {"id": DEST_NODE_ID, "name": "vectordb", "input_edges": [INGEST_NODE_ID], "output_edges": []},
        ]
        generator = JobReportGenerator(job_stats=job_stats, dag_nodes=dag_nodes)

        parquet_returns = {
            INGEST_NODE_ID: {"doc-1": {"id": "doc-1", "name": "file.pdf", "modified_time": 1704067200}},
        }

        def mock_read_parquet(node_id, batch_num=None, branch_index=0):
            return parquet_returns.get(node_id, {})

        with patch.object(generator, "_read_parquet_file", side_effect=mock_read_parquet):
            rows = generator.generate_report_data()

        assert len(rows) == 1
        assert rows[0]["GUID"] == "doc-1"
        assert rows[0]["File name"] == "file.pdf"
        assert rows[0]["Status"] == "Ingested"

    def test_full_pipeline_with_failed_doc(self):
        """A doc in failed_docs → status=Failed in report."""
        ingest_stats = NodeStats(id=INGEST_NODE_ID, name="ingest_local", failed_docs=["doc-2"])
        job_stats = JobStats(
            job_id=JOB_ID,
            job_run_id=JOB_RUN_ID,
            status=ExecutionStatus.COMPLETED_WITH_ERRORS,
            node_stats={INGEST_NODE_ID: ingest_stats},
        )
        dag_nodes = [
            {"id": INGEST_NODE_ID, "name": "ingest_local", "input_edges": [], "output_edges": []},
        ]
        generator = JobReportGenerator(job_stats=job_stats, dag_nodes=dag_nodes)

        parquet_returns = {
            INGEST_NODE_ID: {"doc-2": {"id": "doc-2", "name": "bad.pdf", "modified_time": None}},
        }

        with patch.object(generator, "_read_parquet_file", side_effect=lambda n, **_: parquet_returns.get(n, {})):
            rows = generator.generate_report_data()

        assert rows[0]["Status"] == "Failed"

    def test_full_pipeline_with_page_counts_from_extract(self):
        """Page count from extract parquet is reflected in the report row."""
        ingest_stats = NodeStats(id=INGEST_NODE_ID, name="ingest_local")
        dest_stats = NodeStats(id=DEST_NODE_ID, name="vectordb", docs_completed=["doc-3"])
        job_stats = JobStats(
            job_id=JOB_ID,
            job_run_id=JOB_RUN_ID,
            status=ExecutionStatus.COMPLETED,
            node_stats={INGEST_NODE_ID: ingest_stats, DEST_NODE_ID: dest_stats},
        )
        dag_nodes = [
            {"id": INGEST_NODE_ID, "name": "ingest_local", "input_edges": [], "output_edges": [EXTRACT_NODE_ID]},
            {
                "id": EXTRACT_NODE_ID,
                "name": "extract_op",
                "op": "extract",
                "input_edges": [INGEST_NODE_ID],
                "output_edges": [DEST_NODE_ID],
            },
            {"id": DEST_NODE_ID, "name": "vectordb", "input_edges": [EXTRACT_NODE_ID], "output_edges": []},
        ]
        generator = JobReportGenerator(job_stats=job_stats, dag_nodes=dag_nodes)

        parquet_returns = {
            INGEST_NODE_ID: {"doc-3": {"id": "doc-3", "name": "book.pdf", "modified_time": 1704067200}},
            EXTRACT_NODE_ID: {"doc-3": {"id": "doc-3", "pages_processed": 42}},
        }

        with patch.object(generator, "_read_parquet_file", side_effect=lambda n, **_: parquet_returns.get(n, {})):
            rows = generator.generate_report_data()

        assert rows[0]["Pages"] == "42"
        assert rows[0]["Status"] == "Ingested"


class TestUpdatePageCountFromParquet:
    """Tests for _update_page_count_from_parquet."""

    def _generator(self):
        job_stats = JobStats(job_id=JOB_ID, job_run_id=JOB_RUN_ID, status=ExecutionStatus.COMPLETED, node_stats={})
        return JobReportGenerator(job_stats=job_stats)

    def test_updates_page_count_from_pages_processed(self):
        """pages_processed field is written to all_docs."""
        generator = self._generator()
        all_docs = {"doc-1": {"pages": ""}}

        result = generator._update_page_count_from_parquet(all_docs, "doc-1", {"id": "doc-1", "pages_processed": 7})

        assert result is True
        assert all_docs["doc-1"]["pages"] == "7"

    def test_updates_page_count_from_page_count_field(self):
        """page_count field is used when pages_processed is absent."""
        generator = self._generator()
        all_docs = {"doc-1": {"pages": ""}}

        result = generator._update_page_count_from_parquet(all_docs, "doc-1", {"id": "doc-1", "page_count": 3})

        assert result is True
        assert all_docs["doc-1"]["pages"] == "3"

    def test_returns_false_when_doc_not_in_all_docs(self):
        """Returns False when doc_id is not in all_docs."""
        generator = self._generator()

        result = generator._update_page_count_from_parquet({}, "doc-99", {"id": "doc-99", "pages_processed": 1})

        assert result is False

    def test_returns_false_when_no_page_count_field(self):
        """Returns False when row_data has no pages_processed or page_count."""
        generator = self._generator()
        all_docs = {"doc-1": {"pages": ""}}

        result = generator._update_page_count_from_parquet(all_docs, "doc-1", {"id": "doc-1"})

        assert result is False


class TestCollectAllDocsFromNode:
    """Tests for _collect_all_docs_from_node."""

    def test_collects_union_of_total_failed_skipped(self):
        """Returns union of total_docs, failed_docs, and skipped_docs."""
        job_stats = JobStats(job_id=JOB_ID, job_run_id=JOB_RUN_ID, status=ExecutionStatus.COMPLETED, node_stats={})
        generator = JobReportGenerator(job_stats=job_stats)

        node_stats = NodeStats(
            id=INGEST_NODE_ID,
            name="ingest",
            total_docs=["doc-a"],
            failed_docs=["doc-b"],
            skipped_docs=["doc-c"],
        )

        result = generator._collect_all_docs_from_node(node_stats)

        assert result == {"doc-a", "doc-b", "doc-c"}

    def test_returns_empty_set_when_no_docs(self):
        """Returns empty set when all doc lists are empty."""
        job_stats = JobStats(job_id=JOB_ID, job_run_id=JOB_RUN_ID, status=ExecutionStatus.COMPLETED, node_stats={})
        generator = JobReportGenerator(job_stats=job_stats)

        result = generator._collect_all_docs_from_node(NodeStats(id="n", name="node"))

        assert result == set()


class TestFindExtractOperatorEdgeCases:
    """Edge cases for _find_extract_operator."""

    def test_returns_none_none_when_dag_nodes_empty(self):
        """Returns (None, None) when dag_nodes is empty."""
        job_stats = JobStats(job_id=JOB_ID, job_run_id=JOB_RUN_ID, status=ExecutionStatus.COMPLETED, node_stats={})
        generator = JobReportGenerator(job_stats=job_stats, dag_nodes=[])

        assert generator._find_extract_operator() == (None, None)

    def test_finds_extract_via_app_data_op_type(self):
        """Finds extract operator from nested app_data.op_type field."""
        dag_nodes = [
            {"id": EXTRACT_NODE_ID, "name": "Extract Step", "app_data": {"op_type": "extract_cpd"}},
        ]
        job_stats = JobStats(job_id=JOB_ID, job_run_id=JOB_RUN_ID, status=ExecutionStatus.COMPLETED, node_stats={})
        generator = JobReportGenerator(job_stats=job_stats, dag_nodes=dag_nodes)

        node_id, _ = generator._find_extract_operator()

        assert node_id == EXTRACT_NODE_ID

    def test_returns_none_none_when_no_extract_found(self):
        """Returns (None, None) when no node has extract in op type."""
        dag_nodes = [{"id": INGEST_NODE_ID, "name": "ingest", "op": "ingest_local"}]
        job_stats = JobStats(job_id=JOB_ID, job_run_id=JOB_RUN_ID, status=ExecutionStatus.COMPLETED, node_stats={})
        generator = JobReportGenerator(job_stats=job_stats, dag_nodes=dag_nodes)

        assert generator._find_extract_operator() == (None, None)


class TestHandleUnclassifiedDocument:
    """Tests for _handle_unclassified_document."""

    @pytest.mark.parametrize(
        "status",
        [ExecutionStatus.FAILED, ExecutionStatus.CANCELED, ExecutionStatus.COMPLETED_WITH_ERRORS],
    )
    def test_sets_failed_for_non_successful_job(self, status):
        """Unclassified doc in non-successful job → Failed."""
        job_stats = JobStats(job_id=JOB_ID, job_run_id=JOB_RUN_ID, status=status, node_stats={})
        generator = JobReportGenerator(job_stats=job_stats)
        doc_info = {"status": "", "reason": ""}

        generator._handle_unclassified_document("doc-x", doc_info)

        assert doc_info["status"] == "Failed"

    def test_sets_unknown_for_completed_job(self):
        """Unclassified doc in COMPLETED job → Unknown."""
        job_stats = JobStats(job_id=JOB_ID, job_run_id=JOB_RUN_ID, status=ExecutionStatus.COMPLETED, node_stats={})
        generator = JobReportGenerator(job_stats=job_stats)
        doc_info = {"status": "", "reason": ""}

        generator._handle_unclassified_document("doc-x", doc_info)

        assert doc_info["status"] == "Unknown"


class TestInitFlowDef:
    """Line 103 — __init__ flow_def branch."""

    def test_init_with_flow_def_extracts_dag_nodes(self):
        """When dag_nodes is None and flow_def is provided, nodes come from flow_def."""
        job_stats = JobStats(job_id=JOB_ID, job_run_id=JOB_RUN_ID, status=ExecutionStatus.COMPLETED, node_stats={})
        flow_def = {"dag": {"nodes": [{"id": INGEST_NODE_ID, "name": "ingest"}]}}

        generator = JobReportGenerator(job_stats=job_stats, flow_def=flow_def)

        assert generator.dag_nodes == [{"id": INGEST_NODE_ID, "name": "ingest"}]


class TestSaveReportToFileNoCsvContent:
    """Line 318-319 — save_report_to_file without pre-generated csv_content."""

    def test_generates_csv_internally_when_csv_content_is_none(self, tmp_path):
        """When csv_content is None, generate_csv_content is called internally."""
        from unittest.mock import Mock

        from docpipe.core.models.session_info import create_session_info

        create_session_info(job_id=JOB_ID, job_run_id=JOB_RUN_ID)
        job_stats = JobStats(job_id=JOB_ID, job_run_id=JOB_RUN_ID, status=ExecutionStatus.COMPLETED, node_stats={})
        generator = JobReportGenerator(job_stats=job_stats)

        mock_csv = "GUID,File name\ndoc1,f.pdf\n"
        mock_adapter = Mock()
        mock_adapter.write_text.return_value = str(tmp_path / "r.csv")

        with (
            patch.object(generator, "generate_csv_content", return_value=mock_csv) as mock_gen,
            patch(
                "docpipe.core.job_management.adapters.config.report_storage_factory.get_report_storage",
                return_value=mock_adapter,
            ),
        ):
            generator.save_report_to_file()  # no csv_content kwarg

        mock_gen.assert_called_once()


class TestGetActualBatchNums:
    """Lines 381-391 — batch_num extraction from batch_node_stats."""

    def test_returns_batch_nums_from_batch_node_stats(self):
        """Batch numbers are extracted from batch_node_stats for the given node."""
        batch_stat_0 = NodeStats(id=INGEST_NODE_ID, name="ingest", batch_num=0)
        batch_stat_1 = NodeStats(id=INGEST_NODE_ID, name="ingest", batch_num=1)
        job_stats = JobStats(
            job_id=JOB_ID,
            job_run_id=JOB_RUN_ID,
            status=ExecutionStatus.COMPLETED,
            node_stats={},
            batch_node_stats={INGEST_NODE_ID: {"b0": batch_stat_0, "b1": batch_stat_1}},
        )
        generator = JobReportGenerator(job_stats=job_stats)

        result = generator._get_actual_batch_nums(INGEST_NODE_ID)

        assert result == {0, 1}

    def test_returns_none_set_when_node_not_in_batch_node_stats(self):
        """Returns {None} when the node is not present in batch_node_stats."""
        job_stats = JobStats(
            job_id=JOB_ID,
            job_run_id=JOB_RUN_ID,
            status=ExecutionStatus.COMPLETED,
            node_stats={},
            batch_node_stats={EXTRACT_NODE_ID: {}},
        )
        generator = JobReportGenerator(job_stats=job_stats)

        result = generator._get_actual_batch_nums(INGEST_NODE_ID)

        assert result == {None}


class TestFindExtractOperatorNoId:
    """Line 411 — skip node with no id field."""

    def test_skips_nodes_without_id(self):
        """Nodes missing the 'id' key are skipped without error."""
        dag_nodes = [
            {"name": "no_id_node", "op": "extract"},  # no "id" key
            {"id": EXTRACT_NODE_ID, "name": "real_extract", "op": "extract_operator"},
        ]
        job_stats = JobStats(job_id=JOB_ID, job_run_id=JOB_RUN_ID, status=ExecutionStatus.COMPLETED, node_stats={})
        generator = JobReportGenerator(job_stats=job_stats, dag_nodes=dag_nodes)

        node_id, _ = generator._find_extract_operator()

        assert node_id == EXTRACT_NODE_ID


class TestGetTimestampException:
    """Lines 456-458 — exception path in _get_timestamp_from_modified_time."""

    def test_returns_empty_string_on_invalid_numeric_timestamp(self):
        """Returns '' when timestamp conversion raises (e.g. out-of-range epoch)."""
        job_stats = JobStats(job_id=JOB_ID, job_run_id=JOB_RUN_ID, status=ExecutionStatus.COMPLETED, node_stats={})
        generator = JobReportGenerator(job_stats=job_stats)

        # Very large float triggers OverflowError in datetime.fromtimestamp
        result = generator._get_timestamp_from_modified_time(float("inf"), "doc-1")

        assert result == ""


class TestFindFirstBatchingOperatorEdgeCases:
    """Lines 499-500, 513-517 — edge cases in _find_first_batching_operator."""

    def test_returns_none_when_batch_node_stats_is_empty_dict(self):
        """Returns None when batch_node_stats exists but has no entries."""
        job_stats = JobStats(
            job_id=JOB_ID,
            job_run_id=JOB_RUN_ID,
            status=ExecutionStatus.COMPLETED,
            node_stats={},
            batch_node_stats={},
        )
        generator = JobReportGenerator(job_stats=job_stats)

        assert generator._find_first_batching_operator() is None

    def test_falls_back_to_first_key_when_no_dag_nodes(self):
        """Without DAG nodes, returns the first key in batch_node_stats."""
        batch_stat = NodeStats(id=INGEST_NODE_ID, name="ingest", batch_num=0)
        job_stats = JobStats(
            job_id=JOB_ID,
            job_run_id=JOB_RUN_ID,
            status=ExecutionStatus.COMPLETED,
            node_stats={},
            batch_node_stats={INGEST_NODE_ID: {"b0": batch_stat}},
        )
        # No dag_nodes — forces the "no DAG" fallback path (lines 513-517)
        generator = JobReportGenerator(job_stats=job_stats, dag_nodes=[])

        result = generator._find_first_batching_operator()

        assert result == INGEST_NODE_ID


class TestGetAllBatchDocs:
    """Lines 521-524 — _get_all_batch_docs."""

    def test_unions_total_failed_skipped_from_node_stats_object(self):
        """Returns union of total_docs, failed_docs, skipped_docs from a NodeStats object."""
        batch_stats = NodeStats(
            id=INGEST_NODE_ID,
            name="ingest",
            total_docs=["doc-a"],
            failed_docs=["doc-b"],
            skipped_docs=["doc-c"],
        )
        job_stats = JobStats(job_id=JOB_ID, job_run_id=JOB_RUN_ID, status=ExecutionStatus.COMPLETED, node_stats={})
        generator = JobReportGenerator(job_stats=job_stats)

        result = generator._get_all_batch_docs(batch_stats)

        assert result == {"doc-a", "doc-b", "doc-c"}

    def test_unions_total_failed_skipped_from_dict(self):
        """Returns union from a plain dict batch_stats."""
        batch_stats = {"total_docs": ["doc-1"], "failed_docs": ["doc-2"], "skipped_docs": []}
        job_stats = JobStats(job_id=JOB_ID, job_run_id=JOB_RUN_ID, status=ExecutionStatus.COMPLETED, node_stats={})
        generator = JobReportGenerator(job_stats=job_stats)

        result = generator._get_all_batch_docs(batch_stats)

        assert result == {"doc-1", "doc-2"}


class TestFindDocEndTimeInDestinations:
    """Lines 542-557 — _find_doc_end_time_in_destinations."""

    def _generator_with_batch_stats(self, batch_node_stats):
        """Build a generator with batch_node_stats injected directly (bypassing Pydantic)."""
        job_stats = JobStats(job_id=JOB_ID, job_run_id=JOB_RUN_ID, status=ExecutionStatus.COMPLETED, node_stats={})
        generator = JobReportGenerator(job_stats=job_stats)
        generator.job_stats = type(generator.job_stats).model_construct(
            **{**generator.job_stats.model_dump(), "batch_node_stats": batch_node_stats}
        )
        return generator

    def test_returns_end_time_when_doc_found_in_destination(self):
        """Returns (end_time, True) when doc appears in the destination batch."""
        dest_batch = {"total_docs": ["doc-1"], "failed_docs": [], "skipped_docs": [], "end_time": 2000}
        generator = self._generator_with_batch_stats({DEST_NODE_ID: {"batch-1": dest_batch}})

        end_time, found = generator._find_doc_end_time_in_destinations(
            "doc-1", "batch-1", [DEST_NODE_ID], ingest_start_time=1000.0
        )

        assert found is True
        assert end_time == 2000

    def test_returns_ingest_start_time_when_doc_not_in_any_destination(self):
        """Returns (ingest_start_time, False) when doc not found in any destination."""
        job_stats = JobStats(job_id=JOB_ID, job_run_id=JOB_RUN_ID, status=ExecutionStatus.COMPLETED, node_stats={})
        generator = JobReportGenerator(job_stats=job_stats)

        end_time, found = generator._find_doc_end_time_in_destinations(
            "doc-x", "batch-1", [DEST_NODE_ID], ingest_start_time=500.0
        )

        assert found is False
        assert end_time == pytest.approx(500.0)

    def test_skips_destination_node_not_in_batch_node_stats(self):
        """Destination node absent from batch_node_stats is skipped silently."""
        job_stats = JobStats(job_id=JOB_ID, job_run_id=JOB_RUN_ID, status=ExecutionStatus.COMPLETED, node_stats={})
        generator = JobReportGenerator(job_stats=job_stats)

        _, found = generator._find_doc_end_time_in_destinations(
            "doc-1", "batch-1", [DEST_NODE_ID], ingest_start_time=0.0
        )

        assert found is False

    def test_skips_destination_when_batch_id_not_present(self):
        """Destination node present but batch_id missing — skipped."""
        dest_batch = {"total_docs": ["doc-1"], "failed_docs": [], "skipped_docs": [], "end_time": 2000}
        generator = self._generator_with_batch_stats({DEST_NODE_ID: {"other-batch": dest_batch}})

        _, found = generator._find_doc_end_time_in_destinations(
            "doc-1", "batch-1", [DEST_NODE_ID], ingest_start_time=0.0
        )

        assert found is False

    def test_uses_ingest_start_time_when_end_time_is_none(self):
        """When end_time is None on the dest batch, falls back to ingest_start_time."""
        dest_batch = {"total_docs": ["doc-1"], "failed_docs": [], "skipped_docs": [], "end_time": None}
        generator = self._generator_with_batch_stats({DEST_NODE_ID: {"batch-1": dest_batch}})

        end_time, found = generator._find_doc_end_time_in_destinations(
            "doc-1", "batch-1", [DEST_NODE_ID], ingest_start_time=750.0
        )

        assert found is True
        assert end_time == pytest.approx(750.0)


class TestFindDocMaxEndTimeInAllNodes:
    """Lines 561-575 — _find_doc_max_end_time_in_all_nodes."""

    def _generator_with_batch_stats(self, batch_node_stats):
        job_stats = JobStats(job_id=JOB_ID, job_run_id=JOB_RUN_ID, status=ExecutionStatus.COMPLETED, node_stats={})
        generator = JobReportGenerator(job_stats=job_stats)
        generator.job_stats = type(generator.job_stats).model_construct(
            **{**generator.job_stats.model_dump(), "batch_node_stats": batch_node_stats}
        )
        return generator

    def test_returns_max_end_time_across_all_nodes(self):
        """Returns the highest end_time from all nodes that contain the doc."""
        batch_a = {"total_docs": ["doc-1"], "failed_docs": [], "skipped_docs": [], "end_time": 1500}
        batch_b = {"total_docs": ["doc-1"], "failed_docs": [], "skipped_docs": [], "end_time": 2000}
        generator = self._generator_with_batch_stats(
            {
                INGEST_NODE_ID: {"batch-1": batch_a},
                DEST_NODE_ID: {"batch-1": batch_b},
            }
        )

        result = generator._find_doc_max_end_time_in_all_nodes("doc-1", "batch-1", ingest_start_time=1000.0)

        assert result == pytest.approx(2000.0)

    def test_returns_ingest_start_time_when_doc_not_found(self):
        """Returns ingest_start_time when doc is not in any node batch."""
        generator = self._generator_with_batch_stats(
            {INGEST_NODE_ID: {"batch-1": {"total_docs": [], "failed_docs": [], "skipped_docs": [], "end_time": 2000}}}
        )

        result = generator._find_doc_max_end_time_in_all_nodes("no-such-doc", "batch-1", ingest_start_time=1000.0)

        assert result == pytest.approx(1000.0)


class TestProcessBatchDocuments:
    """Lines 586-601 — _process_batch_documents."""

    def _generator_with_batch_stats(self, batch_node_stats):
        job_stats = JobStats(job_id=JOB_ID, job_run_id=JOB_RUN_ID, status=ExecutionStatus.COMPLETED, node_stats={})
        generator = JobReportGenerator(job_stats=job_stats)
        generator.job_stats = type(generator.job_stats).model_construct(
            **{**generator.job_stats.model_dump(), "batch_node_stats": batch_node_stats}
        )
        return generator

    def test_calculates_processing_time_for_each_doc(self):
        """Each doc in the batch gets a processing time entry."""
        batch_stats = {"total_docs": ["doc-1", "doc-2"], "failed_docs": [], "skipped_docs": [], "end_time": 1050}
        dest_batch = {"total_docs": ["doc-1", "doc-2"], "failed_docs": [], "skipped_docs": [], "end_time": 1050}
        dag_nodes = [
            {"id": INGEST_NODE_ID, "output_edges": [DEST_NODE_ID]},
            {"id": DEST_NODE_ID, "output_edges": []},
        ]
        generator = self._generator_with_batch_stats({DEST_NODE_ID: {"batch-1": dest_batch}})
        generator.dag_nodes = dag_nodes
        doc_to_processing_time: dict = {}

        generator._process_batch_documents("batch-1", batch_stats, [DEST_NODE_ID], 1000.0, doc_to_processing_time)

        assert doc_to_processing_time["doc-1"] == "50"
        assert doc_to_processing_time["doc-2"] == "50"

    def test_skips_empty_batch(self):
        """Empty batch_stats produces no entries."""
        batch_stats: dict = {"total_docs": [], "failed_docs": [], "skipped_docs": []}
        job_stats = JobStats(job_id=JOB_ID, job_run_id=JOB_RUN_ID, status=ExecutionStatus.COMPLETED, node_stats={})
        generator = JobReportGenerator(job_stats=job_stats)
        doc_to_processing_time: dict = {}

        generator._process_batch_documents("batch-1", batch_stats, [], 1000.0, doc_to_processing_time)

        assert doc_to_processing_time == {}


class TestCollectDestinationTimes:
    """Line 609 — dest node not in node_stats is skipped."""

    def test_skips_destination_node_not_in_node_stats(self):
        """A destination node_id that has no NodeStats entry is silently skipped."""
        job_stats = JobStats(job_id=JOB_ID, job_run_id=JOB_RUN_ID, status=ExecutionStatus.COMPLETED, node_stats={})
        generator = JobReportGenerator(job_stats=job_stats)

        result = generator._collect_destination_times(1000.0, [DEST_NODE_ID])

        assert result == {}


class TestTrackMaxEndTimes:
    """Lines 641-642 — _track_max_end_times update logic."""

    def test_keeps_highest_end_time_per_doc_across_nodes(self):
        """When the same doc appears in two nodes, the higher end_time wins."""
        stats_a = NodeStats(id=INGEST_NODE_ID, name="ingest", total_docs=["doc-1"], end_time=1500)
        stats_b = NodeStats(id=DEST_NODE_ID, name="dest", total_docs=["doc-1"], end_time=2000)
        job_stats = JobStats(
            job_id=JOB_ID,
            job_run_id=JOB_RUN_ID,
            status=ExecutionStatus.COMPLETED,
            node_stats={INGEST_NODE_ID: stats_a, DEST_NODE_ID: stats_b},
        )
        generator = JobReportGenerator(job_stats=job_stats)

        result = generator._track_max_end_times()

        assert result["doc-1"] == 2000


class TestBuildDocToBatchMappingFallbackNonDestDoc:
    """Lines 669-671 — non-destination doc uses max end time."""

    def test_assigns_max_end_time_for_docs_not_reaching_destination(self):
        """Docs that only appear in non-destination nodes get max-end-time processing time."""
        # doc-99 is in a non-dest node only — never reaches destination
        ingest_stats = NodeStats(
            id=INGEST_NODE_ID, name="ingest", total_docs=["doc-99"], start_time=1000, end_time=1080
        )
        job_stats = JobStats(
            job_id=JOB_ID,
            job_run_id=JOB_RUN_ID,
            status=ExecutionStatus.COMPLETED,
            node_stats={INGEST_NODE_ID: ingest_stats},
        )
        dag_nodes = [
            {"id": INGEST_NODE_ID, "name": "ingest", "input_edges": [], "output_edges": []},
        ]
        generator = JobReportGenerator(job_stats=job_stats, dag_nodes=dag_nodes)

        mapping = generator._build_doc_to_batch_mapping_fallback()

        assert mapping["doc-99"] == "80"


class TestBuildDocToBatchMappingBatchPath:
    """Lines 693-719 — full batch-level timing path in _build_doc_to_batch_mapping."""

    def test_uses_batch_level_timing_when_batch_stats_available(self):
        """When batch_node_stats are present and first batching node is found, uses batch timing."""
        batch_stats = {"total_docs": ["doc-1"], "failed_docs": [], "skipped_docs": [], "end_time": 1060}
        dest_batch = {"total_docs": ["doc-1"], "failed_docs": [], "skipped_docs": [], "end_time": 1060}
        ingest_node_stats = NodeStats(id=INGEST_NODE_ID, name="ingest_local", start_time=1000)
        dag_nodes = [
            {"id": INGEST_NODE_ID, "name": "ingest_local", "input_edges": [], "output_edges": [DEST_NODE_ID]},
            {"id": DEST_NODE_ID, "name": "vectordb", "input_edges": [INGEST_NODE_ID], "output_edges": []},
        ]
        job_stats = JobStats(
            job_id=JOB_ID,
            job_run_id=JOB_RUN_ID,
            status=ExecutionStatus.COMPLETED,
            node_stats={INGEST_NODE_ID: ingest_node_stats},
        )
        generator = JobReportGenerator(job_stats=job_stats, dag_nodes=dag_nodes)
        # Inject raw-dict batch_node_stats without going through Pydantic validation
        from unittest.mock import MagicMock

        mock_job_stats = MagicMock(wraps=job_stats)
        mock_job_stats.node_stats = job_stats.node_stats
        mock_job_stats.batch_node_stats = {
            INGEST_NODE_ID: {"batch-1": batch_stats},
            DEST_NODE_ID: {"batch-1": dest_batch},
        }
        generator.job_stats = mock_job_stats

        result = generator._build_doc_to_batch_mapping()

        assert result["doc-1"] == "60"


class TestReadParquetFile:
    """Lines 774-822 — _read_parquet_file file-not-found and error paths."""

    @pytest.mark.parametrize("batch_num", [None, 0])
    def test_reads_parquet_from_configured_data_path(self, *, tmp_path, monkeypatch, batch_num):
        import pyarrow as pa
        import pyarrow.parquet as pq

        monkeypatch.setenv("DOCPIPE_DATA_PATH", str(tmp_path))
        job_stats = JobStats(job_id="j1", job_run_id="r1", status=ExecutionStatus.COMPLETED, node_stats={})
        dag_nodes = [{"id": INGEST_NODE_ID, "name": "ingest-local", "input_edges": []}]
        generator = JobReportGenerator(job_stats=job_stats, dag_nodes=dag_nodes)
        output_dir = tmp_path / "j1" / "r1" / "data" / "ingest_local_0"
        if batch_num is not None:
            output_dir /= str(batch_num)
        output_dir.mkdir(parents=True)
        document = {"id": "doc-1", "name": "invoice.pdf", "modified_time": "2026-10-08"}
        pq.write_table(pa.Table.from_pylist([document]), output_dir / "output.parquet")

        assert generator._read_parquet_file(INGEST_NODE_ID, batch_num=batch_num) == {"doc-1": document}

    def test_returns_empty_dict_when_parquet_file_not_found(self, tmp_path):
        """Returns {} when the expected parquet path does not exist."""
        job_stats = JobStats(job_id="j1", job_run_id="r1", status=ExecutionStatus.COMPLETED, node_stats={})
        dag_nodes = [{"id": INGEST_NODE_ID, "name": "ingest_local", "input_edges": []}]
        generator = JobReportGenerator(job_stats=job_stats, dag_nodes=dag_nodes)

        # No file created — path will not exist
        result = generator._read_parquet_file(INGEST_NODE_ID)

        assert result == {}

    def test_returns_empty_dict_and_logs_on_exception(self):
        """Returns {} when pq.read_table raises an unexpected exception."""
        from pathlib import Path

        import pyarrow.parquet as pq

        job_stats = JobStats(job_id="j1", job_run_id="r1", status=ExecutionStatus.COMPLETED, node_stats={})
        dag_nodes = [{"id": INGEST_NODE_ID, "name": "ingest_local", "input_edges": []}]
        generator = JobReportGenerator(job_stats=job_stats, dag_nodes=dag_nodes)

        with (
            patch.object(Path, "exists", return_value=True),
            patch.object(pq, "read_table", side_effect=RuntimeError("corrupt file")),
        ):
            result = generator._read_parquet_file(INGEST_NODE_ID)

        assert result == {}

    def test_builds_batch_path_when_batch_num_provided(self):
        """Constructs the batch-subdirectory path when batch_num is not None."""
        job_stats = JobStats(job_id="j1", job_run_id="r1", status=ExecutionStatus.COMPLETED, node_stats={})
        dag_nodes = [{"id": INGEST_NODE_ID, "name": "ingest_local", "input_edges": []}]
        generator = JobReportGenerator(job_stats=job_stats, dag_nodes=dag_nodes)

        # File doesn't exist — we just verify no exception and empty result
        result = generator._read_parquet_file(INGEST_NODE_ID, batch_num=0)

        assert result == {}


class TestReadPageCountsFromBatches:
    """Line 902-903 — empty extract data branch in _read_page_counts_from_batches."""

    def test_skips_batch_when_extract_parquet_returns_empty(self):
        """When _read_parquet_file returns {} for a batch, it is skipped (updated_count stays 0)."""
        job_stats = JobStats(job_id=JOB_ID, job_run_id=JOB_RUN_ID, status=ExecutionStatus.COMPLETED, node_stats={})
        generator = JobReportGenerator(job_stats=job_stats)

        with patch.object(generator, "_read_parquet_file", return_value={}):
            count = generator._read_page_counts_from_batches({}, EXTRACT_NODE_ID, {None})

        assert count == 0


class TestExtractReasonFromNodeMetadataNonDict:
    """Lines 1026, 1031 — non-dict entries in node_metadata_list are skipped."""

    def test_skips_non_dict_node_meta_entries(self):
        """Non-dict items in node_metadata_list are skipped without error."""
        job_stats = JobStats(job_id=JOB_ID, job_run_id=JOB_RUN_ID, status=ExecutionStatus.COMPLETED)
        # Mix a non-dict entry with a valid one that has no matching doc
        generator = JobReportGenerator(
            job_stats=job_stats,
            node_metadata_list=["not-a-dict", 42],
        )

        result = generator._extract_reason_from_node_metadata("doc-1", "failed_docs")

        assert result is None

    def test_skips_entries_where_node_metadata_is_not_dict(self):
        """Entries where nested node_metadata value is not a dict are skipped."""
        job_stats = JobStats(job_id=JOB_ID, job_run_id=JOB_RUN_ID, status=ExecutionStatus.COMPLETED)
        generator = JobReportGenerator(
            job_stats=job_stats,
            node_metadata_list=[{"id": "n1", "node_metadata": "not-a-dict"}],
        )

        result = generator._extract_reason_from_node_metadata("doc-1", "failed_docs")

        assert result is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

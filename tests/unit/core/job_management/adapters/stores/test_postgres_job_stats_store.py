"""
Unit tests for PostgresJobStatsStore.

These tests focus on the adapter's interface and translation logic.
Integration tests with a real PostgreSQL database are documented as a gap.
"""

from unittest.mock import Mock, patch

import pytest

from docpipe.core.constants.constants import ExecutionStatus
from docpipe.core.job_management.domain.models import JobStats, NodeStats
from docpipe.exceptions.docpipe_exceptions import JobStatsStoreInitializationException


class TestPostgresJobStatsStoreInterface:
    """
    Test PostgresJobStatsStore interface without requiring real database.

    Integration Gap: These are unit tests that mock database operations.
    Full integration tests with PostgreSQL are needed for production validation.
    """

    @pytest.fixture
    def mock_engine(self):
        """Mock SQLAlchemy engine."""
        return Mock()

    @pytest.fixture
    def mock_session_factory(self):
        """Mock session factory."""
        return Mock()

    @pytest.fixture
    def mock_job_stats_dal(self):
        """Mock JobStatsDAL."""
        return Mock()

    @pytest.fixture
    def mock_node_stats_dal(self):
        """Mock NodeStatsDAL."""
        return Mock()

    @pytest.fixture
    def sample_job_stats_dto(self):
        """Sample JobStats for testing."""
        return JobStats(
            job_id="12345678-1234-1234-1234-123456789012",
            job_run_id="87654321-4321-4321-4321-210987654321",
            status=ExecutionStatus.RUNNING,
            message="Test job",
            start_time=1704067200,
            end_time=0,
            duration=0,
            total_docs=100,
            processed_docs=50,
            completed_docs=45,
            failed_docs=5,
            skipped_docs=0,
        )

    @pytest.fixture
    def sample_node_stats_dto(self):
        """Sample NodeStats for testing."""
        return NodeStats(
            id="abcdef12-3456-7890-abcd-ef1234567890",
            name="Test Node",
            node_status=ExecutionStatus.COMPLETED,
            start_time=1704067200,
            end_time=1704067260,
            time_taken=60,
            total_docs=["doc1", "doc2"],
            docs_completed=["doc1", "doc2"],
            failed_docs=[],
            skipped_docs=[],
            batch_id=None,
        )

    @patch(
        "docpipe.core.job_management.adapters.stores.postgres.postgres_job_stats_store.get_postgres_connection_string"
    )
    @patch("docpipe.core.job_management.adapters.stores.postgres.postgres_job_stats_store.create_postgres_engine")
    @patch("docpipe.core.job_management.adapters.stores.postgres.postgres_job_stats_store.create_session_factory")
    @patch("docpipe.core.job_management.adapters.stores.postgres.postgres_job_stats_store.JobStatsDAL")
    @patch("docpipe.core.job_management.adapters.stores.postgres.postgres_job_stats_store.NodeStatsDAL")
    def test_initialization_success(
        self,
        mock_node_dal_class,
        mock_job_dal_class,
        mock_create_session,
        mock_create_engine,
        mock_get_conn_str,
    ):
        """Test successful initialization of PostgresJobStatsStore."""
        from docpipe.core.job_management.adapters.stores.postgres import PostgresJobStatsStore

        # Setup mocks
        mock_get_conn_str.return_value = "postgresql://user:pass@localhost/db"  # pragma: allowlist secret
        mock_engine = Mock()
        mock_create_engine.return_value = mock_engine
        mock_session_factory = Mock()
        mock_create_session.return_value = mock_session_factory

        # Initialize store
        store = PostgresJobStatsStore()

        # Verify initialization
        assert store is not None
        mock_get_conn_str.assert_called_once()
        mock_create_engine.assert_called_once()
        mock_create_session.assert_called_once_with(engine=mock_engine)
        mock_job_dal_class.assert_called_once_with(session_factory=mock_session_factory, model=None)
        mock_node_dal_class.assert_called_once_with(session_factory=mock_session_factory, model=None)

    @patch(
        "docpipe.core.job_management.adapters.stores.postgres.postgres_job_stats_store.get_postgres_connection_string"
    )
    def test_initialization_failure_no_password(self, mock_get_conn_str):
        """Test initialization fails when PostgreSQL password not set."""
        from docpipe.core.job_management.adapters.stores.postgres import PostgresJobStatsStore

        mock_get_conn_str.return_value = None

        with pytest.raises(
            JobStatsStoreInitializationException,
            match="PostgreSQL connection not configured",
        ):
            PostgresJobStatsStore()

    def test_store_job_stats_interface(self, sample_job_stats_dto):
        """
        Test store_job_stats interface (mocked).

        Integration Gap: This tests the interface, not actual database operations.
        """
        from docpipe.core.job_management.adapters.stores.postgres import PostgresJobStatsStore

        with patch.object(PostgresJobStatsStore, "__init__", lambda x: None):
            store = PostgresJobStatsStore()
            store._job_stats_dal = Mock()
            store._job_stats_model_cls = None

            # Call store_job_stats
            store.store_job_stats(sample_job_stats_dto)

            # Verify DAL was called
            store._job_stats_dal.upsert.assert_called_once()

    def test_get_job_stats_interface(self, sample_job_stats_dto):
        """
        Test get_job_stats interface (mocked).

        Integration Gap: This tests the interface, not actual database operations.
        """
        from docpipe.core.job_management.adapters.stores.postgres import PostgresJobStatsStore
        from docpipe.core.job_management.adapters.stores.postgres.models import JobStatsModel

        with patch.object(PostgresJobStatsStore, "__init__", lambda x: None):
            store = PostgresJobStatsStore()
            store._job_stats_dal = Mock()

            # Mock DAL response - use the fixture's job_run_id
            mock_job_run_stats = Mock(spec=JobStatsModel)
            mock_job_run_stats.job_id = sample_job_stats_dto.job_id
            mock_job_run_stats.job_run_id = sample_job_stats_dto.job_run_id
            mock_job_run_stats.status = sample_job_stats_dto.status.value
            mock_job_run_stats.message = sample_job_stats_dto.message
            mock_job_run_stats.start_time = sample_job_stats_dto.start_time
            mock_job_run_stats.end_time = sample_job_stats_dto.end_time
            mock_job_run_stats.duration = sample_job_stats_dto.duration
            mock_job_run_stats.total_docs = sample_job_stats_dto.total_docs
            mock_job_run_stats.processed_docs = sample_job_stats_dto.processed_docs
            mock_job_run_stats.completed_docs = sample_job_stats_dto.completed_docs
            mock_job_run_stats.failed_docs = sample_job_stats_dto.failed_docs
            mock_job_run_stats.skipped_docs = sample_job_stats_dto.skipped_docs
            mock_job_run_stats.heartbeat_timestamp = None
            mock_job_run_stats.progress_timestamp = 0
            mock_job_run_stats.deleted_doc_count = 0
            mock_job_run_stats.total_pages_processed = 0
            mock_job_run_stats.page_type_stats = {}
            mock_job_run_stats.execution_time = 0
            mock_job_run_stats.orchestrator = "Python"
            mock_job_run_stats.container_kind = None
            mock_job_run_stats.container_id = None
            mock_job_run_stats.flow_id = None
            mock_job_run_stats.flow_name = None
            mock_job_run_stats.user_id = None
            mock_job_run_stats.account_id = None
            mock_job_run_stats.user_entitlements = None
            mock_job_run_stats.report_status = None
            mock_job_run_stats.report_generation_started_at = None
            mock_job_run_stats.report_generation_completed_at = None

            store._job_stats_dal.get_by_job_run_id.return_value = mock_job_run_stats

            # Call get_job_stats with the fixture's job_run_id
            result = store.get_job_stats(sample_job_stats_dto.job_run_id)

            # Verify result
            assert result is not None
            assert result.job_run_id == sample_job_stats_dto.job_run_id
            store._job_stats_dal.get_by_job_run_id.assert_called_once_with(job_run_id=sample_job_stats_dto.job_run_id)

    def test_store_node_stats_interface(self, sample_node_stats_dto):
        """
        Test store_node_stats interface (mocked).

        Integration Gap: This tests the interface, not actual database operations.
        """
        from docpipe.core.job_management.adapters.stores.postgres import PostgresJobStatsStore

        with patch.object(PostgresJobStatsStore, "__init__", lambda x: None):
            store = PostgresJobStatsStore()
            store._node_stats_dal = Mock()
            store._node_stats_model_cls = None

            # Call store_node_stats
            store.store_node_stats(job_run_id="test-run-456", node_stats=sample_node_stats_dto)

            # Verify DAL was called
            store._node_stats_dal.upsert.assert_called_once()

    def test_atomic_increment_fields_interface(self):
        """
        Test atomic_increment_fields interface (mocked).

        Integration Gap: This tests the interface, not actual atomic operations.
        """
        from docpipe.core.job_management.adapters.stores.postgres import PostgresJobStatsStore

        with patch.object(PostgresJobStatsStore, "__init__", lambda x: None):
            store = PostgresJobStatsStore()
            store._job_stats_dal = Mock()

            # Call atomic_increment_fields
            store.atomic_increment_fields(
                job_run_id="test-run-456",
                increments={"processed_docs": 10},
                updates={"status": ExecutionStatus.RUNNING},
            )

            # Verify DAL was called
            store._job_stats_dal.atomic_increment_fields.assert_called_once_with(
                job_run_id="test-run-456",
                increments={"processed_docs": 10},
                updates={"status": ExecutionStatus.RUNNING},
                jsonb_merges=None,
            )

    def test_bulk_store_node_stats_interface(self, sample_node_stats_dto):
        """
        Test bulk_store_node_stats interface (mocked).

        Integration Gap: This tests the interface, not actual bulk operations.
        """
        from docpipe.core.job_management.adapters.stores.postgres import PostgresJobStatsStore

        with patch.object(PostgresJobStatsStore, "__init__", lambda x: None):
            store = PostgresJobStatsStore()
            store._node_stats_dal = Mock()
            store._node_stats_model_cls = None

            # Call bulk_store_node_stats
            node_stats_list = [sample_node_stats_dto]
            store.bulk_store_node_stats(job_run_id="test-run-456", node_stats_list=node_stats_list)

            # Verify DAL was called
            store._node_stats_dal.bulk_insert.assert_called_once()

    def test_delete_job_stats_interface(self):
        """
        Test delete_job_stats interface (mocked).

        Integration Gap: This tests the interface, not actual delete operations.
        """
        from docpipe.core.job_management.adapters.stores.postgres import PostgresJobStatsStore

        with patch.object(PostgresJobStatsStore, "__init__", lambda x: None):
            store = PostgresJobStatsStore()
            store._job_stats_dal = Mock()
            store._job_stats_dal.delete_job_stats.return_value = 1

            # Call delete_job_stats
            store.delete_job_stats("test-run-456")

            # Verify DAL was called
            store._job_stats_dal.delete_job_stats.assert_called_once_with(job_run_id="test-run-456")

    def test_list_job_runs_interface(self):
        """
        Test list_job_runs interface (mocked).

        Integration Gap: This tests the interface, not actual query operations.
        """
        from docpipe.core.job_management.adapters.stores.postgres import PostgresJobStatsStore
        from docpipe.core.job_management.adapters.stores.postgres.models import JobStatsModel

        with patch.object(PostgresJobStatsStore, "__init__", lambda x: None):
            store = PostgresJobStatsStore()
            store._job_stats_dal = Mock()

            # Use consistent job_id throughout the test
            test_job_id = "12345678-1234-1234-1234-123456789012"

            # Mock DAL response
            mock_job_run_stats = Mock(spec=JobStatsModel)
            mock_job_run_stats.job_id = test_job_id
            mock_job_run_stats.job_run_id = "87654321-4321-4321-4321-210987654321"
            mock_job_run_stats.status = ExecutionStatus.COMPLETED.value
            mock_job_run_stats.start_time = 1704067200
            mock_job_run_stats.message = "Success"
            mock_job_run_stats.end_time = 0
            mock_job_run_stats.duration = 0
            mock_job_run_stats.total_docs = 100
            mock_job_run_stats.processed_docs = 100
            mock_job_run_stats.completed_docs = 100
            mock_job_run_stats.failed_docs = 0
            mock_job_run_stats.skipped_docs = 0
            mock_job_run_stats.heartbeat_timestamp = None
            mock_job_run_stats.progress_timestamp = 0
            mock_job_run_stats.deleted_doc_count = 0
            mock_job_run_stats.total_pages_processed = 0
            mock_job_run_stats.page_type_stats = {}
            mock_job_run_stats.execution_time = 0
            mock_job_run_stats.orchestrator = "Python"
            mock_job_run_stats.container_kind = None
            mock_job_run_stats.container_id = None
            mock_job_run_stats.flow_id = None
            mock_job_run_stats.flow_name = None
            mock_job_run_stats.user_id = None
            mock_job_run_stats.account_id = None
            mock_job_run_stats.user_entitlements = None
            mock_job_run_stats.report_status = None
            mock_job_run_stats.report_generation_started_at = None
            mock_job_run_stats.report_generation_completed_at = None

            store._job_stats_dal.list_job_runs.return_value = [mock_job_run_stats]

            # Call list_job_runs
            result = store.list_job_runs(job_id=test_job_id, limit=10)

            # Verify result
            assert len(result) == 1
            assert result[0].job_id == test_job_id
            store._job_stats_dal.list_job_runs.assert_called_once_with(
                job_id=test_job_id, job_ids=None, status=None, limit=10
            )


class TestPostgresJobStatsStoreInjectedModel:
    """
    Tests for PostgresJobStatsStore with injected model classes and session factory.

    Verifies that when a caller provides their own model classes and session factory,
    the store uses them exclusively — the default OSS models are never instantiated.
    """

    @pytest.fixture
    def mock_injected_job_stats_model(self):
        """Mock SQLModel class simulating an injected job stats model."""
        model = Mock()
        model.__name__ = "InjectedJobStatsModel"
        return model

    @pytest.fixture
    def mock_injected_node_stats_model(self):
        """Mock SQLModel class simulating an injected node stats model."""
        model = Mock()
        model.__name__ = "InjectedNodeStatsModel"
        return model

    @pytest.fixture
    def mock_session_factory(self):
        """Mock session factory."""
        return Mock()

    @pytest.fixture
    def sample_job_stats(self):
        return JobStats(
            job_id="12345678-1234-1234-1234-123456789012",
            job_run_id="87654321-4321-4321-4321-210987654321",
            status=ExecutionStatus.RUNNING,
            message="Test job",
            start_time=1704067200,
            end_time=0,
            duration=0,
            total_docs=100,
            processed_docs=50,
            completed_docs=45,
            failed_docs=5,
            skipped_docs=0,
        )

    @pytest.fixture
    def sample_node_stats(self):
        return NodeStats(
            id="abcdef12-3456-7890-abcd-ef1234567890",
            name="Test Node",
            node_status=ExecutionStatus.COMPLETED,
            start_time=1704067200,
            end_time=1704067260,
            time_taken=60,
            total_docs=["doc1"],
            docs_completed=["doc1"],
            failed_docs=[],
            skipped_docs=[],
            batch_id=None,
        )

    @patch("docpipe.core.job_management.adapters.stores.postgres.postgres_job_stats_store.JobStatsDAL")
    @patch("docpipe.core.job_management.adapters.stores.postgres.postgres_job_stats_store.NodeStatsDAL")
    def test_injected_session_factory_skips_engine_creation(
        self,
        mock_node_dal_class,
        mock_job_dal_class,
        mock_injected_job_stats_model,
        mock_injected_node_stats_model,
        mock_session_factory,
    ):
        """When session_factory is injected, no engine is created and DALs receive injected models."""
        from docpipe.core.job_management.adapters.stores.postgres import PostgresJobStatsStore

        store = PostgresJobStatsStore(
            job_stats_model=mock_injected_job_stats_model,
            node_stats_model=mock_injected_node_stats_model,
            session_factory=mock_session_factory,
        )

        # Engine must not be created
        assert store._engine is None

        # DALs must be initialised with the injected session factory and model classes
        mock_job_dal_class.assert_called_once_with(
            session_factory=mock_session_factory,
            model=mock_injected_job_stats_model,
        )
        mock_node_dal_class.assert_called_once_with(
            session_factory=mock_session_factory,
            model=mock_injected_node_stats_model,
        )

    @patch("docpipe.core.job_management.adapters.stores.postgres.postgres_job_stats_store.JobStatsDAL")
    @patch("docpipe.core.job_management.adapters.stores.postgres.postgres_job_stats_store.NodeStatsDAL")
    def test_store_job_stats_uses_injected_model(
        self,
        mock_node_dal_class,
        mock_job_dal_class,
        mock_injected_job_stats_model,
        mock_injected_node_stats_model,
        mock_session_factory,
        sample_job_stats,
    ):
        """store_job_stats instantiates the injected model class, not the OSS default."""
        from docpipe.core.job_management.adapters.stores.postgres import PostgresJobStatsStore

        store = PostgresJobStatsStore(
            job_stats_model=mock_injected_job_stats_model,
            node_stats_model=mock_injected_node_stats_model,
            session_factory=mock_session_factory,
        )

        store.store_job_stats(sample_job_stats)

        # The injected model class must have been called (instantiated) by the mapper
        mock_injected_job_stats_model.assert_called_once()
        # The OSS NodeStatsModel must not have been instantiated
        mock_injected_node_stats_model.assert_not_called()

    @patch("docpipe.core.job_management.adapters.stores.postgres.postgres_job_stats_store.JobStatsDAL")
    @patch("docpipe.core.job_management.adapters.stores.postgres.postgres_job_stats_store.NodeStatsDAL")
    def test_store_node_stats_uses_injected_model(
        self,
        mock_node_dal_class,
        mock_job_dal_class,
        mock_injected_job_stats_model,
        mock_injected_node_stats_model,
        mock_session_factory,
        sample_node_stats,
    ):
        """store_node_stats instantiates the injected model class, not the OSS default."""
        from docpipe.core.job_management.adapters.stores.postgres import PostgresJobStatsStore

        store = PostgresJobStatsStore(
            job_stats_model=mock_injected_job_stats_model,
            node_stats_model=mock_injected_node_stats_model,
            session_factory=mock_session_factory,
        )

        store.store_node_stats(job_run_id="test-run-456", node_stats=sample_node_stats)

        # The injected node model class must have been called (instantiated) by the mapper
        mock_injected_node_stats_model.assert_called_once()
        # The OSS JobStatsModel must not have been instantiated
        mock_injected_job_stats_model.assert_not_called()

    @patch("docpipe.core.job_management.adapters.stores.postgres.postgres_job_stats_store.JobStatsDAL")
    @patch("docpipe.core.job_management.adapters.stores.postgres.postgres_job_stats_store.NodeStatsDAL")
    def test_bulk_store_node_stats_uses_injected_model(
        self,
        mock_node_dal_class,
        mock_job_dal_class,
        mock_injected_job_stats_model,
        mock_injected_node_stats_model,
        mock_session_factory,
        sample_node_stats,
    ):
        """bulk_store_node_stats instantiates the injected model class for every record."""
        from docpipe.core.job_management.adapters.stores.postgres import PostgresJobStatsStore

        store = PostgresJobStatsStore(
            job_stats_model=mock_injected_job_stats_model,
            node_stats_model=mock_injected_node_stats_model,
            session_factory=mock_session_factory,
        )

        store.bulk_store_node_stats(job_run_id="test-run-456", node_stats_list=[sample_node_stats, sample_node_stats])

        # Called once per record
        assert mock_injected_node_stats_model.call_count == 2
        mock_injected_job_stats_model.assert_not_called()


class TestGetFailedDocsForBatch:
    """Tests for PostgresJobStatsStore.get_failed_docs_for_batch."""

    def test_returns_failed_doc_ids(self):
        """Collects failed_docs from each db model returned by the DAL."""
        from unittest.mock import Mock, patch

        from docpipe.core.job_management.adapters.stores.postgres import PostgresJobStatsStore

        with patch.object(PostgresJobStatsStore, "__init__", lambda x: None):
            store = PostgresJobStatsStore()
            store._node_stats_dal = Mock()

            m1 = Mock()
            m1.failed_docs = ["doc-a", "doc-b"]
            m2 = Mock()
            m2.failed_docs = ["doc-c"]
            store._node_stats_dal.get_failed_docs_for_batch.return_value = [m1, m2]

            result = store.get_failed_docs_for_batch(job_run_id="run-1", batch_id="batch-1")

            assert sorted(result) == ["doc-a", "doc-b", "doc-c"]
            store._node_stats_dal.get_failed_docs_for_batch.assert_called_once_with(
                job_run_id="run-1", batch_id="batch-1"
            )

    def test_returns_empty_when_no_failed_docs(self):
        """Returns empty list when db models have empty failed_docs."""
        from unittest.mock import Mock, patch

        from docpipe.core.job_management.adapters.stores.postgres import PostgresJobStatsStore

        with patch.object(PostgresJobStatsStore, "__init__", lambda x: None):
            store = PostgresJobStatsStore()
            store._node_stats_dal = Mock()

            m = Mock()
            m.failed_docs = []
            store._node_stats_dal.get_failed_docs_for_batch.return_value = [m]

            result = store.get_failed_docs_for_batch(job_run_id="run-2", batch_id="batch-2")

            assert result == []

    def test_returns_empty_when_dal_returns_nothing(self):
        """Returns empty list when the DAL returns no rows."""
        from unittest.mock import Mock, patch

        from docpipe.core.job_management.adapters.stores.postgres import PostgresJobStatsStore

        with patch.object(PostgresJobStatsStore, "__init__", lambda x: None):
            store = PostgresJobStatsStore()
            store._node_stats_dal = Mock()
            store._node_stats_dal.get_failed_docs_for_batch.return_value = []

            result = store.get_failed_docs_for_batch(job_run_id="run-3", batch_id="batch-3")

            assert result == []

    def test_raises_on_dal_error(self):
        """Raises JobStatsStoreReadException when the DAL raises."""
        from unittest.mock import Mock, patch

        import pytest

        from docpipe.core.job_management.adapters.stores.postgres import PostgresJobStatsStore
        from docpipe.exceptions.docpipe_exceptions import JobStatsStoreReadException

        with patch.object(PostgresJobStatsStore, "__init__", lambda x: None):
            store = PostgresJobStatsStore()
            store._node_stats_dal = Mock()
            store._node_stats_dal.get_failed_docs_for_batch.side_effect = RuntimeError("db down")

            with pytest.raises(JobStatsStoreReadException):
                store.get_failed_docs_for_batch(job_run_id="run-4", batch_id="batch-4")


class TestStoreMethodErrorPaths:
    """Tests for error and empty-result paths across all PostgresJobStatsStore methods."""

    def _store(self):
        """Return a store with __init__ bypassed and DALs mocked."""
        from docpipe.core.job_management.adapters.stores.postgres import PostgresJobStatsStore

        with patch.object(PostgresJobStatsStore, "__init__", lambda x: None):
            store = PostgresJobStatsStore()
            store._job_stats_dal = Mock()
            store._node_stats_dal = Mock()
            store._job_stats_model_cls = None
            store._node_stats_model_cls = None
        return store

    # ── store_job_stats error path ────────────────────────────────────────────

    def test_store_job_stats_raises_on_error(self):
        from docpipe.exceptions.docpipe_exceptions import JobStatsStoreWriteException

        store = self._store()
        store._job_stats_dal.upsert.side_effect = RuntimeError("db error")

        with pytest.raises(JobStatsStoreWriteException):
            store.store_job_stats(Mock(job_run_id="r1"))

    # ── get_job_stats error paths ─────────────────────────────────────────────

    def test_get_job_stats_returns_none_when_not_found(self):
        store = self._store()
        store._job_stats_dal.get_by_job_run_id.return_value = None

        result = store.get_job_stats("r1")

        assert result is None

    def test_get_job_stats_raises_on_error(self):
        from docpipe.exceptions.docpipe_exceptions import JobStatsStoreReadException

        store = self._store()
        store._job_stats_dal.get_by_job_run_id.side_effect = RuntimeError("db error")

        with pytest.raises(JobStatsStoreReadException):
            store.get_job_stats("r1")

    # ── store_node_stats error path ───────────────────────────────────────────

    def test_store_node_stats_raises_on_error(self):
        from docpipe.exceptions.docpipe_exceptions import JobStatsStoreWriteException

        store = self._store()
        store._node_stats_dal.upsert.side_effect = RuntimeError("db error")

        with pytest.raises(JobStatsStoreWriteException):
            store.store_node_stats(job_run_id="r1", node_stats=Mock(id="n1", batch_id=None))

    # ── get_node_stats ────────────────────────────────────────────────────────

    def test_get_node_stats_raises_on_error(self):
        from docpipe.exceptions.docpipe_exceptions import JobStatsStoreReadException

        store = self._store()
        store._node_stats_dal.get_all_node_stats.side_effect = RuntimeError("db error")

        with pytest.raises(JobStatsStoreReadException):
            store.get_node_stats(job_run_id="r1")

    # ── get_batch_node_stats ──────────────────────────────────────────────────

    def test_get_batch_node_stats_returns_empty_for_no_records(self):
        """Returns empty dict when there are no batch records."""
        store = self._store()
        store._node_stats_dal.get_batch_node_stats.return_value = []

        result = store.get_batch_node_stats(job_run_id="r1")

        assert result == {}

    def test_get_batch_node_stats_raises_on_error(self):
        from docpipe.exceptions.docpipe_exceptions import JobStatsStoreReadException

        store = self._store()
        store._node_stats_dal.get_batch_node_stats.side_effect = RuntimeError("db error")

        with pytest.raises(JobStatsStoreReadException):
            store.get_batch_node_stats(job_run_id="r1")

    # ── bulk_store_node_stats ─────────────────────────────────────────────────

    def test_bulk_store_node_stats_empty_list_returns_immediately(self):
        store = self._store()
        store.bulk_store_node_stats(job_run_id="r1", node_stats_list=[])
        store._node_stats_dal.bulk_insert.assert_not_called()

    def test_bulk_store_node_stats_raises_on_error(self):
        from docpipe.exceptions.docpipe_exceptions import JobStatsStoreWriteException

        store = self._store()
        store._node_stats_dal.bulk_insert.side_effect = RuntimeError("db error")

        with pytest.raises(JobStatsStoreWriteException):
            store.bulk_store_node_stats(job_run_id="r1", node_stats_list=[Mock(id="n1", batch_id=None)])

    # ── atomic_increment_fields ───────────────────────────────────────────────

    def test_atomic_increment_fields_delegates_to_dal(self):
        store = self._store()
        store.atomic_increment_fields("r1", increments={"processed_docs": 1})
        store._job_stats_dal.atomic_increment_fields.assert_called_once()

    def test_atomic_increment_fields_raises_on_error(self):
        from docpipe.exceptions.docpipe_exceptions import JobStatsStoreWriteException

        store = self._store()
        store._job_stats_dal.atomic_increment_fields.side_effect = RuntimeError("db error")

        with pytest.raises(JobStatsStoreWriteException):
            store.atomic_increment_fields("r1", increments={})

    # ── get_node_stats_by_batch_and_node ──────────────────────────────────────

    def test_get_node_stats_by_batch_and_node_returns_none_when_not_found(self):
        store = self._store()
        store._node_stats_dal.get_node_stats_by_run_batch.return_value = None

        result = store.get_node_stats_by_batch_and_node("r1", "n1")

        assert result is None

    def test_get_node_stats_by_batch_and_node_raises_on_error(self):
        from docpipe.exceptions.docpipe_exceptions import JobStatsStoreReadException

        store = self._store()
        store._node_stats_dal.get_node_stats_by_run_batch.side_effect = RuntimeError("err")

        with pytest.raises(JobStatsStoreReadException):
            store.get_node_stats_by_batch_and_node("r1", "n1")

    # ── delete_job_stats ──────────────────────────────────────────────────────

    def test_delete_job_stats_raises_when_not_found(self):
        from docpipe.exceptions.docpipe_exceptions import JobStatsStoreDeleteException

        store = self._store()
        store._job_stats_dal.delete_job_stats.return_value = 0

        with pytest.raises(JobStatsStoreDeleteException):
            store.delete_job_stats("r1")

    def test_delete_job_stats_raises_on_error(self):
        from docpipe.exceptions.docpipe_exceptions import JobStatsStoreDeleteException

        store = self._store()
        store._job_stats_dal.delete_job_stats.side_effect = RuntimeError("db error")

        with pytest.raises(JobStatsStoreDeleteException):
            store.delete_job_stats("r1")

    # ── list_job_runs ─────────────────────────────────────────────────────────

    def test_list_job_runs_raises_on_error(self):
        from docpipe.exceptions.docpipe_exceptions import JobStatsStoreReadException

        store = self._store()
        store._job_stats_dal.list_job_runs.side_effect = RuntimeError("db error")

        with pytest.raises(JobStatsStoreReadException):
            store.list_job_runs()

    def test_count_job_runs_returns_dal_count(self):
        store = self._store()
        store._job_stats_dal.count_job_runs.return_value = 42

        result = store.count_job_runs(job_id="job-1", job_ids=["job-1"], status=ExecutionStatus.COMPLETED)

        assert result == 42
        store._job_stats_dal.count_job_runs.assert_called_once_with(
            job_id="job-1",
            job_ids=["job-1"],
            status=ExecutionStatus.COMPLETED.value,
        )

    def test_count_job_runs_raises_on_error(self):
        from docpipe.exceptions.docpipe_exceptions import JobStatsStoreReadException

        store = self._store()
        store._job_stats_dal.count_job_runs.side_effect = RuntimeError("db error")

        with pytest.raises(JobStatsStoreReadException):
            store.count_job_runs()

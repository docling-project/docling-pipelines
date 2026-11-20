# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Unit tests for sanitize_exception and its catch sites."""

import socket
import ssl
from unittest.mock import MagicMock, patch

import pytest
import requests
from pydantic import BaseModel, ValidationError

from docpipe.core.operators.ingest.adapters.outbound.sources.s3.config import S3SourceConfig
from docpipe.core.operators.ingest.ingest_source import IngestSourceOperator
from docpipe.exceptions.docpipe_exceptions import DocpipeException
from docpipe.utils.infrastructure.exception_sanitizer import (
    CATEGORY_CLIENT,
    CATEGORY_CONNECTION,
    CATEGORY_DATABASE,
    CATEGORY_HTTP,
    CATEGORY_TIMEOUT,
    CATEGORY_TLS,
    CATEGORY_VALIDATION,
    sanitize_exception,
)

CANARY = "CANARY-7c1e9b52-secret"
KEY = "ingest_source.provider_config"


class _Model(BaseModel):
    password: str
    port: int


def _validation_error(*, value: object) -> ValidationError:
    with pytest.raises(ValidationError) as info:
        _Model(password="x", port=value)  # type: ignore[arg-type]
    return info.value


class TestValidationError:
    def test_input_value_is_not_rendered(self):
        exc = _validation_error(value=CANARY)

        assert CANARY in str(exc)  # Pydantic echoes the input; this is the leak being closed.
        text = sanitize_exception(exc=exc, config_key=KEY)

        assert CANARY not in text
        assert "input_value" not in text
        assert "errors.pydantic.dev" not in text
        assert f"{KEY}.port" in text
        assert CATEGORY_VALIDATION in text

    def test_s3_endpoint_url_without_scheme(self):
        with pytest.raises(ValidationError) as info:
            S3SourceConfig(
                access_key="ak",
                secret_key=CANARY,
                bucket="bucket",
                endpoint_url=f"{CANARY}.example.com",
            )

        assert CANARY in str(info.value)
        text = sanitize_exception(exc=info.value, config_key=KEY)

        assert CANARY not in text
        assert f"{KEY}.endpoint_url" in text
        assert "endpoint_url must start with http:// or https://" in text

    def test_wrapped_validation_error_is_rendered_from_the_chain(self):
        inner = _validation_error(value=CANARY)
        try:
            raise ValueError(f"wrapper: {inner}") from inner
        except ValueError as wrapper:
            text = sanitize_exception(exc=wrapper, config_key=KEY)

        assert CANARY not in text
        assert CATEGORY_VALIDATION in text
        assert text.count(KEY + ": ") == 1


class TestWrapperMessageIsKept:
    """A wrapper with its own actionable text keeps it; only the wrapped third-party text is replaced."""

    @staticmethod
    def _docpipe_exception(*, message: str, cause: BaseException) -> DocpipeException:
        try:
            raise DocpipeException(message=message, status_code=400) from cause
        except DocpipeException as wrapper:
            return wrapper

    def test_duckdb_wrapper_keeps_the_hint(self):
        import duckdb

        with pytest.raises(duckdb.Error) as info:
            duckdb.connect().execute(f"select '{CANARY}' > 1")
        hint = "Filter condition is invalid due to mismatched data types. Please review the filter expression."
        wrapper = self._docpipe_exception(message=f"{hint} {info.value}", cause=info.value)

        text = sanitize_exception(exc=wrapper, config_key="sql_filter_node")

        assert hint in text
        assert CANARY not in text
        assert str(info.value) not in text
        assert text.endswith(CATEGORY_DATABASE)

    def test_fixed_text_wrapper_around_a_cause_is_unchanged(self):
        cause = requests.exceptions.ConnectionError(f"https://u:{CANARY}@host")
        wrapper = self._docpipe_exception(message="Could not reach the embeddings service.", cause=cause)

        assert sanitize_exception(exc=wrapper, config_key=KEY) == f"{KEY}: Could not reach the embeddings service."

    def test_wrapper_around_a_validation_error_keeps_hint_and_drops_input(self):
        inner = _validation_error(value=CANARY)
        wrapper = self._docpipe_exception(message=f"Invalid operator configuration. {inner}", cause=inner)

        text = sanitize_exception(exc=wrapper, config_key=KEY)

        assert text.startswith(f"{KEY}: Invalid operator configuration. {CATEGORY_VALIDATION} (")
        assert CANARY not in text
        assert f"{KEY}.port" in text

    def test_wrapper_around_a_requests_error_keeps_hint(self):
        cause = requests.exceptions.ConnectionError(f"https://u:{CANARY}@host")
        wrapper = self._docpipe_exception(message=f"Embedding call failed: {cause}", cause=cause)

        assert sanitize_exception(exc=wrapper, config_key=KEY) == f"{KEY}: Embedding call failed: {CATEGORY_CONNECTION}"

    def test_message_equal_to_the_cause_text_becomes_the_category(self):
        cause = requests.exceptions.ConnectionError(f"https://u:{CANARY}@host")
        wrapper = self._docpipe_exception(message=str(cause), cause=cause)

        assert sanitize_exception(exc=wrapper, config_key=KEY) == f"{KEY}: {CATEGORY_CONNECTION}"

    def test_truncated_copy_of_the_cause_falls_back_to_the_category(self):
        cause = requests.exceptions.ConnectionError(f"https://user:{CANARY}@host/path")
        wrapper = self._docpipe_exception(message=f"Failed: {str(cause)[:-8]}", cause=cause)

        text = sanitize_exception(exc=wrapper, config_key=KEY)

        assert CANARY not in text
        assert text == f"{KEY}: {CATEGORY_CONNECTION}"

    def test_repr_of_the_cause_is_redacted_in_place(self):
        cause = requests.exceptions.ConnectionError(f"https://user:{CANARY}@host/path")
        wrapper = self._docpipe_exception(message=f"Failed: {cause!r}", cause=cause)

        text = sanitize_exception(exc=wrapper, config_key=KEY)

        assert CANARY not in text
        assert text.startswith(f"{KEY}: Failed: ")

    def test_escaped_copy_of_the_cause_falls_back_to_the_category(self):
        cause = requests.exceptions.ConnectionError(f"""it's "quoted" {CANARY} @host""")
        wrapper = self._docpipe_exception(message=f"Failed: {cause!r}", cause=cause)
        assert str(cause) not in str(wrapper)  # repr escaped the quote, so verbatim replacement cannot work

        text = sanitize_exception(exc=wrapper, config_key=KEY)

        assert CANARY not in text
        assert text == f"{KEY}: {CATEGORY_CONNECTION}"

    def test_wrapper_without_a_secret_in_the_cause_text(self):
        cause = requests.exceptions.ConnectionError("boom")
        wrapper = self._docpipe_exception(message="Step failed.", cause=cause)

        assert sanitize_exception(exc=wrapper, config_key=KEY) == f"{KEY}: Step failed."

    def test_node_failure_message_keeps_the_hint(self):
        from docpipe.core.job_management.adapters.services.job_tracker_service import JobTrackerService

        cause = requests.exceptions.ConnectionError(f"https://u:{CANARY}@h")
        wrapper = self._docpipe_exception(message=f"Search backend unreachable: {cause}", cause=cause)
        service = JobTrackerService.__new__(JobTrackerService)
        store = MagicMock()
        store.get_node_stats_by_batch_and_node.return_value = None
        service.job_stats_store = store

        service.fail_node_execution(job_run_id="r", node_id="n", node_name="vectordb_node", exception=wrapper)

        stored = str(store.mock_calls)
        assert "Search backend unreachable" in stored
        assert CANARY not in stored


class TestCategories:
    def test_http_connection_error_with_canary(self):
        exc = requests.exceptions.ConnectionError(f"HTTPSConnectionPool(host='https://user:{CANARY}@h', port=443)")

        text = sanitize_exception(exc=exc, config_key=KEY)

        assert text == f"{KEY}: {CATEGORY_CONNECTION}"
        assert CANARY not in text

    def test_timeout(self):
        text = sanitize_exception(exc=requests.exceptions.ReadTimeout(CANARY), config_key=KEY)

        assert text == f"{KEY}: {CATEGORY_TIMEOUT}"

    def test_tls(self):
        text = sanitize_exception(exc=ssl.SSLError(CANARY), config_key=KEY)

        assert text == f"{KEY}: {CATEGORY_TLS}"

    def test_generic_http_error(self):
        text = sanitize_exception(
            exc=requests.exceptions.HTTPError(f"401 for url: https://h/?token={CANARY}"), config_key=KEY
        )

        assert text == f"{KEY}: {CATEGORY_HTTP}"

    def test_dns_failure(self):
        text = sanitize_exception(exc=socket.gaierror(f"{CANARY}.internal"), config_key=KEY)

        assert text == f"{KEY}: {CATEGORY_CONNECTION}"

    def test_botocore_client_error(self):
        from botocore.exceptions import EndpointConnectionError

        text = sanitize_exception(exc=EndpointConnectionError(endpoint_url=f"https://{CANARY}.example"), config_key=KEY)

        assert CANARY not in text
        assert text.startswith(f"{KEY}: ")

    def test_database_error(self):
        import sqlalchemy.exc

        exc = sqlalchemy.exc.OperationalError("SELECT 1", {}, Exception(f"postgresql://u:{CANARY}@h/db"))

        text = sanitize_exception(exc=exc, config_key=KEY)

        assert CANARY not in text
        assert text == f"{KEY}: database error"

    def test_wrapper_hides_a_canary_cause(self):
        try:
            try:
                raise requests.exceptions.ConnectionError(f"https://u:{CANARY}@host")
            except requests.exceptions.ConnectionError as inner:
                msg = f"Failed to fetch documents: {inner!s}"
                raise ValueError(msg) from inner
        except ValueError as wrapper:
            text = sanitize_exception(exc=wrapper, config_key=KEY)

        assert CANARY not in text
        assert text == f"{KEY}: Failed to fetch documents: {CATEGORY_CONNECTION}"

    def test_unknown_exception_keeps_its_message(self):
        assert sanitize_exception(exc=ValueError("bad range"), config_key=KEY) == "bad range"

    def test_empty_message_falls_back_to_class_name(self):
        assert sanitize_exception(exc=RuntimeError(), config_key=KEY) == "RuntimeError"

    def test_cyclic_chain_terminates(self):
        a = RuntimeError("a")
        b = RuntimeError("b")
        a.__cause__ = b
        b.__cause__ = a

        assert sanitize_exception(exc=a, config_key=KEY) == "a"


class TestIngestCatchSites:
    @staticmethod
    def _s3_operator() -> IngestSourceOperator:
        return IngestSourceOperator(
            {
                "provider": "s3",
                "provider_config": {
                    "access_key": "ak",
                    "secret_key": CANARY,
                    "bucket": "b",
                    "endpoint_url": f"{CANARY}.example.com",
                },
            }
        )

    def test_validate_does_not_echo_endpoint_url(self):
        operator = self._s3_operator()
        errors: list[str] = []

        operator.validate(errors=errors, warnings=[], available_features=[])

        assert errors
        assert CANARY not in " ".join(errors)
        assert "endpoint_url" in errors[0]
        assert CATEGORY_VALIDATION in errors[0]

    def test_process_documents_failure_reason_and_log(self, caplog):
        operator = self._s3_operator()
        metadata = operator.create_base_metadata(total_docs_count=0)

        with caplog.at_level("DEBUG"):
            operator.process_documents(metadata)

        assert metadata["failed_docs_count"] == 1
        assert CANARY not in str(metadata["failed_docs"])
        assert CANARY not in caplog.text

    def test_loader_connection_error_with_canary(self, caplog):
        operator = IngestSourceOperator({"provider": "custom", "provider_config": {"loader_class_path": "pkg.Loader"}})
        metadata = operator.create_base_metadata(total_docs_count=0)
        error = requests.exceptions.ConnectionError(f"https://user:{CANARY}@host")

        with patch.object(operator, "_get_loader", side_effect=error), caplog.at_level("DEBUG"):
            operator.process_documents(metadata)

        assert CANARY not in str(metadata["failed_docs"])
        assert CANARY not in caplog.text
        assert CATEGORY_CONNECTION in metadata["failed_docs"][0]["reason"]

    def test_process_document_failure_reason(self, caplog):
        operator = IngestSourceOperator({"provider": "custom", "provider_config": {"loader_class_path": "pkg.Loader"}})
        metadata = operator.create_base_metadata(total_docs_count=1)
        doc = MagicMock()
        doc.metadata.get.side_effect = [requests.exceptions.ConnectionError(CANARY), "file.txt"]

        with caplog.at_level("DEBUG"):
            assert operator.process_document(doc, 0, metadata) is None

        assert CANARY not in str(metadata["failed_docs"])
        assert CANARY not in caplog.text


class TestStorageCatchSites:
    def test_s3_destination_write_error(self, caplog):
        from docpipe.core.operators.storage.adapters.outbound.destinations.s3.adapter import S3DestinationAdapter
        from docpipe.core.operators.storage.adapters.outbound.destinations.s3.config import S3DestinationConfig

        adapter = S3DestinationAdapter()
        config = S3DestinationConfig(access_key="ak", secret_key=CANARY, bucket="b")
        error = requests.exceptions.ConnectionError(f"https://ak:{CANARY}@host")

        with (
            patch.object(adapter, "_create_s3_client", side_effect=error),
            caplog.at_level("DEBUG"),
        ):
            result = adapter.write_document(content=b"x", destination_path="k", config=config)

        assert result.success is False
        assert CANARY not in (result.error_message or "")
        assert CANARY not in caplog.text

    def test_filesystem_destination_write_error(self):
        from docpipe.core.operators.storage.adapters.outbound.destinations.filesystem.adapter import (
            FilesystemDestinationAdapter,
        )

        adapter = FilesystemDestinationAdapter()
        with patch("pathlib.Path.write_bytes", side_effect=requests.exceptions.ConnectionError(CANARY)):
            result = adapter.write_document(content=b"x", destination_path="/tmp/docpipe-a2-test.bin")

        assert result.success is False
        assert CANARY not in (result.error_message or "")


class TestVectorDBCatchSites:
    @staticmethod
    def _config() -> dict:
        return {
            "provider": "opensearch",
            "provider_config": {"host": "http://localhost:9200", "index_name": "idx"},
            "feature_mappings": [],
        }

    def test_init_failure_message(self):
        from docpipe.core.operators.vectordb.vectordb_operator import VectorDBOperator
        from docpipe.exceptions.docpipe_exceptions import DocpipeException

        error = requests.exceptions.ConnectionError(f"https://admin:{CANARY}@host:9200")
        with (
            patch(
                "docpipe.core.operators.vectordb.vectordb_operator.VectorStoreFactory.create",
                side_effect=error,
            ),
            pytest.raises(DocpipeException) as info,
        ):
            VectorDBOperator(config=self._config())

        assert CANARY not in str(info.value)
        assert CATEGORY_CONNECTION in str(info.value)

    def test_indexing_failure_reason_and_log(self, caplog):
        from docpipe.core.operators.vectordb.vectordb_operator import VectorDBOperator

        adapter = MagicMock()
        adapter.create_index.side_effect = requests.exceptions.ConnectionError(f"https://admin:{CANARY}@host")
        adapter.index_exists.return_value = False
        with patch(
            "docpipe.core.operators.vectordb.vectordb_operator.VectorStoreFactory.create",
            return_value=adapter,
        ):
            operator = VectorDBOperator(config=self._config())

        metadata = operator.create_base_metadata(total_docs_count=1)
        with caplog.at_level("DEBUG"):
            ready = operator._ensure_index_ready(
                dimension_mapping={},
                unique_doc_ids={"d1"},
                doc_hash_to_id={"d1": "d1"},
                doc_hash_to_name={"d1": "doc"},
                metadata=metadata,
            )

        assert ready is False
        assert CANARY not in caplog.text
        assert CANARY not in str(metadata)
        assert CATEGORY_CONNECTION in str(metadata)


class TestMessageWriters:
    def test_fail_node_execution_stores_sanitized_error(self):
        from docpipe.core.job_management.adapters.services.job_tracker_service import JobTrackerService

        service = JobTrackerService.__new__(JobTrackerService)
        store = MagicMock()
        store.get_node_stats_by_batch_and_node.return_value = None
        service.job_stats_store = store

        service.fail_node_execution(
            job_run_id="r",
            node_id="n",
            node_name="vectordb_node",
            exception=requests.exceptions.ConnectionError(f"https://u:{CANARY}@h"),
        )

        stored = str(store.mock_calls)
        assert CANARY not in stored
        assert CATEGORY_CONNECTION in stored

    def test_orchestrator_job_message(self):
        from docpipe.core.orchestration.abstract_orchestrator import AbstractOrchestrator

        orchestrator = MagicMock()
        orchestrator.job_status = None
        orchestrator.flow_id = "f"
        global_config: dict = {}
        op_def = {"id": "n1", "name": "vectordb_node", "operator": "vectordb"}
        error = requests.exceptions.ConnectionError(f"https://u:{CANARY}@h")

        AbstractOrchestrator._handle_node_failure(orchestrator, e=error, op_def=op_def, global_config=global_config)

        assert CANARY not in str(orchestrator.message)
        assert CATEGORY_CONNECTION in str(orchestrator.message)


class _OddModuleError(Exception):
    """Exception whose class name alone signals a network failure."""


class TestCategoryFallbacks:
    """Categories derived from the built-in hierarchy, the class name, or the client module."""

    def test_builtin_timeout_subclass(self):
        """A TimeoutError subclass is a timeout even outside HTTP libraries."""

        class _SlowError(TimeoutError):
            pass

        assert sanitize_exception(exc=_SlowError(CANARY), config_key=KEY) == f"{KEY}: {CATEGORY_TIMEOUT}"

    def test_builtin_connection_error_subclass(self):
        """A ConnectionError subclass such as ConnectionRefusedError is a connection failure."""
        exc = ConnectionRefusedError(f"refused {CANARY}")

        assert sanitize_exception(exc=exc, config_key=KEY) == f"{KEY}: {CATEGORY_CONNECTION}"

    @pytest.mark.parametrize(
        ("class_name", "category"),
        [
            ("CertificateVerifyError", CATEGORY_TLS),
            ("ReadTimeoutish", CATEGORY_TIMEOUT),
            ("ProxyError", CATEGORY_CONNECTION),
            ("NameResolutionFailure", CATEGORY_CONNECTION),
        ],
    )
    def test_class_name_implies_network_category(self, class_name, category):
        """An unrelated exception class is categorised by keywords in its name."""
        exc_type = type(class_name, (_OddModuleError,), {})

        assert sanitize_exception(exc=exc_type(CANARY), config_key=KEY) == f"{KEY}: {category}"

    def test_client_module_exception(self):
        """A botocore error without a network keyword falls into the client category."""
        from botocore.exceptions import NoCredentialsError

        text = sanitize_exception(exc=NoCredentialsError(), config_key=KEY)

        assert text == f"{KEY}: {CATEGORY_CLIENT}"

    def test_wrapper_with_empty_message_falls_back_to_the_category(self):
        """A wrapper that has no text of its own is replaced by the cause category."""
        try:
            raise RuntimeError from requests.exceptions.ConnectionError(f"https://u:{CANARY}@host")
        except RuntimeError as wrapper:
            text = sanitize_exception(exc=wrapper, config_key=KEY)

        assert text == f"{KEY}: {CATEGORY_CONNECTION}"

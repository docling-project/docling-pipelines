"""ACLOperator tests for metadata parsing, adapter setup and per-document failure handling.

A small fake adapter stands in for the provider; it returns prepared ACLResponse objects
and records the ACLRequests the operator builds.
"""

import json
from typing import Any
from unittest.mock import patch

import pyarrow as pa
import pytest

from docpipe.core.constants.constants import DocpipeConstants, Metrics
from docpipe.core.operators.acl.acl_operator import ACLOperator
from docpipe.core.operators.acl.domain.models import ACLRequest, ACLResponse
from docpipe.exceptions.docpipe_exceptions import (
    ConfigurationError,
    DocpipeException,
    FlowExecutionFailedException,
)

_FACTORY = "docpipe.core.operators.acl.acl_operator.ACLAdapterFactory.create_adapter"
_INGEST_METADATA = {
    "provider": "sharepoint",
    "client_id": "client-1",
    "client_secret": "<test-secret>",  # pragma: allowlist secret
    "tenant_id": "tenant-1",
}


class FakeAdapter:
    """Returns prepared responses (or raises) and records the requests it receives."""

    def __init__(self, *, responses: list[ACLResponse] | None = None, error: Exception | None = None) -> None:
        self.responses = responses or []
        self.error = error
        self.requests: list[ACLRequest] = []

    async def extract_acls_batch(self, *, requests: list[ACLRequest]) -> list[ACLResponse]:
        self.requests = requests
        if self.error:
            raise self.error
        return self.responses


def _table(*, ids: list[str], metadata: list[Any] | None = None) -> pa.Table:
    return pa.table(
        {
            "id": ids,
            "path": [f"/docs/{i}.pdf" for i in ids],
            "source_id": [f"https://contoso.sharepoint.com/sites/s/Docs/{i}.pdf" for i in ids],
            DocpipeConstants.METADATA: metadata if metadata is not None else [json.dumps(_INGEST_METADATA)] * len(ids),
        }
    )


def _response(*, users: set[Any], success: bool = True, error: str | None = None) -> ACLResponse:
    return ACLResponse(
        resource_id="r",
        resource_path="r",
        allowed_users=users,
        extraction_success=success,
        extraction_error=error,
    )


class LazyResponse:
    """Provider response that resolves its users on access and fails while doing so."""

    extraction_success = True
    extraction_warnings: tuple[str, ...] = ()

    @property
    def allowed_users(self) -> set[str]:
        raise DocpipeException("group expansion failed for group-1", status_code=502)


def _operator(*, fail_on_error: bool) -> ACLOperator:
    return ACLOperator({"provider_config": {}, "fail_on_error": fail_on_error})


def _run(operator: ACLOperator, table: pa.Table, adapter: FakeAdapter) -> tuple[pa.Table, dict]:
    with patch(_FACTORY, return_value=adapter):
        tables, metadata = operator.transform(table)
    return tables[0], metadata


class TestIngestMetadata:
    """Provider and credentials come from the first row's metadata."""

    def test_metadata_as_dict_is_accepted(self) -> None:
        table = _table(ids=["a"], metadata=[_INGEST_METADATA])

        provider, credentials, params = _operator(fail_on_error=True)._extract_ingest_metadata(table)

        assert provider == "sharepoint"
        assert credentials == {k: v for k, v in _INGEST_METADATA.items() if k != "provider"}
        assert params == {}

    @pytest.mark.parametrize(
        ("metadata", "message"),
        [
            ({**_INGEST_METADATA, "provider": ""}, "Provider not found in metadata"),
            ({"provider": "sharepoint", "client_id": "client-1"}, "Credentials not found in metadata"),
        ],
    )
    def test_incomplete_metadata_is_rejected(self, metadata: dict, message: str) -> None:
        with pytest.raises(FlowExecutionFailedException, match=message):
            _operator(fail_on_error=True).transform(_table(ids=["a"], metadata=[json.dumps(metadata)]))

    def test_invalid_json_is_rejected(self) -> None:
        with pytest.raises(FlowExecutionFailedException, match="Failed to parse metadata JSON"):
            _operator(fail_on_error=True).transform(_table(ids=["a"], metadata=["{not json"]))

    def test_missing_metadata_column_is_rejected(self) -> None:
        table = _table(ids=["a"]).drop_columns([DocpipeConstants.METADATA])

        with pytest.raises(FlowExecutionFailedException, match="Required metadata column missing"):
            _operator(fail_on_error=True)._extract_ingest_metadata(table)

    def test_table_without_rows_has_no_metadata(self) -> None:
        empty = _table(ids=[]).cast(_table(ids=["a"]).schema)

        with pytest.raises(FlowExecutionFailedException, match="No metadata found in input table"):
            _operator(fail_on_error=True)._extract_ingest_metadata(empty)


class TestAdapterInitialisation:
    """Errors from ACLAdapterFactory."""

    def test_value_error_becomes_bad_request(self) -> None:
        with patch(_FACTORY, side_effect=ValueError("Unknown provider: dropbox")):
            with pytest.raises(FlowExecutionFailedException, match="Unknown provider: dropbox") as exc_info:
                _operator(fail_on_error=True).transform(_table(ids=["a"]))

        assert exc_info.value.status_code == 400

    def test_configuration_error_passes_through(self) -> None:
        original = ConfigurationError("SharePoint ACL adapter requires client_id")

        with patch(_FACTORY, side_effect=original):
            with pytest.raises(ConfigurationError) as exc_info:
                _operator(fail_on_error=True).transform(_table(ids=["a"]))

        assert exc_info.value is original

    def test_unexpected_error_is_wrapped(self) -> None:
        with patch(_FACTORY, side_effect=RuntimeError("plugin import failed")):
            with pytest.raises(FlowExecutionFailedException, match=r"Failed to initialize ACL adapter.*plugin import"):
                _operator(fail_on_error=True).transform(_table(ids=["a"]))


class TestPerDocumentHandling:
    """Request building and response processing."""

    def test_invalid_document_metadata_falls_back_to_empty_dict(self) -> None:
        first = json.dumps({**_INGEST_METADATA, "item_id": "item-a"})
        adapter = FakeAdapter(responses=[_response(users={"x@contoso.com"}), _response(users={"y@contoso.com"})])

        output, _ = _run(_operator(fail_on_error=True), _table(ids=["a", "b"], metadata=[first, "{broken"]), adapter)

        assert [r.provider_metadata.get("item_id") for r in adapter.requests] == ["item-a", None]
        assert adapter.requests[1].provider_metadata == {}
        assert output.column("allowed_users").to_pylist() == [["x@contoso.com"], ["y@contoso.com"]]

    def test_batch_failure_raises_when_fail_on_error(self) -> None:
        adapter = FakeAdapter(error=TimeoutError("Graph API timed out"))

        with pytest.raises(FlowExecutionFailedException, match="Batch ACL extraction failed: Graph API timed out"):
            _run(_operator(fail_on_error=True), _table(ids=["a"]), adapter)

    def test_document_without_metadata_gets_empty_provider_metadata(self) -> None:
        adapter = FakeAdapter(responses=[_response(users={"x@contoso.com"}), _response(users={"y@contoso.com"})])

        _run(
            _operator(fail_on_error=True),
            _table(ids=["a", "b"], metadata=[json.dumps(_INGEST_METADATA), None]),
            adapter,
        )

        assert adapter.requests[1].provider_metadata == {}

    def test_all_documents_skipped_gives_empty_output(self) -> None:
        table = _table(ids=["a", "b"]).set_column(2, "source_id", pa.array([None, None], type=pa.string()))
        adapter = FakeAdapter()

        output, metadata = _run(_operator(fail_on_error=False), table, adapter)

        assert adapter.requests == []
        assert output.num_rows == 0
        assert "allowed_users" in output.column_names
        assert metadata[Metrics.External.SKIPPED_DOCS_COUNT] == 2

    def test_unsuccessful_response_raises_when_fail_on_error(self) -> None:
        adapter = FakeAdapter(responses=[_response(users=set(), success=False, error="403 Forbidden")])

        with pytest.raises(FlowExecutionFailedException, match=r"document a \(/docs/a.pdf\): 403 Forbidden"):
            _run(_operator(fail_on_error=True), _table(ids=["a"]), adapter)

    @pytest.mark.parametrize("fail_on_error", [True, False])
    def test_docpipe_error_while_reading_a_response(self, fail_on_error: bool) -> None:
        adapter = FakeAdapter(responses=[LazyResponse(), _response(users={"b@contoso.com"})])  # type: ignore[list-item]
        operator = _operator(fail_on_error=fail_on_error)

        if fail_on_error:
            with pytest.raises(FlowExecutionFailedException, match="document a: group expansion failed") as exc_info:
                _run(operator, _table(ids=["a", "b"]), adapter)
            assert isinstance(exc_info.value.__cause__, DocpipeException)
            return

        output, metadata = _run(operator, _table(ids=["a", "b"]), adapter)
        assert output.column("id").to_pylist() == ["b"]
        assert metadata[Metrics.External.FAILED_DOCS][0]["reason"] == "group expansion failed for group-1"

    def test_unsuccessful_response_without_message_is_recorded(self) -> None:
        adapter = FakeAdapter(responses=[_response(users=set(), success=False), _response(users={"ok@contoso.com"})])

        output, metadata = _run(_operator(fail_on_error=False), _table(ids=["a", "b"]), adapter)

        assert output.column("id").to_pylist() == ["b"]
        assert metadata[Metrics.External.FAILED_DOCS][0]["reason"] == "Unknown error"

    @pytest.mark.parametrize("fail_on_error", [True, False])
    def test_malformed_response_is_handled(self, fail_on_error: bool) -> None:
        # A provider that mixes identity types cannot be sorted into the output column.
        adapter = FakeAdapter(responses=[_response(users={"a@contoso.com", 7}), _response(users={"b@contoso.com"})])
        operator = _operator(fail_on_error=fail_on_error)

        if fail_on_error:
            with pytest.raises(FlowExecutionFailedException, match="ACL extraction failed for document a"):
                _run(operator, _table(ids=["a", "b"]), adapter)
            return

        output, metadata = _run(operator, _table(ids=["a", "b"]), adapter)
        assert output.column("id").to_pylist() == ["b"]
        assert metadata[Metrics.External.FAILED_DOCS_COUNT] == 1
        assert "'<' not supported" in metadata[Metrics.External.FAILED_DOCS][0]["reason"]

    def test_output_column_type_conflict_is_reported(self) -> None:
        # Each document's identities sort fine, but string and integer lists cannot share one column.
        adapter = FakeAdapter(responses=[_response(users={"a@contoso.com"}), _response(users={42})])

        with pytest.raises(FlowExecutionFailedException, match="Failed to create output table with allowed_users"):
            _run(_operator(fail_on_error=False), _table(ids=["a", "b"]), adapter)


class TestValidate:
    """Config validation runs only at execution time."""

    def test_valid_config_has_no_errors(self) -> None:
        errors: list[str] = []
        warnings: list[str] = []

        _operator(fail_on_error=True).validate(errors, warnings, ["id", "path", "source_id", "metadata"])

        assert errors == []

    def test_type_checks_are_skipped_while_validating_a_flow(self) -> None:
        operator = ACLOperator(
            {"provider_config": "not-a-dict", "fail_on_error": "yes", DocpipeConstants.VALIDATING_FLOW: True}
        )
        errors: list[str] = []

        operator.validate(errors, [], ["id", "path", "source_id", "metadata"])

        assert errors == []

"""
Public-API tests for DocpipeFlowManager validation and custom operator registration.

These tests use the real orchestrator, operator factory, custom operator loader and
FlowValidator; flows ingest the customer support fixture files from disk.
"""

import textwrap
from pathlib import Path

import pytest

from docpipe.exceptions.docpipe_exceptions import DocpipeException
from docpipe.lib.docpipe_flow_manager import DocpipeFlowManager
from docpipe.utils.infrastructure.flow_execution_reporter import FlowExecutionReporter

_CUSTOM_OPERATOR_SOURCE = textwrap.dedent(
    '''
    """Custom operator written by a library user."""

    import pyarrow as pa

    from docpipe.core.constants.constants import DocpipeConstants
    from docpipe.core.operators.abstract_operator import AbstractOperator, OperatorCategory


    class LibraryEchoOperator(AbstractOperator):
        """Pass documents through unchanged."""

        short_name: str = "lib_api_echo"
        category: OperatorCategory = OperatorCategory.Functional
        owner: str | None = DocpipeConstants.OWNER_CUSTOM

        def transform(self, table: pa.Table, file_name: str | None = None) -> tuple[list[pa.Table], dict]:
            """Return the input table."""
            return [table], self.create_base_metadata(total_docs_count=table.num_rows)

        @staticmethod
        def get_metadata() -> dict:
            """Return operator metadata."""
            return {"label": "Echo", "description": "Echo operator", "category": OperatorCategory.Functional.value}

        @staticmethod
        def get_required_features() -> list[str]:
            """Require no input features."""
            return []
    '''
)


def _ingest_then(*, operator_type: str, docs_dir: Path, global_config: object = None) -> dict:
    """Build an authoring flow that ingests ``docs_dir`` and feeds ``operator_type``."""
    return {
        "flow_name": "library api flow",
        "flow": [
            {
                "type": "ingest_source",
                "name": "ingest",
                "config": {
                    "provider": "filesystem",
                    "provider_config": {"paths": [str(docs_dir)]},
                    "include_filter": "txt",
                },
            },
            {"type": operator_type, "name": "step", "depends_on": ["ingest"], "config": {}},
        ],
        "global_config": {} if global_config is None else global_config,
    }


@pytest.fixture
def custom_operator_dir(tmp_path):
    """Directory containing one custom operator module, as a user would keep it on disk."""
    ops_dir = tmp_path / "my_operators"
    ops_dir.mkdir()
    (ops_dir / "echo_operator.py").write_text(_CUSTOM_OPERATOR_SOURCE, encoding="utf-8")
    return ops_dir


def test_execution_reporter_is_created_by_default_and_skipped_when_disabled(fixtures_customer_support_dir):
    """enable_execution_reporter=False leaves the console reporter unset."""
    flow = _ingest_then(operator_type="noop", docs_dir=fixtures_customer_support_dir)

    default_manager = DocpipeFlowManager(flow_def=dict(flow), configure_logging=False)
    quiet_manager = DocpipeFlowManager(flow_def=dict(flow), configure_logging=False, enable_execution_reporter=False)

    assert isinstance(default_manager.execution_reporter, FlowExecutionReporter)
    assert quiet_manager.enable_execution_reporter is False
    assert quiet_manager.execution_reporter is None


def test_register_custom_operators_rejects_a_bare_string(fixtures_customer_support_dir):
    """A single package name must be wrapped in a list."""
    manager = DocpipeFlowManager(
        flow_def=_ingest_then(operator_type="noop", docs_dir=fixtures_customer_support_dir), configure_logging=False
    )

    with pytest.raises(DocpipeException, match="package_names must be a list of strings") as exc_info:
        manager.register_custom_operators(package_names="my_company.operators")  # type: ignore[arg-type]

    assert exc_info.value.status_code == 400
    assert manager.custom_operator_packages == []


def test_register_custom_operators_rejects_non_string_entries(fixtures_customer_support_dir, custom_operator_dir):
    """Path objects are not accepted; nothing from the rejected list is registered."""
    manager = DocpipeFlowManager(
        flow_def=_ingest_then(operator_type="noop", docs_dir=fixtures_customer_support_dir), configure_logging=False
    )

    with pytest.raises(DocpipeException, match="All package names must be strings") as exc_info:
        manager.register_custom_operators(package_names=["my_company.operators", custom_operator_dir])  # type: ignore[list-item]

    assert exc_info.value.status_code == 400
    assert manager.custom_operator_packages == []


def test_registered_custom_operator_directory_makes_operator_available_to_validate(
    fixtures_customer_support_dir, custom_operator_dir
):
    """An operator from a registered directory is unknown before registration and valid after it."""
    manager = DocpipeFlowManager(
        flow_def=_ingest_then(operator_type="lib_api_echo", docs_dir=fixtures_customer_support_dir),
        configure_logging=False,
        enable_execution_reporter=False,
    )

    before = manager.validate()
    manager.register_custom_operators(package_names=[str(custom_operator_dir)])
    after = manager.validate()

    assert before["valid"] is False
    assert any("OPERATOR_NOT_AVAILABLE" in error for error in before["errors"])
    assert manager.custom_operator_packages == [str(custom_operator_dir)]
    assert after["valid"] is True
    assert after["errors"] == []


def test_validate_reports_unexpected_validator_error_as_invalid(fixtures_customer_support_dir):
    """A global_config that is not an object breaks the validator; validate() reports it instead of raising."""
    manager = DocpipeFlowManager(
        flow_def=_ingest_then(operator_type="noop", docs_dir=fixtures_customer_support_dir, global_config="fast"),
        configure_logging=False,
        enable_execution_reporter=False,
    )

    result = manager.validate()

    assert result["valid"] is False
    assert result["warnings"] == []
    assert len(result["errors"]) == 1
    assert isinstance(result["errors"][0], str)
    assert result["errors"][0]


def test_validate_requires_flow_definition(fixtures_customer_support_dir):
    """validate() refuses to run once the flow definition has been cleared."""
    manager = DocpipeFlowManager(
        flow_def=_ingest_then(operator_type="noop", docs_dir=fixtures_customer_support_dir), configure_logging=False
    )
    manager.flow_def = None  # type: ignore[assignment]

    with pytest.raises(DocpipeException, match="Flow definition must be initialized before validation") as exc_info:
        manager.validate()

    assert exc_info.value.status_code == 500

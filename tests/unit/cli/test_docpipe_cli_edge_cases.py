"""
Edge-case tests for the docling-pipelines CLI (src/docpipe/cli/docpipe_cli.py).

Covers the paths the main CLI test module leaves out:
- job_id generation rejecting empty flow names
- run_command_line_executor rejecting a compiled flow without a name
- attaching per-operator failure detail from the job stats store to the raised exception
- validate_flow_definition reporting missing files and malformed JSON
- the list-global-config subcommand and the --list-global-config flag

Real flow files, the real argparse parser, the real authoring compiler and the real
orchestrator are used throughout. The only test double is the job stats store read in
TestFailureDetailEnrichment, which stands in for a storage backend that cannot be read
or returns a failed record without an error message.
"""

import json
import logging
import sys

import pytest

from docpipe.cli import docpipe_cli
from docpipe.cli.docpipe_cli import (
    load_flow_definition,
    run_command_line_executor,
    sanitize_flow_name_for_job_id,
    validate_flow_definition,
)
from docpipe.core.constants.constants import DocpipeConstants
from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.core.job_management.adapters.config.job_management_factory import get_default_factory
from docpipe.core.job_management.domain.models.node_stats import NodeStats
from docpipe.exceptions.docpipe_exceptions import (
    FlowExecutionFailedException,
    FlowValidationException,
    JobStatsStoreReadException,
)


@pytest.fixture
def cli_logs(caplog):
    """Capture records of the CLI logger, which may not propagate to the root logger."""
    cli_logger = logging.getLogger(DocpipeConstants.LOGGER_NAME)
    cli_logger.addHandler(caplog.handler)
    try:
        yield caplog
    finally:
        cli_logger.removeHandler(caplog.handler)


@pytest.fixture
def restore_cli_logging(monkeypatch):
    """Undo the handler, level and propagation changes main() makes via setup_logging().

    main() installs a console handler bound to the current sys.stdout. Under capsys that
    stream is closed after the test, so the handler must not outlive it.
    """
    cli_logger = logging.getLogger(DocpipeConstants.LOGGER_NAME)
    handlers, level, propagate = list(cli_logger.handlers), cli_logger.level, cli_logger.propagate
    monkeypatch.setattr(docpipe_cli, "logger", docpipe_cli.logger)
    try:
        yield
    finally:
        cli_logger.handlers[:] = handlers
        cli_logger.setLevel(level)
        cli_logger.propagate = propagate


@pytest.fixture
def cli_env(monkeypatch, tmp_path):
    """Run the executor in tmp_path and restore the env vars it sets."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("test_mode", "True")
    monkeypatch.setenv(DocpipeConstants.DATA_FOLDER, str(tmp_path / "data"))
    # run_command_line_executor sets RUNTIME=local; setting it here lets monkeypatch restore it.
    monkeypatch.setenv("RUNTIME", "local")
    return tmp_path


def _unknown_operator_flow_def() -> dict:
    """Return a compiled flow whose only node uses an operator that does not exist.

    FlowExecutor.execute() rejects it during validation, before any node runs, so the
    only job stats read is the one the CLI makes to enrich the error.
    """
    return {
        "name": "cli-unknown-operator-flow",
        "dag": [
            {
                "id": "node-1",
                "name": "bad_node",
                OperatorConstants.Misc.OPERATOR: "no_such_operator",
                "config": {},
                "input_edges": [],
                "output_edges": [],
            }
        ],
    }


class TestJobIdFlowNameValidation:
    """sanitize_flow_name_for_job_id rejects names that cannot produce a job_id."""

    @pytest.mark.parametrize("flow_name", ["", "   ", "\t\n"])
    def test_rejects_empty_or_whitespace_only_flow_name(self, flow_name):
        with pytest.raises(ValueError, match="flow_name cannot be empty"):
            sanitize_flow_name_for_job_id(flow_name=flow_name)


class TestRunCommandLineExecutorFlowName:
    """run_command_line_executor requires the compiled flow to carry a name."""

    @pytest.mark.parametrize("flow_def", [{"dag": []}, {"name": "", "dag": []}])
    def test_raises_value_error_when_compiled_flow_has_no_name(self, cli_env, flow_def):
        with pytest.raises(ValueError, match="Flow definition must include a 'name' field"):
            run_command_line_executor(flow_def=flow_def)


class TestFailureDetailEnrichment:
    """A failed run re-raises the original exception, enriched with per-node errors when available."""

    def test_operator_error_is_attached_to_the_raised_exception(self, cli_env, fixtures_customer_support_dir):
        """A real operator failure surfaces as node_failures on the flow exception."""
        flow_file = cli_env / "failing_flow.json"
        flow_file.write_text(
            json.dumps(
                {
                    "flow_name": "cli-failing-operator-flow",
                    # Skip pre-flight validation so the negative sleep reaches the operator at runtime.
                    "global_config": {OperatorConstants.Config.DISABLE_VALIDATION: True},
                    "flow": [
                        {
                            "type": OperatorConstants.Operators.INGEST_SOURCE,
                            "name": "ingest",
                            "config": {
                                "provider": "filesystem",
                                "provider_config": {"paths": [str(fixtures_customer_support_dir)]},
                                "include_filter": "txt",
                            },
                        },
                        {
                            "type": OperatorConstants.Operators.NOOP,
                            "name": "broken_noop",
                            "depends_on": ["ingest"],
                            "config": {OperatorConstants.Misc.SLEEP_SEC: -1},
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )
        original_flow_json, flow_def = load_flow_definition(file_path=str(flow_file))

        with pytest.raises(FlowExecutionFailedException) as exc_info:
            run_command_line_executor(flow_def=flow_def, original_flow_json=original_flow_json)

        assert exc_info.value.node_failures == {"broken_noop": "sleep length must be non-negative"}

    def test_failure_before_any_node_ran_adds_no_node_failures(self, cli_env):
        """A flow rejected during validation has no failed node records, so nothing is attached."""
        with pytest.raises(FlowValidationException) as exc_info:
            run_command_line_executor(flow_def=_unknown_operator_flow_def())

        assert not hasattr(exc_info.value, "node_failures")

    def test_failed_node_without_error_message_adds_no_node_failures(self, cli_env, monkeypatch):
        """A failed node record with an empty error string yields no node_failures attribute."""
        store = get_default_factory().create_job_stats_store()
        requested_runs: list[str] = []

        def failed_record_without_error(*, job_run_id: str) -> list[NodeStats]:
            requested_runs.append(job_run_id)
            return [NodeStats(id="node-1", name="bad_node", node_status="Failed", error="")]

        monkeypatch.setattr(store, "get_node_stats", failed_record_without_error)

        with pytest.raises(FlowValidationException) as exc_info:
            run_command_line_executor(flow_def=_unknown_operator_flow_def())

        assert len(requested_runs) == 1
        assert not hasattr(exc_info.value, "node_failures")

    def test_unreadable_job_stats_store_does_not_mask_the_original_error(self, cli_env, monkeypatch):
        """If the job stats store cannot be read, the original exception is still raised unchanged."""
        store = get_default_factory().create_job_stats_store()
        requested_runs: list[str] = []

        def unreadable(*, job_run_id: str) -> list[NodeStats]:
            requested_runs.append(job_run_id)
            raise JobStatsStoreReadException(
                message="job stats store unavailable", job_run_id=job_run_id, operation="get_node_stats"
            )

        monkeypatch.setattr(store, "get_node_stats", unreadable)

        with pytest.raises(FlowValidationException) as exc_info:
            run_command_line_executor(flow_def=_unknown_operator_flow_def())

        assert len(requested_runs) == 1
        assert not hasattr(exc_info.value, "node_failures")


class TestValidateFlowDefinitionFileErrors:
    """validate_flow_definition returns False and explains file-level problems."""

    def test_missing_file_returns_false_and_logs_searched_path(self, tmp_path, cli_logs):
        missing = tmp_path / "does_not_exist.json"

        assert validate_flow_definition(flow_file=str(missing)) is False

        messages = [record.getMessage() for record in cli_logs.records]
        assert "Flow definition file not found" in messages
        assert f"  Searched for: {missing.resolve()}" in messages

    def test_malformed_json_returns_false_and_logs_position(self, tmp_path, cli_logs):
        flow_file = tmp_path / "broken.json"
        flow_file.write_text('{\n  "flow_name": "x",\n  oops\n}', encoding="utf-8")

        assert validate_flow_definition(flow_file=str(flow_file)) is False

        messages = [record.getMessage() for record in cli_logs.records]
        assert "Invalid JSON in flow definition file" in messages
        assert f"  File: {flow_file}" in messages
        assert any(message.startswith("  Line 3, Column 3: ") for message in messages)


@pytest.mark.usefixtures("restore_cli_logging")
class TestListGlobalConfig:
    """The list-global-config subcommand and --list-global-config flag print and return without a flow file."""

    def test_subcommand_filters_by_category(self, monkeypatch, capsys):
        monkeypatch.setattr(
            sys, "argv", ["docling-pipelines", "list-global-config", "--category", "Incremental Processing"]
        )

        docpipe_cli.main()

        out = capsys.readouterr().out
        assert "GLOBAL CONFIGURATION PARAMETERS - CATEGORY: Incremental Processing" in out
        assert "(retain_deleted_docs)" in out
        assert "Total parameters: 3" in out
        assert "(micro_batch_size)" not in out

    def test_subcommand_verbose_shows_parameter_details(self, monkeypatch, capsys):
        monkeypatch.setattr(sys, "argv", ["docling-pipelines", "list-global-config", "-v", "-c", "Execution Control"])

        docpipe_cli.main()

        out = capsys.readouterr().out
        assert "CATEGORY: Execution Control" in out
        assert "Parameter: disable_validation" in out
        assert "Disables flow validation before execution." in out
        assert "Parameter: micro_batch_size" not in out

    def test_flag_prints_summary_of_all_categories(self, monkeypatch, capsys):
        monkeypatch.setattr(sys, "argv", ["docling-pipelines", "--list-global-config"])

        docpipe_cli.main()

        out = capsys.readouterr().out
        assert "GLOBAL CONFIGURATION PARAMETERS SUMMARY" in out
        assert "(disable_validation)" in out
        assert "(retain_deleted_docs)" in out
        assert "(micro_batch_size)" in out

    def test_flag_with_verbose_and_category_shows_filtered_details(self, monkeypatch, capsys):
        monkeypatch.setattr(
            sys,
            "argv",
            ["docling-pipelines", "--list-global-config", "--verbose", "--category", "Orchestration configuration"],
        )

        docpipe_cli.main()

        out = capsys.readouterr().out
        assert "CATEGORY: Orchestration configuration" in out
        assert "Parameter: micro_batch_size" in out
        assert "Parameter: disable_validation" not in out

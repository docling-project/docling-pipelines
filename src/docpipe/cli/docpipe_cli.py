import argparse
import hashlib
import json
import os
import re
import sys
import uuid
from pathlib import Path
from typing import Any

from docpipe.utils.infrastructure.flow_execution_reporter import FlowExecutionReporter
from docpipe.utils.infrastructure.logging import get_logger, set_dpk_log_level_from_ds_log_level, setup_logging

logger = get_logger()


def sanitize_flow_name_for_job_id(*, flow_name: str) -> str:
    """
    Sanitize flow_name to create a valid job_id.
    Converts to lowercase and replaces special characters/spaces with hyphens.
    Preserves Unicode word characters (letters from any language, digits, underscores).

    Args:
        flow_name: The flow name to sanitize

    Returns:
        Sanitized flow name suitable for use as job_id

    Raises:
        ValueError: If flow_name is empty or contains only whitespace
    """
    if not flow_name or not flow_name.strip():
        raise ValueError("flow_name cannot be empty")

    # Convert to lowercase and replace non-word chars (preserves Unicode letters/digits) with hyphens
    sanitized = re.sub(r"[^\w]+", "-", flow_name.lower(), flags=re.UNICODE)
    # Remove leading/trailing hyphens
    return sanitized.strip("-")


def generate_job_id_from_flow_name(*, flow_name: str) -> str:
    """
    Generate a deterministic job_id from flow_name using UUID v5.

    Process:
    1. Sanitize flow_name (lowercase, replace special chars with hyphens)
    2. Generate 8-char hash from original flow_name
    3. Create intermediate string: {sanitized}_{hash}
    4. Generate UUID v5 from intermediate string

    This ensures:
    - Deterministic: Same flow_name always generates same job_id
    - Compatible: 36-character UUID format works with PostgreSQL job_stats_store
    - Standard: Same format as UUID v4 (8-4-4-4-12 with hyphens)
    - Unique: Different flow_names generate different job_ids

    Format: Standard UUID (8-4-4-4-12 format, 36 chars total)
    Example: "a1b2c3d4-e5f6-5789-a012-b3c4d5e6f7a8"

    Args:
        flow_name: The flow name from the flow definition

    Returns:
        Generated job_id as UUID v5 string (36 characters)
    """
    # Sanitize flow_name for consistency
    sanitized = sanitize_flow_name_for_job_id(flow_name=flow_name)

    # Generate deterministic hash (first 8 chars of SHA256)
    hash_value = hashlib.sha256(flow_name.encode("utf-8")).hexdigest()[:8]

    # Create intermediate string: {sanitized}_{hash}
    intermediate = f"{sanitized}_{hash_value}"

    # Generate deterministic UUID v5 from intermediate string
    # Using DNS namespace ensures global uniqueness
    job_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, intermediate))

    logger.info("Generated job_id '%s' from flow_name '%s' (intermediate: '%s')", job_id, flow_name, intermediate)
    return job_id


def _enrich_exception_from_job_stats(*, exception: Exception, job_run_id: str) -> None:
    """Attach per-node error detail from the job stats store to the exception.

    Prefect serialises exceptions across task boundaries, which drops the
    __cause__ chain and loses the operator-level failure message.  The job
    stats store records the real error string in NodeStats.error before that
    boundary is crossed, so we read it back here and attach it as
    a ``node_failures`` attribute so the CLI summary box can display it.
    """
    try:
        from docpipe.core.job_management.adapters.config.job_management_factory import get_default_factory

        factory = get_default_factory()
        store = factory.create_job_stats_store()
        node_stats_list = store.get_node_stats(job_run_id=job_run_id)

        failed_nodes = [ns for ns in (node_stats_list or []) if getattr(ns, "node_status", None) == "Failed"]
        if not failed_nodes:
            return

        node_failures = {ns.name: ns.error for ns in failed_nodes if getattr(ns, "error", None)}
        if node_failures:
            exception.node_failures = node_failures  # type: ignore[attr-defined]
    except Exception:  # nosec B110 — best-effort enrichment, never block the raise
        pass


def run_command_line_executor(flow_def: dict, original_flow_json: dict | None = None) -> None:
    """Run command line executor."""
    from docpipe.core.constants.constants import DocpipeConstants
    from docpipe.core.orchestration.flow_executor import FlowExecutor
    from docpipe.core.orchestration.orchestrator_factory import OrchestratorFactory
    from docpipe.integrations.secrets.vault_initializer import initialize_secret_providers
    from docpipe.utils.infrastructure import get_telemetry_service

    # Register secret providers (no-op when secrets.vault.enabled=false in config)
    initialize_secret_providers()

    # Initialise telemetry early so spans and metrics are captured during flow execution
    telemetry = get_telemetry_service()
    telemetry.initialize()

    # Create execution reporter for user-friendly console output
    execution_reporter = FlowExecutionReporter()

    logger.info(">>> Creating the orchestrator")
    orchestrator = OrchestratorFactory.create_orchestrator(execution_reporter=execution_reporter)
    logger.info(">>> Setting up execution parameters")
    # Generate job_id from flow name (required field in compiled flow)
    flow_name = flow_def.get("name")
    if not flow_name:
        raise ValueError("Flow definition must include a 'name' field (compiled from 'flow_name' in authoring format)")
    job_id = generate_job_id_from_flow_name(flow_name=flow_name)
    job_run_id = str(uuid.uuid4())

    params: dict[str, Any] = {
        DocpipeConstants.JOB_ID: job_id,
        DocpipeConstants.JOB_RUN_ID: job_run_id,
    }
    flow_global_config = flow_def.get("global_config", {})
    if DocpipeConstants.ENABLE_MICRO_BATCHING not in flow_global_config:
        params[DocpipeConstants.ENABLE_MICRO_BATCHING] = True

    os.environ["RUNTIME"] = "local"
    from docpipe.core.models.session_info import (
        SessionInfo,
        create_session_info,
        set_session_info,
    )

    session_info: SessionInfo = create_session_info(
        cli_mode=True,
        job_id=job_id,
        job_run_id=job_run_id,
        orchestrator=orchestrator,
        flow_id=flow_def.get(DocpipeConstants.FLOW_ID, job_id),
    )
    set_session_info(session_info)

    logger.info(">>> Creating the flow executor")
    executor = FlowExecutor(flow_def=flow_def, orchestrator=orchestrator, original_flow_def=original_flow_json)

    orchestrator.initialize(job_id=job_id, job_run_id=job_run_id)

    logger.info(">>> Starting flow execution")
    try:
        executor.execute(orchestrator=orchestrator, params=params)
    except Exception as exc:
        # Attempt to enrich the exception message with per-node error detail
        # stored in the job stats before Prefect's task boundary erased it.
        _enrich_exception_from_job_stats(exception=exc, job_run_id=job_run_id)
        raise
    finally:
        telemetry.shutdown()
    logger.info(">>> Completed flow execution")


def load_flow_definition(*, file_path: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """
    Load and compile an authoring format flow definition from a JSON file.

    The authoring format is automatically compiled to runtime DAG format for execution.
    Returns both the original flow definition and the compiled DAG.

    Args:
        file_path: Path to the JSON file containing the flow definition

    Returns:
        Tuple of (original_flow_json, compiled_runtime_dag)

    Raises:
        FileNotFoundError: If the flow definition file is not found
        json.JSONDecodeError: If the file contains invalid JSON
        FlowInvalidDataException: If the flow definition is invalid or required fields are missing
        Exception: For other compilation errors
    """
    from docpipe.core.assets.flows.application.services.authoring_compiler import AuthoringCompiler
    from docpipe.core.assets.flows.domain.models.authoring_flow import AuthoringFlow

    with Path(file_path).open(encoding="utf-8") as file:
        original_flow_json: dict[str, Any] = json.load(file)

    logger.info("Loading authoring format flow from %s", file_path)

    # Parse and validate authoring flow
    authoring_flow = AuthoringFlow.from_dict(data=original_flow_json)

    # Compile to runtime DAG format
    compiler = AuthoringCompiler()
    runtime_dag = compiler.compile(authoring_flow=authoring_flow)

    logger.info("Successfully compiled authoring format to runtime DAG")
    return original_flow_json, runtime_dag


def validate_flow_definition(flow_file: str) -> bool:
    """
    Validate a flow definition file.

    Args:
        flow_file: Path to the flow definition JSON file

    Returns:
        True if validation succeeds, False otherwise
    """
    from docpipe.core.constants.constants import DocpipeConstants
    from docpipe.core.models.session_info import create_session_info
    from docpipe.core.orchestration.flow_validator import FlowValidator
    from docpipe.core.orchestration.orchestrator_factory import OrchestratorFactory
    from docpipe.exceptions.docpipe_exceptions import FlowInvalidDataException, FlowValidationException

    try:
        _original_flow_json, flow_def = load_flow_definition(file_path=flow_file)
        flow_name: str = flow_def.get("name", "Unnamed flow")

        logger.info(
            "Validating flow: '%s' number of operators: %d",
            flow_name,
            len(flow_def.get("dag", [])),
        )

        orchestrator = OrchestratorFactory.create_orchestrator()
        validation_job_id = f"validation_{uuid.uuid4()}"
        validation_job_run_id = f"validation_run_{uuid.uuid4()}"

        create_session_info(
            job_id=validation_job_id,
            job_run_id=validation_job_run_id,
            orchestrator=orchestrator,
            flow_id=flow_def.get(DocpipeConstants.FLOW_ID, validation_job_id),
        )

        orchestrator.initialize(job_id=validation_job_id, job_run_id=validation_job_run_id)

        FlowValidator(orchestrator=orchestrator).validate(flow_def=flow_def, params={})

        logger.info("Validation successful: '%s' is valid", flow_name)
        return True

    except FileNotFoundError:
        cwd = Path.cwd()
        abs_path = Path(flow_file).resolve()
        logger.error("Flow definition file not found")
        logger.error("  Searched for: %s", abs_path)
        logger.error("  Current directory: %s", cwd)
        return False

    except json.JSONDecodeError as e:
        logger.error("Invalid JSON in flow definition file")
        logger.error("  File: %s", flow_file)
        logger.error("  Line %d, Column %d: %s", e.lineno, e.colno, e.msg)
        return False

    except (FlowInvalidDataException, KeyError) as e:
        logger.error("Flow validation failed")
        logger.error("  File: %s", flow_file)
        logger.error("  Error: %s", str(e))
        return False

    except FlowValidationException as e:
        errors: list[Any] = e.errors or []
        warnings: list[Any] = e.warnings or []

        for i, err in enumerate(errors, 1):
            logger.error("Error %d: %s", i, getattr(err, "message", str(err)))

        for i, warn in enumerate(warnings, 1):
            logger.warning("Warning %d: %s", i, getattr(warn, "message", str(warn)))

        # Only fail on errors, not warnings
        return not errors

    except Exception:
        logger.exception("Validation failed with unexpected error")
        return False


def _handle_subcommands(*, args: argparse.Namespace, parser: argparse.ArgumentParser) -> bool:
    """Handle subcommands and fast-exit flags. Returns True if the caller should return immediately."""
    if args.command == "validate-flow":
        success = validate_flow_definition(flow_file=args.flow_file)
        sys.exit(0 if success else 1)

    if args.command == "list-global-config":
        from docpipe.utils.global_config.display import list_global_config

        print(list_global_config(category=args.category, verbose=args.verbose))
        return True

    if args.list_operators:
        from docpipe.utils.operators.display import list_operators

        print(
            list_operators(
                verbose=args.verbose,
                summary_only=not args.verbose,  # Default: summary table, Verbose: detailed view
            )
        )
        return True

    if args.list_global_config:
        from docpipe.utils.global_config.display import list_global_config

        print(list_global_config(verbose=args.verbose, category=args.category))
        return True

    if not args.flow_file:
        parser.error("--flow-file is required unless using a subcommand or --list-operators or --list-global-config")

    if args.validate:
        success = validate_flow_definition(flow_file=args.flow_file)
        sys.exit(0 if success else 1)

    return False


def _load_flow_or_exit(*, flow_file: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Load and compile the flow definition, or exit with code 1 on any error."""
    from docpipe.exceptions.docpipe_exceptions import FlowInvalidDataException

    logger.info("Loading flow definition from %s", flow_file)
    try:
        return load_flow_definition(file_path=flow_file)
    except FileNotFoundError:
        cwd = Path.cwd()
        abs_path = Path(flow_file).resolve()
        logger.error("Flow definition file not found")
        logger.error("  Searched for: %s", abs_path)
        logger.error("  Current directory: %s", cwd)
        logger.error("Suggestions:")
        logger.error("  - Check if the file path is correct")
        logger.error("  - Verify the file exists in the specified location")
        logger.error("  - Use absolute path or path relative to: %s", cwd)
        sys.exit(1)
    except json.JSONDecodeError as e:
        logger.error("Invalid JSON in flow definition file")
        logger.error("  File: %s", flow_file)
        logger.error("  Line %d, Column %d: %s", e.lineno, e.colno, e.msg)
        logger.error("Suggestions:")
        logger.error("  - Validate JSON syntax using: python -m json.tool %s", flow_file)
        logger.error("  - Check for missing commas, brackets, or quotes")
        logger.error("  - Use a JSON validator: https://jsonlint.com/")
        sys.exit(1)
    except FlowInvalidDataException as e:
        logger.error("Flow validation failed")
        logger.error("  File: %s", flow_file)
        logger.error("%s", str(e))
        logger.error("Suggestions:")
        logger.error("  - Review the authoring format documentation")
        logger.error("  - Check operator names and dependencies")
        logger.error("  - Ensure all required fields are present")
        logger.error("  - Verify operator types are valid")
        sys.exit(1)
    except Exception as e:
        logger.error("Failed to compile flow")
        logger.error("  File: %s", flow_file)
        logger.error("  Error: %s", str(e))
        logger.exception("Compilation error details:")
        sys.exit(1)


def _execute_flow_or_exit(*, flow_def: dict[str, Any], original_flow_json: dict[str, Any]) -> None:
    """Execute the flow, formatting any exception and exiting with code 1 on failure."""
    try:
        run_command_line_executor(flow_def=flow_def, original_flow_json=original_flow_json)
        logger.info("Execution completed")
    except Exception as e:
        from docpipe.exceptions.docpipe_exceptions import DocpipeException, FlowValidationException
        from docpipe.utils.infrastructure.error_formatter import (
            format_docpipe_exception,
            format_generic_exception,
            format_validation_exception,
        )

        if isinstance(e, DocpipeException):
            flow_name = flow_def.get("name")
            if isinstance(e, FlowValidationException) and flow_name:
                formatted_error = format_validation_exception(exception=e, flow_name=flow_name)
            else:
                formatted_error = format_docpipe_exception(exception=e)
            logger.error(formatted_error)
        else:
            formatted_error = format_generic_exception(exception=e)
            logger.error(formatted_error)
            logger.debug("Full stack trace:", exc_info=True)
        sys.exit(1)


def main() -> None:  # pragma: no cover
    """Main."""
    os.environ["CMD_LINE"] = "True"

    parser = argparse.ArgumentParser(
        description="Execute or validate a flow definition using the CommandLineOrchestrator.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  docling-pipelines --flow-file flow.json
  docling-pipelines --flow-file flow.json --validate
  docling-pipelines validate-flow flow.json
  docling-pipelines --list-operators
  docling-pipelines --list-operators --verbose
  docling-pipelines --list-global-config
  docling-pipelines --list-global-config --verbose
  docling-pipelines --list-global-config --category "Orchestration configuration"
        """,
    )

    subparsers = parser.add_subparsers(dest="command")

    # -------------------------
    # validate-flow subcommand
    # -------------------------
    validate_parser = subparsers.add_parser(
        "validate-flow",
        help="Validate a flow definition without executing it",
    )
    validate_parser.add_argument(
        "flow_file",
        help="Path to the flow definition JSON file to validate",
    )

    # -------------------------
    # list-global-config subcommand
    # -------------------------
    list_global_config_parser = subparsers.add_parser(
        "list-global-config",
        help="List all global configuration parameters",
    )
    list_global_config_parser.add_argument(
        "--category",
        "-c",
        type=str,
        default=argparse.SUPPRESS,
        help="Filter by category (e.g., 'Execution Control', 'Incremental Processing', 'Orchestration configuration')",
    )
    list_global_config_parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Show detailed parameter information",
    )

    # -------------------------
    # global args
    # -------------------------
    parser.add_argument(
        "--flow-file",
        "-f",
        help="Path to the flow definition JSON file",
    )

    parser.add_argument(
        "--list-operators",
        "-lo",
        action="store_true",
        help="List all available operators and exit",
    )
    parser.add_argument(
        "--list-global-config",
        "-lgc",
        action="store_true",
        help="List all global configuration parameters and exit",
    )
    parser.add_argument(
        "--category",
        "-c",
        type=str,
        help="Filter by category (use with --list-global-config)",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose output (use with --list-operators or --list-global-config)",
    )
    parser.add_argument(
        "--validate",
        action="store_true",
        help="Validate the flow definition without executing it",
    )

    args = parser.parse_args()

    # Configure DPK log level to match DS_LOG_LEVEL
    set_dpk_log_level_from_ds_log_level()

    # Install handlers on the root docpipe logger for CLI output
    setup_logging()

    # Re-fetch logger now that setup_logging() has installed handlers
    global logger
    logger = get_logger()

    if _handle_subcommands(args=args, parser=parser):
        return

    original_flow_json, flow_def = _load_flow_or_exit(flow_file=args.flow_file)

    logger.info("Loaded flow definition from %s", args.flow_file)
    logger.info("Flow name: %s", flow_def.get("name", "Unnamed flow"))
    logger.info("Number of operators: %d", len(flow_def.get("dag", [])))

    _execute_flow_or_exit(flow_def=flow_def, original_flow_json=original_flow_json)


if __name__ == "__main__":  # pragma: no cover
    main()

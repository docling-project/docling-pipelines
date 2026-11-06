#!/usr/bin/env python3
"""
Test Script for Examples Directory

This script executes all example Python files in the examples/ directory and verifies
their expected outputs. It provides a comprehensive test suite to ensure all examples
work correctly after repository reorganization.

Usage:
    # Run all tests
    python scripts/test_examples.py

    # Run specific category
    python scripts/test_examples.py --category operators

    # Dry run (show what would be tested)
    python scripts/test_examples.py --dry-run

    # Verbose output
    python scripts/test_examples.py --verbose

Prerequisites:
    - Virtual environment activated: source src/docpipe_app/backend/.venv/bin/activate
    - PYTHONPATH set: export PYTHONPATH="$(pwd)/src/docpipe_app/backend:${PYTHONPATH}"
    - Ollama running (for embedding examples): http://localhost:11434
    - OpenSearch running (for vector DB examples): http://localhost:9200
"""

import argparse
import subprocess
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class TestCategory(Enum):
    """Categories of example tests"""

    OPERATORS = "operators"
    CONNECTORS = "connectors"
    FLOW_MANAGER = "flow_manager"
    RETRIEVAL = "retrieval"
    ALL = "all"


class TestStatus(Enum):
    """Test execution status"""

    PASSED = "✓ PASSED"
    FAILED = "✗ FAILED"
    SKIPPED = "⊘ SKIPPED"
    ERROR = "✗ ERROR"


@dataclass
class TestResult:
    """Result of a test execution"""

    name: str
    status: TestStatus
    duration: float
    output: str
    error: str | None = None
    skip_reason: str | None = None


@dataclass
class ExampleTest:
    """Definition of an example test"""

    name: str
    path: Path
    category: TestCategory
    requires_ollama: bool = False
    requires_opensearch: bool = False
    requires_env: list[str] | None = None
    requires_any_env: list[str] | None = None
    expected_outputs: list[str] | None = None
    timeout: int = 60


# These files are support modules or require a dedicated integration harness;
# they are intentionally not launched as standalone examples.
EXCLUDED_EXAMPLES = {
    "examples/custom_operators/example_custom_operator.py": "support example covered by the custom-operator package harness",
    "examples/custom_operators/hello_operator.py": "support example covered by the custom-operator package harness",
    "examples/custom_operators/package_example/my_custom_operators/__init__.py": "package module, not a runnable example",
    "examples/custom_operators/package_example/my_custom_operators/operators/reverse_operator.py": "operator module, not a runnable example",
    "examples/custom_operators/package_example/my_custom_operators/operators/uppercase_operator.py": "operator module, not a runnable example",
    "examples/duckdb_job_stats/duckdb_job_store_example.py": "requires the separate DuckDB job-store integration setup",
}


class ExampleTester:
    """Main test runner for examples"""

    def __init__(self, *, verbose: bool = False, dry_run: bool = False):
        self.verbose = verbose
        self.dry_run = dry_run
        self.repo_root = Path(__file__).parent.parent
        self.examples_dir = self.repo_root / "examples"
        self.results: list[TestResult] = []

    def define_tests(self) -> list[ExampleTest]:
        """Define all example tests with their requirements"""
        return [
            # Operator Examples
            ExampleTest(
                name="NOOP Operator",
                path=self.examples_dir / "noop_operator_example.py",
                category=TestCategory.OPERATORS,
                expected_outputs=["completed the operator", "output table has"],
                timeout=30,
            ),
            ExampleTest(
                name="Operator Metadata",
                path=self.examples_dir / "operator_metadata_example.py",
                category=TestCategory.OPERATORS,
                expected_outputs=["Key:", "value:"],
                timeout=30,
            ),
            ExampleTest(
                name="Ingest Filesystem Folder",
                path=self.examples_dir / "ingest_filesystem_example.py",
                category=TestCategory.OPERATORS,
                expected_outputs=["completed the operator", "output table has", "rows"],
                timeout=30,
            ),
            ExampleTest(
                name="Deduplication",
                path=self.examples_dir / "deduplication_example.py",
                category=TestCategory.OPERATORS,
                expected_outputs=["Ededup Output Table", "Ededup Output MetaData"],
                timeout=30,
            ),
            ExampleTest(
                name="Language Detection",
                path=self.examples_dir / "language_detection_example.py",
                category=TestCategory.OPERATORS,
                expected_outputs=["Language Detection", "Example completed"],
                timeout=60,
            ),
            ExampleTest(
                name="ML Enrichment",
                path=self.examples_dir / "ml_enrichment_example.py",
                category=TestCategory.OPERATORS,
                expected_outputs=["Enrichment Features", "ml_"],
                timeout=60,
            ),
            ExampleTest(
                name="Readability",
                path=self.examples_dir / "readability_example.py",
                category=TestCategory.OPERATORS,
                expected_outputs=["completed the operator", "total scores added"],
                timeout=30,
            ),
            ExampleTest(
                name="Redaction",
                path=self.examples_dir / "redaction_example.py",
                category=TestCategory.OPERATORS,
                expected_outputs=["completed the operator", "output table"],
                timeout=30,
            ),
            ExampleTest(
                name="PII/HAP Detection",
                path=self.examples_dir / "pii_hap_detection_example.py",
                category=TestCategory.OPERATORS,
                expected_outputs=['"input":', '"detectors":'],
                timeout=30,
            ),
            ExampleTest(
                name="Chunker",
                path=self.examples_dir / "chunker_example.py",
                category=TestCategory.OPERATORS,
                requires_ollama=True,
                expected_outputs=["SEMANTIC CHUNKING", "Number of rows after chunking"],
                timeout=120,
            ),
            ExampleTest(
                name="Embeddings Pipeline",
                path=self.examples_dir / "embeddings_pipeline_example.py",
                category=TestCategory.OPERATORS,
                requires_ollama=True,
                expected_outputs=["EMBEDDINGS PIPELINE", "Pipeline completed successfully"],
                timeout=180,
            ),
            ExampleTest(
                name="LiteLLM Embeddings",
                path=self.examples_dir / "embeddings_litellm_example.py",
                category=TestCategory.OPERATORS,
                requires_env=["OPENAI_API_KEY"],
                expected_outputs=["LiteLLM Embeddings Examples", "Summary"],
                timeout=60,
            ),
            ExampleTest(
                name="OpenSearch Integration",
                path=self.examples_dir / "opensearch_integration_example.py",
                category=TestCategory.OPERATORS,
                requires_opensearch=True,
                expected_outputs=["OpenSearch Operator", "All examples completed"],
                timeout=120,
            ),
            ExampleTest(
                name="Ingest Source",
                path=self.examples_dir / "ingest_source_example.py",
                category=TestCategory.OPERATORS,
                requires_env=["GOOGLE_DRIVE_CREDENTIALS"],
                expected_outputs=["INGESTION RESULTS"],
                timeout=60,
            ),
            # Connector Examples
            ExampleTest(
                name="S3 Adapter",
                path=self.examples_dir / "connectors" / "test_s3_adapter.py",
                category=TestCategory.CONNECTORS,
                requires_env=["S3_ACCESS_KEY", "S3_SECRET_KEY", "S3_BUCKET"],
                expected_outputs=["S3 Adapter Test", "All tests passed"],
                timeout=60,
            ),
            ExampleTest(
                name="OneDrive Adapter",
                path=self.examples_dir / "connectors" / "test_onedrive_adapter.py",
                category=TestCategory.CONNECTORS,
                requires_env=["ONEDRIVE_CLIENT_ID", "ONEDRIVE_CLIENT_SECRET"],
                expected_outputs=["OneDrive Adapter Test", "All tests passed"],
                timeout=60,
            ),
            ExampleTest(
                name="SharePoint Adapter",
                path=self.examples_dir / "connectors" / "test_sharepoint_adapter.py",
                category=TestCategory.CONNECTORS,
                requires_env=["SHAREPOINT_CLIENT_ID", "SHAREPOINT_CLIENT_SECRET"],
                expected_outputs=["SharePoint Adapter Test", "All tests passed"],
                timeout=60,
            ),
            ExampleTest(
                name="Google Drive Adapter",
                path=self.examples_dir / "connectors" / "test_google_drive_adapter.py",
                category=TestCategory.CONNECTORS,
                requires_env=["GOOGLE_DRIVE_CREDENTIALS"],
                expected_outputs=["Google Drive Adapter Test", "All tests passed"],
                timeout=60,
            ),
            ExampleTest(
                name="Web Adapter",
                path=self.examples_dir / "connectors" / "test_web_adapter.py",
                category=TestCategory.CONNECTORS,
                expected_outputs=["All tests completed successfully"],
                timeout=120,
            ),
            # Flow Manager Examples
            ExampleTest(
                name="Flow Manager Complete",
                path=self.examples_dir / "docpipe_flow_manager" / "00_complete_example.py",
                category=TestCategory.FLOW_MANAGER,
                requires_ollama=True,
                expected_outputs=["PipelineExecutor Complete Example", "Example completed successfully"],
                timeout=180,
            ),
            ExampleTest(
                name="Flow Manager Execute from File",
                path=self.examples_dir / "docpipe_flow_manager" / "01_execute_from_file.py",
                category=TestCategory.FLOW_MANAGER,
                requires_ollama=True,
                expected_outputs=["Execute Flow from File", "Execution completed"],
                timeout=120,
            ),
            ExampleTest(
                name="Flow Manager Execute from Dictionary",
                path=self.examples_dir / "docpipe_flow_manager" / "02_execute_from_dict.py",
                category=TestCategory.FLOW_MANAGER,
                requires_ollama=True,
                expected_outputs=["Example 2: Execute Flow from Dictionary", "Execution completed successfully"],
                timeout=180,
            ),
            ExampleTest(
                name="Flow Manager List Operators",
                path=self.examples_dir / "docpipe_flow_manager" / "03_list_operators.py",
                category=TestCategory.FLOW_MANAGER,
                expected_outputs=["Example 3: List Available Operators", "Operator Summary"],
                timeout=60,
            ),
            ExampleTest(
                name="Flow Manager Custom Configuration",
                path=self.examples_dir / "docpipe_flow_manager" / "04_custom_configuration.py",
                category=TestCategory.FLOW_MANAGER,
                requires_ollama=True,
                expected_outputs=["Example 4: Custom Configuration", "Execution successful"],
                timeout=180,
            ),
            ExampleTest(
                name="Flow Manager Notebook Usage",
                path=self.examples_dir / "docpipe_flow_manager" / "05_notebook_usage.py",
                category=TestCategory.FLOW_MANAGER,
                expected_outputs=["Example 5: Jupyter Notebook Usage Pattern"],
                timeout=180,
            ),
            ExampleTest(
                name="Flow Manager Basic Test",
                path=self.examples_dir / "docpipe_flow_manager" / "06_basic_test.py",
                category=TestCategory.FLOW_MANAGER,
                requires_ollama=True,
                expected_outputs=["Starting DocpipeFlowManager Test", "Test completed successfully"],
                timeout=180,
            ),
            # Local operator examples
            ExampleTest(
                name="Entity Curation",
                path=self.examples_dir / "entity_curation_example.py",
                category=TestCategory.OPERATORS,
                expected_outputs=["Curated Entities for All Documents"],
                timeout=60,
            ),
            ExampleTest(
                name="Extract Operator",
                path=self.examples_dir / "extract_operator_example.py",
                category=TestCategory.OPERATORS,
                expected_outputs=["EXTRACT OPERATOR"],
                timeout=180,
            ),
            ExampleTest(
                name="Ingest Local Folder",
                path=self.examples_dir / "ingest_local_folder_example.py",
                category=TestCategory.OPERATORS,
                expected_outputs=["completed the operator", "output table has"],
                timeout=60,
            ),
            ExampleTest(
                name="Document Set",
                path=self.examples_dir / "document_set_example.py",
                category=TestCategory.OPERATORS,
                expected_outputs=["DOCUMENT SET OPERATOR EXAMPLE", "EXAMPLE COMPLETED SUCCESSFULLY"],
                timeout=60,
            ),
            ExampleTest(
                name="Milvus Integration",
                path=self.examples_dir / "milvus_integration_example.py",
                category=TestCategory.OPERATORS,
                requires_any_env=["MILVUS_URI", "MILVUS_HOST"],
                expected_outputs=["Example 1: Basic Document Indexing"],
                timeout=180,
            ),
        ]

    def check_prerequisites(self, *, test: ExampleTest) -> tuple[bool, str | None]:
        """Check if test prerequisites are met"""
        # Check Ollama
        if test.requires_ollama:
            try:
                result = subprocess.run(
                    ["curl", "-s", "http://localhost:11434/api/tags"],
                    capture_output=True,
                    timeout=5,
                )
                if result.returncode != 0:
                    return False, "Ollama not running (http://localhost:11434)"
            except Exception:
                return False, "Ollama not accessible"

        # Check OpenSearch
        if test.requires_opensearch:
            try:
                result = subprocess.run(
                    ["curl", "-s", "http://localhost:9200"],
                    capture_output=True,
                    timeout=5,
                )
                if result.returncode != 0:
                    return False, "OpenSearch not running (http://localhost:9200)"
            except Exception:
                return False, "OpenSearch not accessible"

        # Check environment variables
        if test.requires_env:
            import os

            missing = [env for env in test.requires_env if not os.getenv(env)]
            if missing:
                return False, f"Missing environment variables: {', '.join(missing)}"

        if test.requires_any_env:
            import os

            from dotenv import dotenv_values

            configured = {
                **dotenv_values(self.repo_root / ".env"),
                **os.environ,
            }
            if not any(configured.get(env) for env in test.requires_any_env):
                choices = ", ".join(test.requires_any_env)
                return False, f"Missing any of these environment variables: {choices}"

        # Check file exists
        if not test.path.exists():
            return False, f"File not found: {test.path}"

        return True, None

    def run_test(self, *, test: ExampleTest) -> TestResult:
        """Execute a single test"""
        import time

        start_time = time.time()

        if self.dry_run:
            return TestResult(
                name=test.name,
                status=TestStatus.SKIPPED,
                duration=0,
                output="",
                skip_reason="Dry run mode",
            )

        # Check prerequisites
        can_run, skip_reason = self.check_prerequisites(test=test)
        if not can_run:
            return TestResult(
                name=test.name,
                status=TestStatus.SKIPPED,
                duration=0,
                output="",
                skip_reason=skip_reason,
            )

        # Run the test
        try:
            result = subprocess.run(
                [sys.executable, str(test.path)],
                capture_output=True,
                text=True,
                timeout=test.timeout,
                cwd=self.repo_root,
            )

            duration = time.time() - start_time
            output = result.stdout + result.stderr

            # Check for expected outputs
            if test.expected_outputs:
                missing_outputs = [exp for exp in test.expected_outputs if exp not in output]
                if missing_outputs:
                    return TestResult(
                        name=test.name,
                        status=TestStatus.FAILED,
                        duration=duration,
                        output=output,
                        error=f"Missing expected outputs: {', '.join(missing_outputs)}",
                    )

            # Check return code
            if result.returncode != 0:
                return TestResult(
                    name=test.name,
                    status=TestStatus.FAILED,
                    duration=duration,
                    output=output,
                    error=f"Non-zero exit code: {result.returncode}",
                )

            return TestResult(
                name=test.name,
                status=TestStatus.PASSED,
                duration=duration,
                output=output,
            )

        except subprocess.TimeoutExpired:
            duration = time.time() - start_time
            return TestResult(
                name=test.name,
                status=TestStatus.ERROR,
                duration=duration,
                output="",
                error=f"Timeout after {test.timeout}s",
            )
        except Exception as e:
            duration = time.time() - start_time
            return TestResult(
                name=test.name,
                status=TestStatus.ERROR,
                duration=duration,
                output="",
                error=str(e),
            )

    def run_tests(self, *, category: TestCategory = TestCategory.ALL) -> None:
        """Run all tests in specified category"""
        tests = self.define_tests()

        # Filter by category
        if category != TestCategory.ALL:
            tests = [t for t in tests if t.category == category]

        print("\n" + "=" * 80)
        print("DOCPIPE EXAMPLES TEST SUITE")
        print("=" * 80)
        print(f"Repository Root: {self.repo_root}")
        print(f"Examples Directory: {self.examples_dir}")
        print(f"Category: {category.value}")
        print(f"Total Tests: {len(tests)}")
        print(f"Mode: {'DRY RUN' if self.dry_run else 'EXECUTE'}")
        print("=" * 80)

        # Run tests
        for i, test in enumerate(tests, 1):
            print(f"\n[{i}/{len(tests)}] Testing: {test.name}")
            print(f"  File: {test.path.relative_to(self.repo_root)}")
            print(f"  Category: {test.category.value}")

            if test.requires_ollama:
                print("  Requires: Ollama")
            if test.requires_opensearch:
                print("  Requires: OpenSearch")
            if test.requires_env:
                print(f"  Requires: {', '.join(test.requires_env)}")
            if test.requires_any_env:
                print(f"  Requires any of: {', '.join(test.requires_any_env)}")

            result = self.run_test(test=test)
            self.results.append(result)

            print(f"  Status: {result.status.value}")
            print(f"  Duration: {result.duration:.2f}s")

            if result.skip_reason:
                print(f"  Reason: {result.skip_reason}")
            if result.error:
                print(f"  Error: {result.error}")

            if self.verbose and result.output:
                print("\n  Output:")
                for line in result.output.split("\n")[:20]:
                    print(f"    {line}")
                if len(result.output.split("\n")) > 20:
                    print("    ... (output truncated)")

    def print_summary(self) -> int:
        """Print test summary and return exit code"""
        print("\n" + "=" * 80)
        print("TEST SUMMARY")
        print("=" * 80)

        passed = sum(1 for r in self.results if r.status == TestStatus.PASSED)
        failed = sum(1 for r in self.results if r.status == TestStatus.FAILED)
        skipped = sum(1 for r in self.results if r.status == TestStatus.SKIPPED)
        errors = sum(1 for r in self.results if r.status == TestStatus.ERROR)

        print(f"\nTotal Tests: {len(self.results)}")
        print(f"  {TestStatus.PASSED.value}: {passed}")
        print(f"  {TestStatus.FAILED.value}: {failed}")
        print(f"  {TestStatus.SKIPPED.value}: {skipped}")
        print(f"  {TestStatus.ERROR.value}: {errors}")

        if failed > 0 or errors > 0:
            print("\nFailed/Error Tests:")
            for result in self.results:
                if result.status in [TestStatus.FAILED, TestStatus.ERROR]:
                    print(f"  - {result.name}: {result.error or 'Unknown error'}")

        if skipped > 0:
            print("\nSkipped Tests:")
            for result in self.results:
                if result.status == TestStatus.SKIPPED:
                    print(f"  - {result.name}: {result.skip_reason}")

        total_duration = sum(r.duration for r in self.results)
        print(f"\nTotal Duration: {total_duration:.2f}s")

        print("\n" + "=" * 80)

        # Return exit code
        if failed > 0 or errors > 0:
            print("RESULT: FAILED")
            return 1
        if passed > 0:
            print("RESULT: PASSED")
            return 0
        print("RESULT: NO TESTS RUN")
        return 0


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description="Test all example scripts in the examples/ directory")
    parser.add_argument(
        "--category",
        choices=[c.value for c in TestCategory],
        default=TestCategory.ALL.value,
        help="Test category to run (default: all)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be tested without executing",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show detailed output from tests",
    )

    args = parser.parse_args()

    tester = ExampleTester(verbose=args.verbose, dry_run=args.dry_run)
    tester.run_tests(category=TestCategory(args.category))
    exit_code = tester.print_summary()

    sys.exit(exit_code)


if __name__ == "__main__":
    main()

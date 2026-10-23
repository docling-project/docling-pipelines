"""Tests for the example registry and prerequisite handling."""

from pathlib import Path

from scripts.test_examples import (
    EXCLUDED_EXAMPLES,
    ExampleTest,
    ExampleTester,
)
from scripts.test_examples import (
    TestCategory as ExampleCategory,
)
from scripts.test_examples import (
    TestStatus as ExampleStatus,
)


def test_define_tests_registers_every_python_example() -> None:
    tester = ExampleTester(dry_run=True)
    registered = {test.path.relative_to(tester.repo_root) for test in tester.define_tests()}

    expected = {
        Path("examples/docpipe_flow_manager/02_execute_from_dict.py"),
        Path("examples/docpipe_flow_manager/03_list_operators.py"),
        Path("examples/docpipe_flow_manager/04_custom_configuration.py"),
        Path("examples/docpipe_flow_manager/05_notebook_usage.py"),
        Path("examples/docpipe_flow_manager/06_basic_test.py"),
        Path("examples/entity_curation_example.py"),
        Path("examples/extract_operator_example.py"),
        Path("examples/ingest_local_folder_example.py"),
        Path("examples/document_set_example.py"),
        Path("examples/milvus_integration_example.py"),
        Path("examples/connectors/test_web_adapter.py"),
    }

    assert expected <= registered

    all_examples = {
        path.relative_to(tester.repo_root).as_posix()
        for path in (tester.repo_root / "examples").rglob("*.py")
        if "__pycache__" not in path.parts
    }
    assert all_examples == {path.as_posix() for path in registered} | set(EXCLUDED_EXAMPLES)


def test_category_filtering_keeps_only_requested_category() -> None:
    tester = ExampleTester(dry_run=True)
    tests = [test for test in tester.define_tests() if test.category == ExampleCategory.CONNECTORS]

    assert tests
    assert all(test.category is ExampleCategory.CONNECTORS for test in tests)


def test_registered_examples_use_their_actual_default_requirements_and_output() -> None:
    tester = ExampleTester(dry_run=True)
    tests_by_name = {test.name: test for test in tester.define_tests()}

    notebook = tests_by_name["Flow Manager Notebook Usage"]
    assert notebook.requires_ollama is False

    entity_curation = tests_by_name["Entity Curation"]
    assert entity_curation.expected_outputs == ["Curated Entities for All Documents"]

    extract = tests_by_name["Extract Operator"]
    assert extract.requires_env is None
    assert extract.expected_outputs == ["EXTRACT OPERATOR"]


def test_missing_example_is_skipped_with_a_reason(tmp_path: Path) -> None:
    tester = ExampleTester(dry_run=False)
    missing = ExampleTest(
        name="missing",
        path=tmp_path / "missing.py",
        category=ExampleCategory.OPERATORS,
    )

    result = tester.run_test(test=missing)

    assert result.status is ExampleStatus.SKIPPED
    assert result.skip_reason == f"File not found: {missing.path}"


def test_missing_prerequisite_is_skipped_before_execution(monkeypatch, tmp_path: Path) -> None:
    tester = ExampleTester(dry_run=False)
    example = tmp_path / "example.py"
    example.write_text("raise RuntimeError('must not execute')\n", encoding="utf-8")
    test = ExampleTest(
        name="needs credentials",
        path=example,
        category=ExampleCategory.CONNECTORS,
        requires_env=["TEST_EXAMPLES_MISSING"],
    )
    monkeypatch.delenv("TEST_EXAMPLES_MISSING", raising=False)

    result = tester.run_test(test=test)

    assert result.status is ExampleStatus.SKIPPED
    assert result.skip_reason == "Missing environment variables: TEST_EXAMPLES_MISSING"


def test_nonzero_example_is_reported_as_failed(tmp_path: Path) -> None:
    tester = ExampleTester(dry_run=False)
    example = tmp_path / "example.py"
    example.write_text("print('started')\nraise SystemExit(2)\n", encoding="utf-8")
    test = ExampleTest(
        name="failing example",
        path=example,
        category=ExampleCategory.OPERATORS,
        expected_outputs=["started"],
    )

    result = tester.run_test(test=test)

    assert result.status is ExampleStatus.FAILED
    assert result.error == "Non-zero exit code: 2"

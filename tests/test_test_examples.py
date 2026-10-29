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

    milvus = tests_by_name["Milvus Integration"]
    assert milvus.requires_env is None
    assert milvus.requires_any_env == ["MILVUS_URI", "MILVUS_HOST"]


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


def test_web_example_connection_failure_is_reported_as_failed(tmp_path: Path) -> None:
    tester = ExampleTester(dry_run=False)
    registered = {test.name: test for test in tester.define_tests()}["Web Adapter"]
    wrapper = tmp_path / "web_adapter_failure.py"
    wrapper.write_text(
        "\n".join(
            [
                "import asyncio",
                "import sys",
                f"sys.path.insert(0, {str(tester.repo_root)!r})",
                "from examples.connectors import test_web_adapter as example",
                "async def reject_connection(self, *, config):",
                "    return False, 'connection refused'",
                "example.WebPageSourceAdapter.test_connection = reject_connection",
                "asyncio.run(example.main())",
            ]
        ),
        encoding="utf-8",
    )
    test = ExampleTest(
        name=registered.name,
        path=wrapper,
        category=registered.category,
        expected_outputs=registered.expected_outputs,
        timeout=registered.timeout,
    )

    result = tester.run_test(test=test)

    assert result.status is ExampleStatus.FAILED
    assert "connection refused" in result.output


def test_milvus_prerequisite_accepts_exported_uri_without_token(monkeypatch) -> None:
    tester = ExampleTester(dry_run=False)
    test = {test.name: test for test in tester.define_tests()}["Milvus Integration"]
    monkeypatch.setenv("MILVUS_URI", "https://milvus.example.test")
    monkeypatch.delenv("MILVUS_HOST", raising=False)
    monkeypatch.delenv("MILVUS_TOKEN", raising=False)

    assert tester.check_prerequisites(test=test) == (True, None)


def test_milvus_prerequisite_accepts_dotenv_standalone_host(monkeypatch, tmp_path: Path) -> None:
    tester = ExampleTester(dry_run=False)
    tester.repo_root = tmp_path
    example = tmp_path / "examples" / "milvus_integration_example.py"
    example.parent.mkdir()
    example.write_text("", encoding="utf-8")
    (tmp_path / ".env").write_text(
        "MILVUS_HOST=milvus.example.test\nMILVUS_PORT=19530\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("MILVUS_URI", raising=False)
    monkeypatch.delenv("MILVUS_HOST", raising=False)
    test = ExampleTest(
        name="Milvus Integration",
        path=example,
        category=ExampleCategory.OPERATORS,
        requires_any_env=["MILVUS_URI", "MILVUS_HOST"],
    )

    assert tester.check_prerequisites(test=test) == (True, None)


def test_milvus_prerequisite_skips_without_uri_or_host(monkeypatch, tmp_path: Path) -> None:
    tester = ExampleTester(dry_run=False)
    tester.repo_root = tmp_path
    example = tmp_path / "milvus_integration_example.py"
    example.write_text("", encoding="utf-8")
    monkeypatch.delenv("MILVUS_URI", raising=False)
    monkeypatch.delenv("MILVUS_HOST", raising=False)
    test = ExampleTest(
        name="Milvus Integration",
        path=example,
        category=ExampleCategory.OPERATORS,
        requires_any_env=["MILVUS_URI", "MILVUS_HOST"],
    )

    assert tester.check_prerequisites(test=test) == (
        False,
        "Missing any of these environment variables: MILVUS_URI, MILVUS_HOST",
    )

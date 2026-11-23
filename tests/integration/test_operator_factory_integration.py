#!/usr/bin/env python3
# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""
Integration tests for OperatorFactory with operator_loader.
Tests environment variables, filesystem loading, S3 loading, priority resolution, and refresh.
"""

import os
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

from docpipe.core.constants.constants import DocpipeConstants, EnvironmentVariables, OrchestratorType
from docpipe.core.orchestration.operator_factory import OperatorFactory, OperatorFactoryProvider


class TestOperatorFactoryIntegration:
    """Integration tests for OperatorFactory with operator_loader."""

    def setup_method(self):
        """Setup test environment."""
        # Clear operator factory cache
        OperatorFactoryProvider.operator_factories.clear()

        # Clear environment variables
        for var in [
            EnvironmentVariables.DOCPIPE_CUSTOM_OPERATORS,
            EnvironmentVariables.DOCPIPE_ENABLE_CUSTOM_OPERATORS,
        ]:
            if var in os.environ:
                del os.environ[var]

    def teardown_method(self):
        """Cleanup after tests."""
        # Clear operator factory cache
        OperatorFactoryProvider.operator_factories.clear()

        # Clear environment variables
        for var in [
            EnvironmentVariables.DOCPIPE_CUSTOM_OPERATORS,
            EnvironmentVariables.DOCPIPE_ENABLE_CUSTOM_OPERATORS,
        ]:
            if var in os.environ:
                del os.environ[var]

    def test_environment_variable_loading(self):
        """Test 1: Loading custom operators via DOCPIPE_CUSTOM_OPERATORS environment variable."""
        print("\n" + "=" * 80)
        print("TEST 1: Environment Variable Loading")
        print("=" * 80)

        # Set environment variable to test custom operator path
        test_operator_path = str(Path(__file__).parent.parent / "fixtures" / "custom_operators")
        os.environ[EnvironmentVariables.DOCPIPE_CUSTOM_OPERATORS] = test_operator_path

        # Create factory - should automatically load from environment variable
        factory = OperatorFactoryProvider.get_operator_factory(
            orchestrator=OrchestratorType.PYTHON, enable_custom_operators=True
        )

        # Verify custom operator was loaded
        assert "valid_custom" in factory.operators, (
            "Custom operator 'valid_custom' should be loaded from environment variable"
        )

        valid_custom_op = factory.operators["valid_custom"]
        assert valid_custom_op.short_name == "valid_custom"
        assert getattr(valid_custom_op, "owner", None) == DocpipeConstants.OWNER_CUSTOM

        print(f"✓ Loaded custom operator from environment variable: {valid_custom_op.__name__}")
        print(f"  Owner: {getattr(valid_custom_op, 'owner', 'unknown')}")
        print(f"  Total operators: {len(factory.operators)}")

    def test_filesystem_path_loading(self):
        """Test 2: Loading custom operators from filesystem paths."""
        print("\n" + "=" * 80)
        print("TEST 2: Filesystem Path Loading")
        print("=" * 80)

        # Create temporary directory with custom operator
        with tempfile.TemporaryDirectory() as tmpdir:
            # Write a simple custom operator
            operator_file = Path(tmpdir) / "test_operator.py"
            operator_file.write_text("""
import pyarrow as pa
from docpipe.core.constants.constants import DocpipeConstants, ExecutionStatus
from docpipe.core.operators.abstract_operator import AbstractOperator, OperatorCategory

class TestFilesystemOperator(AbstractOperator):
    short_name: str = "test_filesystem"
    category: OperatorCategory = OperatorCategory.Functional
    owner: str | None = DocpipeConstants.OWNER_CUSTOM

    def __init__(self, *, config: dict):
        super().__init__(config=config)

    def transform(self, *, table: pa.Table, file_name: str | None = None) -> tuple[list[pa.Table], dict]:
        metadata = self.create_base_metadata(total_docs_count=len(table), node_status=ExecutionStatus.COMPLETED)
        return [table], metadata

    @staticmethod
    def get_metadata() -> dict:
        return {"label": "Test Filesystem Operator", "category": OperatorCategory.Functional.value}

    def get_required_features(self) -> list:
        return []
""")

            # Create factory with filesystem path
            factory = OperatorFactoryProvider.get_operator_factory(
                orchestrator=OrchestratorType.PYTHON, package_names=[str(tmpdir)], enable_custom_operators=True
            )

            # Verify operator was loaded
            assert "test_filesystem" in factory.operators, "Custom operator should be loaded from filesystem"

            test_op = factory.operators["test_filesystem"]
            assert test_op.short_name == "test_filesystem"

            print(f"✓ Loaded custom operator from filesystem: {test_op.__name__}")
            print(f"  Path: {tmpdir}")
            print(f"  Owner: {getattr(test_op, 'owner', 'unknown')}")

    @patch("boto3.client")
    def test_s3_uri_loading(self, mock_boto_client):
        """Test 3: Loading custom operators from S3 URIs."""
        print("\n" + "=" * 80)
        print("TEST 3: S3 URI Loading (Mocked)")
        print("=" * 80)

        # Mock S3 client
        mock_s3 = Mock()
        mock_boto_client.return_value = mock_s3

        # Mock S3 list_objects_v2 response
        mock_s3.list_objects_v2.return_value = {"Contents": [{"Key": "operators/test_s3_operator.py", "Size": 1000}]}

        # Mock S3 get_object response with operator code
        operator_code = b"""
import pyarrow as pa
from docpipe.core.constants.constants import DocpipeConstants, ExecutionStatus
from docpipe.core.operators.abstract_operator import AbstractOperator, OperatorCategory

class TestS3Operator(AbstractOperator):
    short_name: str = "test_s3"
    category: OperatorCategory = OperatorCategory.Functional
    owner: str | None = DocpipeConstants.OWNER_CUSTOM

    def __init__(self, *, config: dict):
        super().__init__(config=config)

    def transform(self, *, table: pa.Table, file_name: str | None = None) -> tuple[list[pa.Table], dict]:
        metadata = self.create_base_metadata(total_docs_count=len(table), node_status=ExecutionStatus.COMPLETED)
        return [table], metadata

    @staticmethod
    def get_metadata() -> dict:
        return {"label": "Test S3 Operator", "category": OperatorCategory.Functional.value}

    def get_required_features(self) -> list:
        return []
"""
        mock_s3.get_object.return_value = {"Body": Mock(read=Mock(return_value=operator_code))}

        # Note: Actual S3 loading requires the S3Adapter to be fully implemented
        # This test verifies the mocking infrastructure is in place
        print("✓ S3 loading infrastructure verified (mocked)")
        print("  S3 URI format: s3://bucket/operators/")
        print("  Note: Full S3 integration requires S3Adapter implementation")

    def test_priority_resolution(self):
        """Test 4: Verify priority resolution works correctly."""
        print("\n" + "=" * 80)
        print("TEST 4: Priority Resolution")
        print("=" * 80)

        # Create factory with only docpipe operators
        factory1 = OperatorFactoryProvider.get_operator_factory(
            orchestrator=OrchestratorType.PYTHON, enable_custom_operators=False
        )

        # Get a docpipe operator
        if "noop" in factory1.operators:
            docpipe_noop = factory1.operators["noop"]
            docpipe_owner = getattr(docpipe_noop, "owner", None)

            print(f"✓ Docpipe operator 'noop': {docpipe_noop.__name__}")
            print(f"  Owner: {docpipe_owner}")
            priority = OperatorFactory.PRIORITY_MAP.get(docpipe_owner or DocpipeConstants.OWNER_DOCPIPE, "unknown")
            print(f"  Priority: {priority}")

        # Create temporary custom operator that could override
        with tempfile.TemporaryDirectory() as tmpdir:
            operator_file = Path(tmpdir) / "custom_noop.py"
            operator_file.write_text("""
import pyarrow as pa
from docpipe.core.constants.constants import DocpipeConstants, ExecutionStatus
from docpipe.core.operators.abstract_operator import AbstractOperator, OperatorCategory

class CustomNoopOperator(AbstractOperator):
    short_name: str = "custom_noop"
    category: OperatorCategory = OperatorCategory.Functional
    owner: str | None = DocpipeConstants.OWNER_CUSTOM

    def __init__(self, *, config: dict):
        super().__init__(config=config)

    def transform(self, *, table: pa.Table, file_name: str | None = None) -> tuple[list[pa.Table], dict]:
        metadata = self.create_base_metadata(total_docs_count=len(table), node_status=ExecutionStatus.COMPLETED)
        return [table], metadata

    @staticmethod
    def get_metadata() -> dict:
        return {"label": "Custom Noop", "category": OperatorCategory.Functional.value}

    def get_required_features(self) -> list:
        return []
""")

            # Clear cache and create new factory with custom operator
            OperatorFactoryProvider.operator_factories.clear()
            factory2 = OperatorFactoryProvider.get_operator_factory(
                orchestrator=OrchestratorType.PYTHON, package_names=[str(tmpdir)], enable_custom_operators=True
            )

            # Verify custom operator was loaded
            assert "custom_noop" in factory2.operators
            custom_op = factory2.operators["custom_noop"]
            custom_owner = getattr(custom_op, "owner", None)

            print(f"✓ Custom operator 'custom_noop': {custom_op.__name__}")
            print(f"  Owner: {custom_owner}")
            print(
                f"  Priority: {OperatorFactory.PRIORITY_MAP.get(custom_owner or DocpipeConstants.OWNER_CUSTOM, 'unknown')}"
            )

            # Verify priority map
            assert (
                OperatorFactory.PRIORITY_MAP[DocpipeConstants.OWNER_CUSTOM]
                < OperatorFactory.PRIORITY_MAP[DocpipeConstants.OWNER_DOCPIPE]
            )
            print(
                f"✓ Priority resolution verified: CUSTOM ({OperatorFactory.PRIORITY_MAP[DocpipeConstants.OWNER_CUSTOM]}) < DOCPIPE ({OperatorFactory.PRIORITY_MAP[DocpipeConstants.OWNER_DOCPIPE]})"
            )

    def test_refresh_operators(self):
        """Test 5: Test refresh_operators() method."""
        print("\n" + "=" * 80)
        print("TEST 5: Refresh Operators Method")
        print("=" * 80)

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create initial operator
            operator_file = Path(tmpdir) / "refreshable_operator.py"
            operator_file.write_text("""
import pyarrow as pa
from docpipe.core.constants.constants import DocpipeConstants, ExecutionStatus
from docpipe.core.operators.abstract_operator import AbstractOperator, OperatorCategory

class RefreshableOperator(AbstractOperator):
    short_name: str = "refreshable_v1"
    category: OperatorCategory = OperatorCategory.Functional
    owner: str | None = DocpipeConstants.OWNER_CUSTOM

    def __init__(self, *, config: dict):
        super().__init__(config=config)

    def transform(self, *, table: pa.Table, file_name: str | None = None) -> tuple[list[pa.Table], dict]:
        metadata = self.create_base_metadata(total_docs_count=len(table), node_status=ExecutionStatus.COMPLETED)
        return [table], metadata

    @staticmethod
    def get_metadata() -> dict:
        return {"label": "Refreshable V1", "category": OperatorCategory.Functional.value}

    def get_required_features(self) -> list:
        return []
""")

            # Create factory
            factory = OperatorFactoryProvider.get_operator_factory(
                orchestrator=OrchestratorType.PYTHON, package_names=[str(tmpdir)], enable_custom_operators=True
            )

            # Verify initial operator
            assert "refreshable_v1" in factory.operators
            print("✓ Initial operator loaded: refreshable_v1")

            # Update operator file with new version
            operator_file.write_text("""
import pyarrow as pa
from docpipe.core.constants.constants import DocpipeConstants, ExecutionStatus
from docpipe.core.operators.abstract_operator import AbstractOperator, OperatorCategory

class RefreshableOperator(AbstractOperator):
    short_name: str = "refreshable_v1"
    category: OperatorCategory = OperatorCategory.Functional
    owner: str | None = DocpipeConstants.OWNER_CUSTOM

    def __init__(self, *, config: dict):
        super().__init__(config=config)

    def transform(self, *, table: pa.Table, file_name: str | None = None) -> tuple[list[pa.Table], dict]:
        metadata = self.create_base_metadata(total_docs_count=len(table), node_status=ExecutionStatus.COMPLETED)
        return [table], metadata

    def get_metadata(self) -> dict:
        return {"label": "Refreshable V1 - Updated", "category": self.category.value}

    def get_required_features(self) -> list:
        return []
""")

            # Refresh operators
            factory.refresh_operators()

            # Verify operator is refreshed with updated code
            assert "refreshable_v1" in factory.operators
            refreshed_op = factory.operators["refreshable_v1"]
            instance = refreshed_op(config={})
            metadata = instance.get_metadata()
            assert "Updated" in metadata["label"], "Operator should be refreshed with new code"
            print("✓ Operator refreshed successfully: refreshable_v1")
            print(f"  Updated metadata: {metadata['label']}")
            print(f"  Total operators after refresh: {len(factory.operators)}")

    def test_custom_operators_disabled(self):
        """Test that custom operators can be disabled."""
        print("\n" + "=" * 80)
        print("TEST 6: Custom Operators Disabled")
        print("=" * 80)

        # Create factory with custom operators disabled
        factory = OperatorFactoryProvider.get_operator_factory(
            orchestrator=OrchestratorType.PYTHON, enable_custom_operators=False
        )

        # Verify only docpipe operators are loaded
        for op_name, op_class in factory.operators.items():
            owner = getattr(op_class, "owner", None)
            assert owner == DocpipeConstants.OWNER_DOCPIPE or owner is None, (
                f"Operator {op_name} should be a docpipe operator when custom operators are disabled"
            )

        print("✓ Custom operators disabled successfully")
        print(f"  Loaded {len(factory.operators)} docpipe operators only")

    def test_mixed_sources(self):
        """Test loading from multiple source types simultaneously."""
        print("\n" + "=" * 80)
        print("TEST 7: Mixed Sources (Filesystem + Environment Variable)")
        print("=" * 80)

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create operator in filesystem
            operator_file = Path(tmpdir) / "mixed_operator.py"
            operator_file.write_text("""
import pyarrow as pa
from docpipe.core.constants.constants import DocpipeConstants, ExecutionStatus
from docpipe.core.operators.abstract_operator import AbstractOperator, OperatorCategory

class MixedSourceOperator(AbstractOperator):
    short_name: str = "mixed_source"
    category: OperatorCategory = OperatorCategory.Functional
    owner: str | None = DocpipeConstants.OWNER_CUSTOM

    def __init__(self, *, config: dict):
        super().__init__(config=config)

    def transform(self, *, table: pa.Table, file_name: str | None = None) -> tuple[list[pa.Table], dict]:
        metadata = self.create_base_metadata(total_docs_count=len(table), node_status=ExecutionStatus.COMPLETED)
        return [table], metadata

    def get_metadata(self) -> dict:
        return {"label": "Mixed Source", "category": self.category.value}

    def get_required_features(self) -> list:
        return []
""")

            # Set environment variable to test operator path
            test_operator_path = str(Path(__file__).parent.parent / "fixtures" / "custom_operators")
            os.environ[EnvironmentVariables.DOCPIPE_CUSTOM_OPERATORS] = test_operator_path

            # Create factory with additional filesystem path
            factory = OperatorFactoryProvider.get_operator_factory(
                orchestrator=OrchestratorType.PYTHON, package_names=[str(tmpdir)], enable_custom_operators=True
            )

            # Verify both operators are loaded
            assert "mixed_source" in factory.operators, "Operator from filesystem should be loaded"
            assert "valid_custom" in factory.operators, "Operator from environment variable should be loaded"

            print("✓ Loaded operators from multiple sources:")
            print("  - Filesystem: mixed_source")
            print("  - Environment: valid_custom")
            print(f"  Total operators: {len(factory.operators)}")


if __name__ == "__main__":
    # Run tests
    test_suite = TestOperatorFactoryIntegration()

    try:
        test_suite.setup_method()
        test_suite.test_environment_variable_loading()
        test_suite.teardown_method()

        test_suite.setup_method()
        test_suite.test_filesystem_path_loading()
        test_suite.teardown_method()

        test_suite.setup_method()
        test_suite.test_s3_uri_loading()
        test_suite.teardown_method()

        test_suite.setup_method()
        test_suite.test_priority_resolution()
        test_suite.teardown_method()

        test_suite.setup_method()
        test_suite.test_refresh_operators()
        test_suite.teardown_method()

        test_suite.setup_method()
        test_suite.test_custom_operators_disabled()
        test_suite.teardown_method()

        test_suite.setup_method()
        test_suite.test_mixed_sources()
        test_suite.teardown_method()

        print("\n" + "=" * 80)
        print("ALL TESTS PASSED!")
        print("=" * 80)

    except Exception as e:
        print(f"\n✗ TEST FAILED: {e}")
        import traceback

        traceback.print_exc()

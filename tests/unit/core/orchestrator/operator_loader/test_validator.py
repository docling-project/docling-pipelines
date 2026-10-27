"""Unit tests for OperatorValidator."""

import importlib.util
import sys
from pathlib import Path

import pytest

from docpipe.core.orchestration.operator_loader.ports.operator_source import OperatorInfo
from docpipe.core.orchestration.operator_loader.validator import OperatorValidator


class TestOperatorValidator:
    """Test OperatorValidator class."""

    @pytest.fixture
    def fixtures_path(self):
        """Return path to test fixtures."""
        return Path(__file__).parent.parent.parent.parent.parent / "fixtures" / "custom_operators"

    def load_module_from_file(self, file_path: Path):
        """Helper to load a module from a file path."""
        spec = importlib.util.spec_from_file_location("test_module", file_path)
        if spec is None or spec.loader is None:
            raise ImportError(f"Could not load module from {file_path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules["test_module"] = module
        spec.loader.exec_module(module)
        return module

    def test_validate_valid_operator(self, fixtures_path):
        """Test validation of a valid operator."""
        module_path = fixtures_path / "valid_operator.py"
        module = self.load_module_from_file(module_path)

        operator_info = OperatorInfo(
            name="ValidCustomOperator",
            short_name="valid_custom",
            module_path=str(module_path),
            category="Functional",
            source_location=str(module_path),
        )

        result = OperatorValidator.validate_module(module=module, operator_info=operator_info)

        assert result.valid is True
        assert len(result.errors) == 0

    def test_validate_operator_missing_transform(self, fixtures_path):
        """Test validation fails when transform method is missing."""
        module_path = fixtures_path / "invalid_operator_no_transform.py"
        module = self.load_module_from_file(module_path)

        operator_info = OperatorInfo(
            name="InvalidOperatorNoTransform",
            short_name="invalid_no_transform",
            module_path=str(module_path),
            category="Functional",
            source_location=str(module_path),
        )

        result = OperatorValidator.validate_module(module=module, operator_info=operator_info)

        assert result.valid is False
        assert any("transform" in error.lower() for error in result.errors)

    def test_validate_operator_missing_short_name(self, fixtures_path):
        """Test validation fails when short_name is missing."""
        module_path = fixtures_path / "invalid_operator_no_short_name.py"
        module = self.load_module_from_file(module_path)

        operator_info = OperatorInfo(
            name="InvalidOperatorNoShortName",
            short_name="invalid_no_short_name",
            module_path=str(module_path),
            category="Functional",
            source_location=str(module_path),
        )

        result = OperatorValidator.validate_module(module=module, operator_info=operator_info)

        assert result.valid is False
        assert any("short_name" in error.lower() for error in result.errors)

    def test_validate_not_an_operator(self, fixtures_path):
        """Test validation fails when class doesn't inherit from AbstractOperator."""
        module_path = fixtures_path / "not_an_operator.py"
        module = self.load_module_from_file(module_path)

        operator_info = OperatorInfo(
            name="NotAnOperator",
            short_name="not_an_operator",
            module_path=str(module_path),
            category="Functional",
            source_location=str(module_path),
        )

        result = OperatorValidator.validate_module(module=module, operator_info=operator_info)

        assert result.valid is False
        assert len(result.errors) > 0

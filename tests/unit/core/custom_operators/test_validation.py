"""Unit tests for AST static validation of custom operators."""

from pathlib import Path

import pytest

from docpipe.core.custom_operators.validation import validate_operator_file
from docpipe.exceptions.docpipe_exceptions import CustomOperatorInvalidDataException

EXAMPLES_DIR = Path(__file__).resolve().parents[4] / "examples" / "custom_operators"


class TestASTOperatorValidatorHappyPath:
    """Test suite for valid custom operator AST validation."""

    def test_validate_valid_operator_with_enum_category(self, *, tmp_path: Path) -> None:
        """Test validating a fully compliant custom operator with OperatorCategory enum."""
        code = """
from docpipe.core.operators.abstract_operator import AbstractOperator, OperatorCategory
import pyarrow as pa

class ValidCustomOp(AbstractOperator):
    short_name = "valid_custom_op"
    category = OperatorCategory.Quality
    owner = "custom"

    def transform(self, table: pa.Table):
        return [table], {}

    @staticmethod
    def get_metadata():
        return {"short_name": "valid_custom_op"}
"""
        op_file = tmp_path / "valid_op.py"
        op_file.write_text(code, encoding="utf-8")

        info = validate_operator_file(operator_file_path=op_file)
        assert info["short_name"] == "valid_custom_op"
        assert info["category"] == "Quality"
        assert info["class_name"] == "ValidCustomOp"

    def test_validate_valid_operator_with_string_category_and_owner_constant(self, *, tmp_path: Path) -> None:
        """Test category and owner specified as string literals."""
        code = """
from docpipe.core.operators.abstract_operator import AbstractOperator

class AnotherOp(AbstractOperator):
    short_name = "another_op"
    category = "Extract"
    owner = "custom"

    def transform(self, table):
        return [table], {}

    @staticmethod
    def get_metadata():
        return {}
"""
        op_file = tmp_path / "another_op.py"
        op_file.write_text(code, encoding="utf-8")

        info = validate_operator_file(operator_file_path=op_file)
        assert info["short_name"] == "another_op"
        assert info["category"] == "Extract"


class TestASTOperatorValidatorFailureCases:
    """Test suite for AST validation rejection rules."""

    def test_validate_syntax_error_raises_exception(self, *, tmp_path: Path) -> None:
        """Test reporting syntax error in operator file."""
        op_file = tmp_path / "syntax_err.py"
        op_file.write_text("def invalid syntax (", encoding="utf-8")

        with pytest.raises(CustomOperatorInvalidDataException, match="Syntax error"):
            validate_operator_file(operator_file_path=op_file)

    def test_validate_missing_file_raises_exception(self, *, tmp_path: Path) -> None:
        """Test validating non-existent file."""
        op_file = tmp_path / "non_existent.py"
        with pytest.raises(CustomOperatorInvalidDataException, match="Operator file does not exist"):
            validate_operator_file(operator_file_path=op_file)

    def test_validate_no_abstract_operator_subclass_raises_exception(self, *, tmp_path: Path) -> None:
        """Test rejection when no AbstractOperator subclass exists."""
        code = """
class RegularClass:
    short_name = "test"
"""
        op_file = tmp_path / "no_op.py"
        op_file.write_text(code, encoding="utf-8")

        with pytest.raises(CustomOperatorInvalidDataException, match="No class inheriting from AbstractOperator found"):
            validate_operator_file(operator_file_path=op_file)

    def test_validate_multiple_operator_classes_raises_exception(self, *, tmp_path: Path) -> None:
        """Test rejection when multiple AbstractOperator subclasses exist."""
        code = """
from docpipe.core.operators.abstract_operator import AbstractOperator

class Op1(AbstractOperator):
    short_name = "op1"
    category = "Extract"
    owner = "custom"
    def transform(self, table): pass
    @staticmethod
    def get_metadata(): pass

class Op2(AbstractOperator):
    short_name = "op2"
    category = "Extract"
    owner = "custom"
    def transform(self, table): pass
    @staticmethod
    def get_metadata(): pass
"""
        op_file = tmp_path / "multi_op.py"
        op_file.write_text(code, encoding="utf-8")

        with pytest.raises(CustomOperatorInvalidDataException, match="Multiple operator classes found"):
            validate_operator_file(operator_file_path=op_file)

    def test_validate_missing_short_name_raises_exception(self, *, tmp_path: Path) -> None:
        """Test rejection when short_name is missing."""
        code = """
from docpipe.core.operators.abstract_operator import AbstractOperator

class MissingShortName(AbstractOperator):
    category = "Extract"
    owner = "custom"
    def transform(self, table): pass
    @staticmethod
    def get_metadata(): pass
"""
        op_file = tmp_path / "missing_short_name.py"
        op_file.write_text(code, encoding="utf-8")

        with pytest.raises(CustomOperatorInvalidDataException, match="must define 'short_name'"):
            validate_operator_file(operator_file_path=op_file)

    def test_validate_non_literal_short_name_raises_exception(self, *, tmp_path: Path) -> None:
        """Test rejection when short_name is not a string literal."""
        code = """
from docpipe.core.operators.abstract_operator import AbstractOperator
NAME = "dynamic_name"

class DynamicShortName(AbstractOperator):
    short_name = NAME
    category = "Extract"
    owner = "custom"
    def transform(self, table): pass
    @staticmethod
    def get_metadata(): pass
"""
        op_file = tmp_path / "dynamic_short_name.py"
        op_file.write_text(code, encoding="utf-8")

        with pytest.raises(CustomOperatorInvalidDataException, match="short_name must be a string literal"):
            validate_operator_file(operator_file_path=op_file)

    def test_validate_owner_docpipe_raises_exception(self, *, tmp_path: Path) -> None:
        """Test rejection when custom operator attempts owner='docpipe'."""
        code = """
from docpipe.core.operators.abstract_operator import AbstractOperator

class FakeDocpipeOp(AbstractOperator):
    short_name = "fake_op"
    category = "Extract"
    owner = "docpipe"
    def transform(self, table): pass
    @staticmethod
    def get_metadata(): pass
"""
        op_file = tmp_path / "fake_docpipe.py"
        op_file.write_text(code, encoding="utf-8")

        with pytest.raises(CustomOperatorInvalidDataException, match="must set owner='custom'"):
            validate_operator_file(operator_file_path=op_file)

    def test_validate_missing_transform_raises_exception(self, *, tmp_path: Path) -> None:
        """Test rejection when transform method is missing."""
        code = """
from docpipe.core.operators.abstract_operator import AbstractOperator

class MissingTransform(AbstractOperator):
    short_name = "missing_transform"
    category = "Extract"
    owner = "custom"
    @staticmethod
    def get_metadata(): pass
"""
        op_file = tmp_path / "missing_transform.py"
        op_file.write_text(code, encoding="utf-8")

        with pytest.raises(CustomOperatorInvalidDataException, match="must implement 'transform' method"):
            validate_operator_file(operator_file_path=op_file)

    def test_validate_missing_get_metadata_static_raises_exception(self, *, tmp_path: Path) -> None:
        """Test rejection when get_metadata is not static."""
        code = """
from docpipe.core.operators.abstract_operator import AbstractOperator

class InstanceMetadata(AbstractOperator):
    short_name = "instance_metadata"
    category = "Extract"
    owner = "custom"
    def transform(self, table): pass
    def get_metadata(self): pass
"""
        op_file = tmp_path / "instance_metadata.py"
        op_file.write_text(code, encoding="utf-8")

        with pytest.raises(
            CustomOperatorInvalidDataException, match="must implement 'get_metadata' as a @staticmethod"
        ):
            validate_operator_file(operator_file_path=op_file)


def _write_operator(*, directory: Path, code: str, filename: str = "operator.py") -> Path:
    """Write operator source code to a file in directory and return its path."""
    op_file = directory / filename
    op_file.write_text(code, encoding="utf-8")
    return op_file


def _operator_source(*, short_name: str = '"probe_op"', category: str = '"Extract"', owner: str = '"custom"') -> str:
    """Return a minimal operator source whose class attributes are the given source expressions."""
    return f"""
from docpipe.core.constants.constants import DocpipeConstants
from docpipe.core.operators.abstract_operator import AbstractOperator, OperatorCategory

class ProbeOp(AbstractOperator):
    short_name = {short_name}
    category = {category}
    owner = {owner}
    def transform(self, table): pass
    @staticmethod
    def get_metadata(): pass
"""


class TestASTOperatorValidatorShippedExamples:
    """The example operators shipped in the repository satisfy the upload contract."""

    @pytest.mark.parametrize(
        ("example_file", "short_name", "class_name"),
        [
            ("hello_operator.py", "hello", "HelloOperator"),
            ("example_custom_operator.py", "example_custom", "ExampleCustomOperator"),
        ],
    )
    def test_validate_shipped_example_operator(self, *, example_file: str, short_name: str, class_name: str) -> None:
        """Annotated attributes, OperatorCategory members and DocpipeConstants.OWNER_CUSTOM are accepted."""
        example_path = EXAMPLES_DIR / example_file

        info = validate_operator_file(operator_file_path=example_path)

        assert info == {"short_name": short_name, "category": "Functional", "class_name": class_name}


class TestASTOperatorValidatorClassDetection:
    """Test suite for detecting the operator class and reading its body."""

    def test_validate_detects_module_qualified_base_and_ignores_other_classes(self, *, tmp_path: Path) -> None:
        """A base written as module.AbstractOperator is detected; classes with other bases are ignored."""
        code = '''
import abc
from docpipe.core.operators import abstract_operator

class Helper(object):
    short_name = 1

class Config(abc.ABC):
    category = 2

class QualifiedOp(abstract_operator.AbstractOperator):
    """Docstrings and other statements in the class body are ignored."""

    short_name: str = "qualified_op"
    category: str = "Quality"
    owner: str = "custom"
    version = "1.0"
    description: str
    registry.default: int = 3

    def transform(self, table):
        return [table], {}

    def get_required_features(self):
        return []

    @staticmethod
    def get_metadata():
        return {}
'''
        op_file = _write_operator(directory=tmp_path, code=code)

        info = validate_operator_file(operator_file_path=op_file)

        assert info == {"short_name": "qualified_op", "category": "Quality", "class_name": "QualifiedOp"}

    def test_validate_accepts_module_qualified_staticmethod_decorator(self, *, tmp_path: Path) -> None:
        """get_metadata decorated with builtins.staticmethod counts as a static method."""
        code = _operator_source().replace("@staticmethod", "@builtins.staticmethod")
        op_file = _write_operator(directory=tmp_path, code=code)

        info = validate_operator_file(operator_file_path=op_file)

        assert info["class_name"] == "ProbeOp"

    def test_validate_annotation_without_value_does_not_define_short_name(self, *, tmp_path: Path) -> None:
        """A bare annotation `short_name: str` does not count as a short_name definition."""
        code = _operator_source().replace('short_name = "probe_op"', "short_name: str")
        op_file = _write_operator(directory=tmp_path, code=code)

        with pytest.raises(CustomOperatorInvalidDataException, match="must define 'short_name'") as exc_info:
            validate_operator_file(operator_file_path=op_file)

        assert exc_info.value.field_name == "short_name"


class TestASTOperatorValidatorAttributeRules:
    """Test suite for the category and owner attribute rules."""

    @pytest.mark.parametrize("category", ["42", 'OperatorCategory("Quality")', "None"])
    def test_validate_non_literal_category_raises_exception(self, *, tmp_path: Path, category: str) -> None:
        """A category that is neither a string literal nor an attribute reference is rejected."""
        op_file = _write_operator(directory=tmp_path, code=_operator_source(category=category))

        with pytest.raises(
            CustomOperatorInvalidDataException, match="category must be a string literal or OperatorCategory enum"
        ) as exc_info:
            validate_operator_file(operator_file_path=op_file)

        assert exc_info.value.field_name == "category"

    def test_validate_missing_category_raises_exception(self, *, tmp_path: Path) -> None:
        """An operator class without a category attribute is rejected."""
        code = _operator_source().replace('    category = "Extract"\n', "")
        op_file = _write_operator(directory=tmp_path, code=code)

        with pytest.raises(CustomOperatorInvalidDataException, match="must define 'category'") as exc_info:
            validate_operator_file(operator_file_path=op_file)

        assert exc_info.value.field_name == "category"

    @pytest.mark.parametrize(
        ("category", "reported"),
        [('"Transform"', "Transform"), ('"quality"', "quality"), ("OperatorCategory.Enrichment", "Enrichment")],
    )
    def test_validate_unknown_category_raises_exception(self, *, tmp_path: Path, category: str, reported: str) -> None:
        """Categories outside OperatorCategory (case-sensitive) are rejected and the valid ones are listed."""
        op_file = _write_operator(directory=tmp_path, code=_operator_source(category=category))

        with pytest.raises(CustomOperatorInvalidDataException, match=f"Invalid category '{reported}'") as exc_info:
            validate_operator_file(operator_file_path=op_file)

        assert exc_info.value.field_name == "category"
        assert "Extract, Functional, Ingest, Quality, Storage, VectorDB" in str(exc_info.value)

    @pytest.mark.parametrize("owner", ["DocpipeConstants.OWNER_DOCPIPE", "100", "None"])
    def test_validate_non_custom_owner_expression_raises_exception(self, *, tmp_path: Path, owner: str) -> None:
        """An owner that is neither a string literal nor OWNER_CUSTOM is rejected while parsing the class."""
        op_file = _write_operator(directory=tmp_path, code=_operator_source(owner=owner))

        with pytest.raises(CustomOperatorInvalidDataException, match="owner must be 'custom'") as exc_info:
            validate_operator_file(operator_file_path=op_file)

        assert exc_info.value.field_name == "owner"


class TestASTOperatorValidatorUnreadableFile:
    """Test suite for files that cannot be decoded."""

    def test_validate_non_utf8_file_raises_exception(self, *, tmp_path: Path) -> None:
        """A file that is not valid UTF-8 is reported as unreadable instead of crashing."""
        op_file = tmp_path / "latin1_op.py"
        op_file.write_bytes(_operator_source(short_name='"caf' + chr(0xE9) + '"').encode("latin-1"))

        with pytest.raises(
            CustomOperatorInvalidDataException, match="Failed to read or parse operator file"
        ) as exc_info:
            validate_operator_file(operator_file_path=op_file)

        assert exc_info.value.field_name == "operator_file"
        assert isinstance(exc_info.value.__cause__, UnicodeDecodeError)

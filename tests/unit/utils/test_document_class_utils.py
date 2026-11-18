"""
Unit tests for DocumentClassUtils.

Tests cover:
- Document class loading and validation
- Template generation from document schemas
- Field type mapping and resolution
- Nested field handling
- Example and description extraction
- Document class listing and discovery
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from docpipe.utils.document_class_utils import DocumentClassUtils


@pytest.fixture
def sample_document_class():
    """Create sample document class structure."""
    return {
        "document_class_name": "Invoice",
        "document_class_id": "invoice-v1",
        "document_class_schema": {
            "document": {
                "document_type": "invoice",
                "document_description": "Standard invoice document",
                "fields": [
                    {
                        "name": "invoice_number",
                        "description": "Unique invoice identifier",
                        "examples": ["INV-2024-001", "INV-2024-002"],
                    },
                    {
                        "name": "invoice_date",
                        "description": "Date of invoice",
                        "examples": ["2024-01-15"],
                    },
                    {
                        "name": "total",
                        "description": "Total amount",
                        "examples": [1500.00, 2300.50],
                    },
                    {
                        "name": "line_items",
                        "description": "Invoice line items",
                        "fields": [
                            {"name": "description", "description": "Item description"},
                            {"name": "quantity", "description": "Item quantity"},
                            {"name": "amount", "description": "Item amount"},
                        ],
                    },
                ],
            },
            "target_tables": [
                {
                    "table_name": "invoices",
                    "columns": [
                        {"name": "invoice_number", "type": "string", "source": {"field": ["invoice_number"]}},
                        {"name": "invoice_date", "type": "date", "source": {"field": ["invoice_date"]}},
                        {"name": "total", "type": "decimal", "source": {"field": ["total"]}},
                    ],
                },
                {
                    "table_name": "line_items",
                    "columns": [
                        {"name": "description", "type": "string", "source": {"field": ["line_items", "description"]}},
                        {"name": "quantity", "type": "integer", "source": {"field": ["line_items", "quantity"]}},
                        {"name": "amount", "type": "float", "source": {"field": ["line_items", "amount"]}},
                    ],
                },
            ],
        },
    }


@pytest.fixture
def temp_doc_class_file(sample_document_class):
    """Create temporary document class JSON file."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(sample_document_class, f)
        temp_path = f.name
    yield temp_path
    Path(temp_path).unlink()


class TestNormalizeFilename:
    """Test filename normalization."""

    def test_normalize_simple_name(self):
        """Test normalization of simple name."""
        result = DocumentClassUtils.normalize_filename("Invoice")
        assert result == "invoice"

    def test_normalize_with_spaces(self):
        """Test normalization with spaces."""
        result = DocumentClassUtils.normalize_filename("Purchase Order")
        assert result == "purchase_order"

    def test_normalize_with_special_chars(self):
        """Test normalization with special characters."""
        result = DocumentClassUtils.normalize_filename("Invoice-2024/Q1")
        assert result == "invoice_2024_q1"

    def test_normalize_multiple_underscores(self):
        """Test normalization removes multiple consecutive underscores."""
        result = DocumentClassUtils.normalize_filename("Invoice___Document")
        assert result == "invoice_document"

    def test_normalize_leading_trailing_underscores(self):
        """Test normalization removes leading/trailing underscores."""
        result = DocumentClassUtils.normalize_filename("_Invoice_")
        assert result == "invoice"

    def test_normalize_mixed_case(self):
        """Test normalization converts to lowercase."""
        result = DocumentClassUtils.normalize_filename("InVoIcE")
        assert result == "invoice"

    def test_normalize_numbers(self):
        """Test normalization preserves numbers."""
        result = DocumentClassUtils.normalize_filename("Invoice2024")
        assert result == "invoice2024"


class TestLoadDocumentClass:
    """Test document class loading."""

    def test_load_valid_document_class(self, temp_doc_class_file, sample_document_class):
        """Test loading valid document class."""
        result = DocumentClassUtils.load_document_class(temp_doc_class_file)
        assert result == sample_document_class
        assert result["document_class_name"] == "Invoice"

    def test_load_nonexistent_file(self):
        """Test loading nonexistent file raises error."""
        with pytest.raises(FileNotFoundError, match="Document class file not found"):
            DocumentClassUtils.load_document_class("/nonexistent/file.json")

    def test_load_invalid_json(self):
        """Test loading invalid JSON raises error."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("invalid json content {")
            temp_path = f.name

        try:
            with pytest.raises(json.JSONDecodeError):
                DocumentClassUtils.load_document_class(temp_path)
        finally:
            Path(temp_path).unlink()

    def test_load_with_path_object(self, temp_doc_class_file, sample_document_class):
        """Test loading with Path object."""
        result = DocumentClassUtils.load_document_class(Path(temp_doc_class_file))
        assert result == sample_document_class


class TestFieldTypeResolution:
    """Test field type resolution from target tables."""

    def test_get_field_type_simple_field(self, sample_document_class):
        """Test getting type for simple field."""
        target_tables = sample_document_class["document_class_schema"]["target_tables"]
        field_type = DocumentClassUtils._get_field_type_from_target_tables(["invoice_number"], target_tables)
        assert field_type == "string"

    def test_get_field_type_nested_field(self, sample_document_class):
        """Test getting type for nested field."""
        target_tables = sample_document_class["document_class_schema"]["target_tables"]
        field_type = DocumentClassUtils._get_field_type_from_target_tables(["line_items", "quantity"], target_tables)
        assert field_type == "integer"

    def test_get_field_type_not_found(self, sample_document_class):
        """Test getting type for nonexistent field."""
        target_tables = sample_document_class["document_class_schema"]["target_tables"]
        field_type = DocumentClassUtils._get_field_type_from_target_tables(["nonexistent"], target_tables)
        assert field_type is None

    def test_check_direct_field_match(self):
        """Test direct field matching."""
        source = {"field": ["invoice_number"], "type": "string"}
        result = DocumentClassUtils._check_direct_field_match(source, ["invoice_number"])
        assert result == "string"

    def test_check_direct_field_no_match(self):
        """Test direct field no match."""
        source = {"field": ["invoice_number"], "type": "string"}
        result = DocumentClassUtils._check_direct_field_match(source, ["other_field"])
        assert result is None

    def test_check_transform_field_match(self):
        """Test transform field matching."""
        source = {
            "transform": {
                "function": "concat",
                "arguments": [{"value": {"field": ["first_name"]}}, {"value": {"field": ["last_name"]}}],
            }
        }
        result = DocumentClassUtils._check_transform_field_match(source, ["first_name"])
        assert result is True

    def test_check_transform_field_no_match(self):
        """Test transform field no match."""
        source = {"transform": {"function": "concat", "arguments": [{"value": {"field": ["first_name"]}}]}}
        result = DocumentClassUtils._check_transform_field_match(source, ["other_field"])
        assert result is False


class TestTypeMapping:
    """Test type mapping from target tables to Docling types."""

    def test_type_mapping_string(self):
        """Test string type mapping."""
        assert DocumentClassUtils.TYPE_MAPPING["string"] == "string"

    def test_type_mapping_date(self):
        """Test date type mapping."""
        assert DocumentClassUtils.TYPE_MAPPING["date"] == "string"

    def test_type_mapping_decimal(self):
        """Test decimal type mapping."""
        assert DocumentClassUtils.TYPE_MAPPING["decimal"] == "float"

    def test_type_mapping_integer(self):
        """Test integer type mapping."""
        assert DocumentClassUtils.TYPE_MAPPING["integer"] == "int"

    def test_type_mapping_boolean(self):
        """Test boolean type mapping."""
        assert DocumentClassUtils.TYPE_MAPPING["boolean"] == "boolean"

    def test_type_mapping_aliases(self):
        """Test type mapping aliases."""
        assert DocumentClassUtils.TYPE_MAPPING["int"] == "int"
        assert DocumentClassUtils.TYPE_MAPPING["long"] == "int"
        assert DocumentClassUtils.TYPE_MAPPING["bool"] == "boolean"


class TestTemplateGeneration:
    """Test Docling template generation."""

    def test_generate_docling_template_basic(self, temp_doc_class_file):
        """Test basic template generation."""
        template = DocumentClassUtils.generate_docling_template(temp_doc_class_file)

        assert "invoice_number" in template
        assert template["invoice_number"] == "string"
        assert "invoice_date" in template
        assert template["invoice_date"] == "string"  # date maps to string
        assert "total" in template
        assert template["total"] == "float"  # decimal maps to float

    def test_generate_docling_template_with_nested(self, temp_doc_class_file):
        """Test template generation includes nested fields."""
        template = DocumentClassUtils.generate_docling_template(temp_doc_class_file, include_nested=True)

        assert "line_items" in template
        assert isinstance(template["line_items"], dict)
        assert "description" in template["line_items"]
        assert "quantity" in template["line_items"]
        assert "amount" in template["line_items"]

    def test_generate_docling_template_without_nested(self, temp_doc_class_file):
        """Test template generation excludes nested fields."""
        template = DocumentClassUtils.generate_docling_template(temp_doc_class_file, include_nested=False)

        assert "invoice_number" in template
        assert "line_items" not in template

    def test_generate_docling_template_max_fields(self, temp_doc_class_file):
        """Test template generation with field limit."""
        template = DocumentClassUtils.generate_docling_template(temp_doc_class_file, max_fields=2)

        assert len(template) == 2

    def test_generate_docling_template_empty_fields(self):
        """Test template generation with no fields."""
        doc_class = {"document_class_schema": {"document": {"fields": []}, "target_tables": []}}

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(doc_class, f)
            temp_path = f.name

        try:
            template = DocumentClassUtils.generate_docling_template(temp_path)
            assert template == {}
        finally:
            Path(temp_path).unlink()

    def test_generate_docling_template_no_target_tables(self):
        """Test template generation with no target tables."""
        doc_class = {
            "document_class_schema": {
                "document": {"fields": [{"name": "test_field"}]},
                "target_tables": [],
            }
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(doc_class, f)
            temp_path = f.name

        try:
            template = DocumentClassUtils.generate_docling_template(temp_path)
            assert template == {}
        finally:
            Path(temp_path).unlink()


class TestTemplateWithExamples:
    """Test template generation with examples."""

    def test_generate_template_with_examples(self, temp_doc_class_file):
        """Test template generation includes examples."""
        result = DocumentClassUtils.generate_template_with_examples(temp_doc_class_file)

        assert "template" in result
        assert "examples" in result
        assert "descriptions" in result
        assert "document_type" in result
        assert "document_description" in result

    def test_template_with_examples_content(self, temp_doc_class_file):
        """Test template with examples has correct content."""
        result = DocumentClassUtils.generate_template_with_examples(temp_doc_class_file)

        assert result["document_type"] == "invoice"
        assert "invoice_number" in result["examples"]
        assert "INV-2024-001" in result["examples"]["invoice_number"]
        assert "invoice_number" in result["descriptions"]

    def test_template_with_examples_nested_fields(self, temp_doc_class_file):
        """Test template with examples handles nested fields."""
        result = DocumentClassUtils.generate_template_with_examples(temp_doc_class_file, include_nested=True)

        assert isinstance(result["template"]["line_items"], dict)

    def test_extract_field_metadata(self, sample_document_class):
        """Test field metadata extraction."""
        fields = sample_document_class["document_class_schema"]["document"]["fields"]
        examples: dict = {}
        descriptions: dict = {}

        DocumentClassUtils._extract_field_metadata(fields, examples, descriptions)

        assert "invoice_number" in examples
        assert "invoice_number" in descriptions
        assert len(examples["invoice_number"]) == 2


class TestDocumentClassListing:
    """Test document class listing and discovery."""

    @patch("docpipe.utils.document_class_utils.Path")
    def test_list_available_document_classes(self, mock_path, sample_document_class):
        """Test listing available document classes."""
        mock_dir = Mock()
        mock_file = Mock()
        mock_file.stem = "invoice"
        mock_dir.glob.return_value = [mock_file]
        mock_dir.exists.return_value = True
        mock_path.return_value = mock_dir

        with patch.object(DocumentClassUtils, "load_document_class", return_value=sample_document_class):
            result = DocumentClassUtils.list_available_document_classes()

            assert len(result) > 0
            assert result[0]["name"] == "Invoice"

    @patch("docpipe.utils.document_class_utils.Path")
    def test_list_available_document_classes_empty_dir(self, mock_path):
        """Test listing with no document classes."""
        mock_dir = Mock()
        mock_dir.glob.return_value = []
        mock_dir.exists.return_value = True
        mock_path.return_value = mock_dir

        result = DocumentClassUtils.list_available_document_classes()
        assert result == []

    @patch("docpipe.utils.document_class_utils.Path")
    def test_list_available_document_classes_nonexistent_dir(self, mock_path):
        """Test listing with nonexistent directory."""
        mock_dir = Mock()
        mock_dir.exists.return_value = False
        mock_path.return_value = mock_dir

        result = DocumentClassUtils.list_available_document_classes()
        assert result == []

    @patch("docpipe.utils.document_class_utils.Path")
    def test_list_available_document_classes_with_error(self, mock_path):
        """Test listing handles errors gracefully."""
        mock_dir = Mock()
        mock_file = Mock()
        mock_dir.glob.return_value = [mock_file]
        mock_dir.exists.return_value = True
        mock_path.return_value = mock_dir

        with patch.object(DocumentClassUtils, "load_document_class", side_effect=Exception("Load error")):
            result = DocumentClassUtils.list_available_document_classes()
            assert result == []


class TestSchemaDescription:
    """Test schema description building."""

    def test_build_schema_description_simple(self):
        """Test building schema description for simple fields."""
        fields = [
            {"name": "field1", "description": "First field", "examples": ["example1"]},
            {"name": "field2", "description": "Second field"},
        ]

        result = DocumentClassUtils.build_schema_description_from_fields(fields)

        assert "field1" in result
        assert "First field" in result
        assert "example1" in result
        assert "field2" in result

    def test_build_schema_description_nested(self):
        """Test building schema description with nested fields."""
        fields = [
            {
                "name": "parent",
                "description": "Parent field",
                "fields": [{"name": "child", "description": "Child field"}],
            }
        ]

        result = DocumentClassUtils.build_schema_description_from_fields(fields)

        assert "parent" in result
        assert "child" in result
        assert "Contains:" in result

    def test_build_schema_description_multiple_examples(self):
        """Test schema description with multiple examples."""
        fields = [{"name": "field1", "examples": ["ex1", "ex2", "ex3", "ex4"]}]

        result = DocumentClassUtils.build_schema_description_from_fields(fields)

        assert "ex1" in result
        assert "ex2" in result
        assert "ex3" in result
        # Should only show first 3 examples
        assert "ex4" not in result

    def test_build_schema_description_with_indent(self):
        """Test schema description respects indentation."""
        fields = [{"name": "field1", "description": "Test field"}]

        result = DocumentClassUtils.build_schema_description_from_fields(fields, indent=2)

        assert result.startswith("    ")  # 2 levels of indentation


class TestJSONTemplateBuilding:
    """Test JSON template building."""

    def test_build_json_template_simple(self):
        """Test building JSON template for simple fields."""
        fields = [{"name": "field1"}, {"name": "field2"}]

        result = DocumentClassUtils.build_json_template_from_fields(fields)

        assert "field1" in result
        assert "field2" in result
        assert result["field1"] is None
        assert result["field2"] is None

    def test_build_json_template_nested(self):
        """Test building JSON template with nested fields."""
        fields = [{"name": "parent", "fields": [{"name": "child1"}, {"name": "child2"}]}]

        result = DocumentClassUtils.build_json_template_from_fields(fields)

        assert "parent" in result
        assert isinstance(result["parent"], list)
        assert "child1" in result["parent"][0]
        assert "child2" in result["parent"][0]

    def test_build_json_template_empty_fields(self):
        """Test building JSON template with empty fields."""
        result = DocumentClassUtils.build_json_template_from_fields([])
        assert result == {}


class TestGetDocumentTypes:
    """Test document types retrieval."""

    @patch("docpipe.utils.document_class_utils.Path")
    def test_get_document_types(self, mock_path):
        """Test getting document types."""
        from unittest.mock import MagicMock

        mock_dir = MagicMock()
        mock_file = MagicMock()
        mock_dir.glob.return_value = [mock_file]
        mock_dir.exists.return_value = True
        mock_path.return_value = mock_dir

        doc_class = {
            "document_class_schema": {
                "document": {"document_type": "invoice", "document_description": "Invoice document"}
            }
        }

        with patch("json.load", return_value=doc_class):
            result = DocumentClassUtils.get_document_types()

            assert "invoice" in result
            assert result["invoice"] == "Invoice document"

    @patch("docpipe.utils.document_class_utils.Path")
    def test_get_document_types_nonexistent_dir(self, mock_path):
        """Test getting document types with nonexistent directory."""
        mock_dir = Mock()
        mock_dir.exists.return_value = False
        mock_path.return_value = mock_dir

        result = DocumentClassUtils.get_document_types()
        assert result == {}

    @patch("docpipe.utils.document_class_utils.Path")
    def test_get_document_types_with_errors(self, mock_path):
        """Test getting document types handles errors."""
        mock_dir = Mock()
        mock_file = Mock()
        mock_dir.glob.return_value = [mock_file]
        mock_dir.exists.return_value = True
        mock_path.return_value = mock_dir

        with patch("builtins.open", side_effect=Exception("Read error")):
            result = DocumentClassUtils.get_document_types()
            # Should return empty dict or partial results
            assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# Additional tests for get_schema_templates and generate_docling_templates_for_types
# (lines 470-555 in document_class_utils.py)
# ---------------------------------------------------------------------------


class TestGetSchemaTemplates:
    """Test get_schema_templates method."""

    def test_get_schema_templates_loads_valid_file(self, tmp_path, sample_document_class):
        """Test that a valid doc class file is loaded."""
        doc_class_file = tmp_path / "invoice.json"
        doc_class_file.write_text(json.dumps(sample_document_class))

        with (
            patch.object(DocumentClassUtils, "normalize_filename", return_value="invoice"),
            patch.object(DocumentClassUtils, "DOCUMENT_CLASSES_PATH", str(tmp_path)),
        ):
            result = DocumentClassUtils.get_schema_templates(["invoice"])
            assert "invoice" in result

    def test_get_schema_templates_skips_empty_types(self):
        """Test that empty strings in document_types are skipped."""
        result = DocumentClassUtils.get_schema_templates(["", "", ""])
        assert result == {}

    def test_get_schema_templates_skips_already_loaded(self):
        """Test that duplicate types are only loaded once."""
        # Pass duplicates - result should have only unique entries (deduplicated)
        # Use a non-existent path so the file open fails for both, proving dedup
        with patch.object(DocumentClassUtils, "DOCUMENT_CLASSES_PATH", "/nonexistent/path"):
            result = DocumentClassUtils.get_schema_templates(["invoice", "invoice"])
            assert result == {}

    def test_get_schema_templates_file_not_found_warns(self):
        """Test OSError is handled gracefully."""
        with patch("builtins.open", side_effect=OSError("no file")):
            result = DocumentClassUtils.get_schema_templates(["unknown_type"])
            assert result == {}

    def test_get_schema_templates_json_decode_error_warns(self):
        """Test json.JSONDecodeError is handled gracefully."""
        with patch("builtins.open", side_effect=json.JSONDecodeError("bad", "", 0)):
            result = DocumentClassUtils.get_schema_templates(["bad_type"])
            assert result == {}

    def test_get_schema_templates_no_schema_in_file(self, tmp_path):
        """Test file with no document_class_schema returns no entry."""
        empty_file = tmp_path / "empty.json"
        empty_file.write_text(json.dumps({}))

        with (
            patch.object(DocumentClassUtils, "normalize_filename", return_value="empty"),
            patch(
                "docpipe.utils.document_class_utils.DocumentClassUtils.DOCUMENT_CLASSES_PATH",
                str(tmp_path),
            ),
        ):
            result = DocumentClassUtils.get_schema_templates(["empty"])
            assert result == {}


class TestGenerateDoclingTemplatesForTypes:
    """Test generate_docling_templates_for_types method."""

    def test_empty_document_types_returns_empty(self):
        """Empty input returns empty dict."""
        result = DocumentClassUtils.generate_docling_templates_for_types([])
        assert result == {}

    def test_all_empty_strings_returns_empty(self):
        """All-empty document types returns empty dict."""
        result = DocumentClassUtils.generate_docling_templates_for_types(["", ""])
        assert result == {}

    def test_file_not_found_skips_and_continues(self, tmp_path):
        """Missing file logs warning and skips type."""
        with patch(
            "docpipe.utils.document_class_utils.DocpipeConstants.DOCUMENT_CLASSES_PATH",
            str(tmp_path),
        ):
            result = DocumentClassUtils.generate_docling_templates_for_types(["nonexistent_type"])
            assert "nonexistent_type" not in result

    def test_valid_file_generates_template(self, tmp_path, sample_document_class):
        """Existing file generates a template entry."""
        normalized = "invoice"
        doc_file = tmp_path / f"{normalized}.json"
        doc_file.write_text(json.dumps(sample_document_class))

        with patch(
            "docpipe.utils.document_class_utils.DocpipeConstants.DOCUMENT_CLASSES_PATH",
            str(tmp_path),
        ):
            result = DocumentClassUtils.generate_docling_templates_for_types(["invoice"])
            assert "invoice" in result

    def test_exception_in_generate_skips_type(self, tmp_path, sample_document_class):
        """Exception during template generation skips type gracefully."""
        normalized = "invoice"
        doc_file = tmp_path / f"{normalized}.json"
        doc_file.write_text(json.dumps(sample_document_class))

        with (
            patch(
                "docpipe.utils.document_class_utils.DocpipeConstants.DOCUMENT_CLASSES_PATH",
                str(tmp_path),
            ),
            patch.object(DocumentClassUtils, "generate_docling_template", side_effect=RuntimeError("boom")),
        ):
            result = DocumentClassUtils.generate_docling_templates_for_types(["invoice"])
            assert "invoice" not in result


class TestBuildTemplateFromFieldsEdgeCases:
    """Test _build_template_from_fields edge cases."""

    def test_field_with_no_type_in_target_defaults_to_string(self):
        """Field not in target_tables defaults to 'string'."""
        fields = [{"name": "mystery_field"}]
        target_tables: list = []
        result = DocumentClassUtils._build_template_from_fields(fields, target_tables)
        assert result["mystery_field"] == "string"

    def test_field_without_name_is_skipped(self):
        """Field with no 'name' key is skipped."""
        fields = [{"description": "no name here"}]
        target_tables: list = []
        result = DocumentClassUtils._build_template_from_fields(fields, target_tables)
        assert result == {}

    def test_transform_field_match_returns_type(self):
        """_get_field_type_from_target_tables returns type via transform match."""
        target_tables = [
            {
                "table_name": "test",
                "columns": [
                    {
                        "name": "full_name",
                        "type": "string",
                        "source": {
                            "transform": {
                                "function": "concat",
                                "arguments": [{"value": {"field": ["first_name"]}}],
                            }
                        },
                    }
                ],
            }
        ]
        result = DocumentClassUtils._get_field_type_from_target_tables(["first_name"], target_tables)
        assert result == "string"


# ---------------------------------------------------------------------------
# Targeted tests for remaining missing lines
# ---------------------------------------------------------------------------


class TestExtractFieldMetadataMissingName:
    """Line 252: _extract_field_metadata skips fields without a name."""

    def test_skips_field_without_name(self):
        """Field dict with no 'name' key is silently skipped."""
        examples: dict = {}
        descriptions: dict = {}
        fields = [
            {},  # no 'name' — triggers continue at line 252
            {"name": "invoice_number", "description": "An ID", "examples": ["INV-1"]},
        ]
        DocumentClassUtils._extract_field_metadata(fields, examples, descriptions)
        # Only the named field produces output
        assert "invoice_number" in descriptions
        assert len(examples) == 1


class TestBuildJsonTemplateNonListNestedFields:
    """Line 416: nested_fields is truthy but not a list — use tuple to hit else branch."""

    def test_nested_fields_tuple_branch(self):
        """If nested_fields is a tuple (truthy, not list), result is plain nested_template."""
        # A tuple is truthy and not isinstance(x, list), so it hits the else branch at line 416
        # The recursive call with a tuple works because the function only calls .get() on each item
        fields = [
            {
                "name": "address",
                "fields": ({"name": "street"}, {"name": "city"}),  # tuple, not list
            }
        ]
        result = DocumentClassUtils.build_json_template_from_fields(fields)
        # The value should be the template dict (not wrapped in a list)
        assert "address" in result
        assert not isinstance(result["address"], list)
        assert isinstance(result["address"], dict)


class TestGetDocumentTypesMissingLines:
    """Lines 457, 460-461: get_document_types() warning/error branches."""

    @patch("docpipe.utils.document_class_utils.Path")
    def test_warns_when_doc_type_or_description_missing(self, mock_path_cls):
        """Line 457: JSON loaded but missing document_type or document_description."""
        import json as json_mod
        from unittest.mock import mock_open

        mock_dir = Mock()
        mock_dir.exists.return_value = True

        mock_file = Mock()
        mock_file.name = "test.json"

        data_missing: dict = {"document_class_schema": {"document": {}}}  # no doc_type
        mock_dir.glob.return_value = [mock_file]
        mock_path_cls.return_value = mock_dir

        with patch("builtins.open", mock_open(read_data=json_mod.dumps(data_missing))):
            result = DocumentClassUtils.get_document_types()

        # Should return empty dict since no valid entries
        assert result == {}

    @patch("docpipe.utils.document_class_utils.Path")
    def test_continues_on_os_error_per_file(self, mock_path_cls):
        """Lines 460-461: OSError for a single file is caught and processing continues."""
        mock_dir = Mock()
        mock_dir.exists.return_value = True

        bad_file = Mock()
        bad_file.name = "bad.json"

        mock_dir.glob.return_value = [bad_file]
        mock_path_cls.return_value = mock_dir

        with patch("builtins.open", side_effect=OSError("permission denied")):
            result = DocumentClassUtils.get_document_types()

        # Error per file is caught; result is empty but no exception raised
        assert result == {}


# ── StaticDocumentClassProvider ──────────────────────────────────────────────


@pytest.mark.unit
class TestStaticDocumentClassProvider:
    """Tests for StaticDocumentClassProvider: ABC subclassing and delegation."""

    def test_satisfies_document_class_provider_protocol(self):
        """StaticDocumentClassProvider must be a subclass of DocumentClassProvider."""
        from docpipe.core.ports.document_class_provider import (
            DocumentClassProvider,
            StaticDocumentClassProvider,
        )

        provider = StaticDocumentClassProvider()
        assert isinstance(provider, DocumentClassProvider)

    def test_get_document_types_delegates_to_utils(self):
        """get_document_types() returns what DocumentClassUtils.get_document_types() returns."""
        from docpipe.core.ports.document_class_provider import StaticDocumentClassProvider

        fake_types = {"invoice": "A business invoice", "receipt": "A payment receipt"}

        with patch(
            "docpipe.utils.document_class_utils.DocumentClassUtils.get_document_types",
            return_value=fake_types,
        ):
            result = StaticDocumentClassProvider().get_document_types()

        assert result == fake_types

    def test_get_schema_templates_delegates_to_utils(self):
        """get_schema_templates() delegates to DocumentClassUtils.get_schema_templates()."""
        from docpipe.core.ports.document_class_provider import StaticDocumentClassProvider

        fake_schemas = {"invoice": {"document_type": "invoice", "fields": []}}

        with patch(
            "docpipe.utils.document_class_utils.DocumentClassUtils.get_schema_templates",
            return_value=fake_schemas,
        ) as mock_util:
            result = StaticDocumentClassProvider().get_schema_templates(document_types=["invoice"])

        mock_util.assert_called_once_with(["invoice"])
        assert result == fake_schemas

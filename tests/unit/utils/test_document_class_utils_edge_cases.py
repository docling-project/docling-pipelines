# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Edge-case tests for docpipe.utils.document_class_utils.DocumentClassUtils."""

import json
from typing import Any
from unittest.mock import patch

from docpipe.utils.document_class_utils import DocumentClassUtils


class TestTransformFieldMatch:
    """Tests for _check_transform_field_match argument scanning."""

    def test_non_matching_arguments_are_skipped_until_a_match(self):
        """Arguments without a field reference or with another field are ignored."""
        source = {
            "transform": {
                "arguments": [
                    {"value": {"literal": "x"}},
                    {"value": {"field": ["other"]}},
                    {"value": {"field": ["wanted"]}},
                ]
            }
        }
        assert DocumentClassUtils._check_transform_field_match(source, ["wanted"]) is True

    def test_no_argument_matches(self):
        """Without a matching argument the check returns False."""
        source = {"transform": {"arguments": [{"value": {"field": ["other"]}}, {"constant": 1}]}}
        assert DocumentClassUtils._check_transform_field_match(source, ["wanted"]) is False


class TestBuildTemplateFromFields:
    """Tests for _build_template_from_fields nested handling."""

    def test_nested_field_without_named_children_is_dropped(self):
        """A nested field whose children produce no template entries is omitted."""
        fields: list[dict[str, Any]] = [
            {"name": "total"},
            {"name": "line_items", "fields": [{"description": "unnamed child"}]},
        ]
        target_tables = [{"columns": [{"type": "decimal", "source": {"field": ["total"]}}]}]

        template = DocumentClassUtils._build_template_from_fields(fields=fields, target_tables=target_tables)

        assert template == {"total": "float"}


class TestExtractFieldMetadata:
    """Tests for _extract_field_metadata."""

    def test_examples_without_description(self):
        """Fields with examples but no description only populate the examples mapping."""
        examples: dict[str, list] = {}
        descriptions: dict[str, str] = {}
        fields: list[dict[str, Any]] = [
            {"name": "invoice_number", "examples": ["INV-1"]},
            {"name": "vendor", "fields": [{"name": "name", "examples": ["ACME"], "description": "Vendor name"}]},
        ]

        DocumentClassUtils._extract_field_metadata(fields, examples, descriptions)

        assert examples == {"invoice_number": ["INV-1"], "vendor.name": ["ACME"]}
        assert descriptions == {"vendor.name": "Vendor name"}


class TestBuildJsonTemplateFromFields:
    """Tests for build_json_template_from_fields option hints."""

    def test_available_options_become_hint_string(self):
        """Leaf fields with available_options get an inline hint listing the allowed values."""
        fields: list[dict[str, Any]] = [
            {"name": "currency", "available_options": ["EUR", "USD", 1]},
            {"name": "notes"},
        ]
        assert DocumentClassUtils.build_json_template_from_fields(fields) == {
            "currency": "<one of: EUR, USD, 1>",
            "notes": None,
        }


class TestGetDocumentTypes:
    """Tests for get_document_types file filtering."""

    @staticmethod
    def _write(path, document):
        """Write a document class JSON file with the given document section."""
        path.write_text(json.dumps({"document_class_schema": {"document": document}}), encoding="utf-8")

    def test_incomplete_and_invalid_files_are_skipped(self, tmp_path):
        """Files missing type/description or holding invalid JSON are skipped; valid ones load."""
        self._write(tmp_path / "invoice.json", {"document_type": "invoice", "document_description": "An invoice"})
        self._write(tmp_path / "no_description.json", {"document_type": "receipt"})
        (tmp_path / "broken.json").write_text("{not json", encoding="utf-8")

        with patch.object(DocumentClassUtils, "DOCUMENT_CLASSES_PATH", str(tmp_path)):
            assert DocumentClassUtils.get_document_types() == {"invoice": "An invoice"}

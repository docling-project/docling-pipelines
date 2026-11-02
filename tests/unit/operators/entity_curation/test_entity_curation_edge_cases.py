"""Entity curation edge cases: schema loading, array and single tables, transforms and the operator.

Schemas are real document class JSON files in a temporary DOCUMENT_CLASSES_PATH; the transforms
run for real (Babel, datefinder).
"""

import json
import sys
from pathlib import Path
from typing import Any

import pyarrow as pa
import pytest

from docpipe.core.constants.constants import DocpipeConstants, ExecutionStatus, Metrics
from docpipe.core.operators.functional.entity_curation.entity_curation_operator import EntityCurationOperator
from docpipe.core.operators.functional.entity_curation.schema_processor import SchemaProcessor
from docpipe.core.operators.functional.entity_curation.transforms import (
    currency_to_numeric,
    make_date_uniform,
    weight_to_numeric,
)


def _field(*path: str) -> dict[str, Any]:
    return {"field": list(path)}


def _transform(name: str, **arguments: Any) -> dict[str, Any]:
    return {"transform": {"transform_name": name, "arguments": [{"name": k, "value": v} for k, v in arguments.items()]}}


def _schema(*tables: tuple[str, list[dict[str, Any]]]) -> dict[str, Any]:
    return {"target_tables": [{"name": name, "columns": columns} for name, columns in tables]}


@pytest.fixture
def classes_dir(tmp_path: Path, monkeypatch) -> Path:
    """An empty DOCUMENT_CLASSES_PATH for this test."""
    monkeypatch.setattr(DocpipeConstants, "DOCUMENT_CLASSES_PATH", str(tmp_path))
    return tmp_path


def _write_class(directory: Path, name: str, content: str | dict[str, Any]) -> None:
    text = content if isinstance(content, str) else json.dumps(content)
    (directory / f"{name}.json").write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# Transforms
# ---------------------------------------------------------------------------


class TestMakeDateUniform:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("   ", None),
            ("2024/1/5", "2024-01-05"),
            ("15/01/2024", "2024-01-15"),
            ("01/02/2024", "2024-01-02"),
            ("20240115", "2024-01-15"),
            ("due on 2024-01-15 at noon", "2024-01-15"),
            ("no date here", None),
        ],
        ids=["blank", "year-first", "day-first", "month-first", "compact", "datefinder", "unparseable"],
    )
    def test_formats(self, value, expected):
        assert make_date_uniform(date_str=value) == expected

    def test_without_datefinder_only_the_fixed_formats_are_parsed(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "datefinder", None)

        assert make_date_uniform(date_str="due on 2024-01-15 at noon") is None
        assert make_date_uniform(date_str="2024/01/15") == "2024-01-15"


def test_currency_to_numeric_requires_babel(monkeypatch):
    monkeypatch.setitem(sys.modules, "babel.core", None)

    with pytest.raises(ImportError, match="The 'Babel' library is required for currency parsing"):
        currency_to_numeric(amount="$10")


@pytest.mark.parametrize("value", ["5 lb", "5 LB"])
def test_weight_units_are_matched_case_insensitively(value):
    assert weight_to_numeric(weight=value) == pytest.approx(2.26796)


def test_weight_unit_matching_only_through_case_folding_is_not_converted():
    """The long s (U+017F) is a case variant of "s", so the pattern matches it, but no unit is spelled that way."""
    assert weight_to_numeric(weight="5 lb\u017f") is None


# ---------------------------------------------------------------------------
# SchemaProcessor
# ---------------------------------------------------------------------------


class TestLoadSchemas:
    def test_loads_valid_schemas_and_skips_broken_files(self, classes_dir):
        _write_class(classes_dir, "invoice", {"document_class_schema": _schema(("inv", []))})
        _write_class(classes_dir, "no_schema", {"name": "no_schema"})
        _write_class(classes_dir, "broken", "{not json")
        processor = SchemaProcessor()

        processor.load_schemas(document_types=["Invoice", "no schema", "broken", "missing", ""])

        assert list(processor.schema_cache) == ["Invoice"]

    def test_cached_schemas_are_not_read_again(self, classes_dir):
        _write_class(classes_dir, "invoice", {"document_class_schema": _schema(("first", []))})
        processor = SchemaProcessor()
        processor.load_schemas(document_types=["invoice"])
        _write_class(classes_dir, "invoice", {"document_class_schema": _schema(("second", []))})

        processor.load_schemas(document_types=["invoice"])

        assert processor.schema_cache["invoice"]["target_tables"][0]["name"] == "first"


def _process(schema: dict[str, Any], entities: dict[str, Any]) -> dict[str, Any]:
    processor = SchemaProcessor()
    processor.schema_cache["doc"] = schema
    return processor.process_with_schema(entities=entities, document_type="doc")


class TestProcessWithSchema:
    def test_schema_without_target_tables(self):
        assert _process({"target_tables": []}, {"a": 1}) == {}

    def test_single_table_columns(self):
        schema = _schema(
            (
                "invoice",
                [
                    {"name": "number", "source": _field("invoice", "number")},
                    {"name": "total", "source": _transform("to_number", number_str=_field("total"))},
                    {"name": "broken", "source": _transform("currency_to_numeric", amount="$1", locale="xx_INVALID")},
                    {"name": "no_source", "source": {}},
                    {"source": _field("invoice", "number")},
                ],
            )
        )

        result = _process(schema, {"invoice": {"number": "A-1"}, "total": "1.5k"})

        assert result == {"invoice": {"number": "A-1", "total": 1500.0, "broken": None}}

    def test_empty_field_path_selects_the_whole_entities_object(self):
        entities = {"invoice": {"number": "A-1"}}

        assert _process(_schema(("raw", [{"name": "all", "source": _field()}])), entities) == {"raw": {"all": entities}}

    def test_array_table_columns(self):
        schema = _schema(
            (
                "line_items",
                [
                    {"name": "amount", "source": _field("items", "amount")},
                    {"name": "invoice", "source": _field("invoice_number")},
                    {"name": "weight_kg", "source": _transform("weight_to_numeric", weight=_field("items", "weight"))},
                    {"name": "currency", "source": _transform("currency_to_numeric", amount=_field("currency"))},
                    {"name": "label", "source": _transform("to_number", number_str="2k")},
                    {"name": "unknown", "source": _transform("no_such_transform", value=_field("items", "amount"))},
                    {"name": "failing", "source": _transform("currency_to_numeric", amount="$1", locale="xx")},
                    {
                        "name": "bad_argument",
                        "source": {
                            "transform": {
                                "transform_name": "to_number",
                                "arguments": [{"name": 7, "value": "1"}, {"name": "number_str", "value": "3"}],
                            }
                        },
                    },
                    {"name": "no_source", "source": {}},
                    {"source": _field("items", "amount")},
                ],
            )
        )
        entities = {
            "invoice_number": "INV-7",
            "currency": "$2",
            "items": [{"amount": 10, "weight": "2 kg"}, {"amount": 20, "weight": "500 g"}],
        }

        result = _process(schema, entities)

        common = {
            "invoice": "INV-7",
            "currency": "2",
            "label": 2000.0,
            "unknown": None,
            "failing": None,
            "bad_argument": 3.0,
        }
        assert result == {
            "line_items": [
                {"amount": 10, "weight_kg": 2.0, **common},
                {"amount": 20, "weight_kg": 0.5, **common},
            ]
        }

    def test_columns_referencing_two_arrays_fall_back_to_a_single_table(self):
        schema = _schema(
            (
                "mixed",
                [
                    {"name": "items", "source": _field("items")},
                    {"name": "tax_total", "source": _transform("to_number", number_str=_field("taxes", "0"))},
                ],
            )
        )

        result = _process(schema, {"items": [1, 2], "taxes": ["5"]})

        assert result == {"mixed": {"items": [1, 2], "tax_total": None}}


# ---------------------------------------------------------------------------
# EntityCurationOperator
# ---------------------------------------------------------------------------


class TestEntityCurationOperator:
    @staticmethod
    def _invoice_class(classes_dir: Path) -> None:
        schema = _schema(("invoice", [{"name": "number", "source": _field("number")}]))
        _write_class(classes_dir, "invoice", {"document_class_schema": schema})

    @pytest.mark.parametrize(("validating_flow", "error_count"), [(True, 0), (False, 2)], ids=["deferred", "checked"])
    def test_column_checks_are_deferred_while_validating_the_flow(self, validating_flow, error_count):
        config = {"validating_flow": validating_flow, "entities_column": "llm_entities", "document_type_column": "kind"}
        errors: list[str] = []

        EntityCurationOperator(config).validate(errors, [], available_features=["entities"])

        assert len(errors) == error_count

    def test_documents_without_type_entities_or_valid_json(self, classes_dir):
        self._invoice_class(classes_dir)
        table = pa.table(
            {
                "id": ["a", "b", "c", "d"],
                "name": ["A", "B", "C", "D"],
                "entities": [json.dumps({"number": "1"}), "", "{broken", json.dumps({"number": "4"})],
                "document_type": ["invoice", "invoice", "invoice", None],
            }
        )

        tables, metadata = EntityCurationOperator({}).transform(table)

        assert [json.loads(v) for v in tables[0].column("transformed_entities").to_pylist()] == [
            {"invoice": {"number": "1"}},
            {},
            {},
            {},
        ]
        assert [d["id"] for d in metadata[Metrics.External.SKIPPED_DOCS]] == ["b"]
        assert [d["id"] for d in metadata[Metrics.External.FAILED_DOCS]] == ["c"]
        assert metadata[Metrics.External.PROCESSED_DOCS] == 2
        assert metadata[Metrics.External.NODE_STATUS] == ExecutionStatus.COMPLETED_WITH_ERRORS

    @pytest.mark.parametrize(
        "document_type",
        [None, pa.array([None], pa.string())],
        ids=["no-column", "all-empty"],
    )
    def test_without_document_types_no_schemas_are_loaded(self, classes_dir, document_type):
        self._invoice_class(classes_dir)
        columns: dict[str, Any] = {"id": ["a"], "entities": [{"number": "1"}]}
        if document_type is not None:
            columns["document_type"] = document_type
        operator = EntityCurationOperator({})

        tables, metadata = operator.transform(pa.table(columns))

        assert operator.schema_processor.schema_cache == {}
        assert tables[0].column("transformed_entities").to_pylist() == ["{}"]
        assert metadata[Metrics.External.NODE_STATUS] == ExecutionStatus.COMPLETED

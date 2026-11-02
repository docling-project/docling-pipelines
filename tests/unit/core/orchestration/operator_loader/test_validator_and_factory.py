"""Unit tests for OperatorValidator rules and the OperatorSourceFactory registry."""

import types
from abc import ABC, abstractmethod
from dataclasses import replace
from typing import Any

import pyarrow as pa
import pytest

from docpipe.core.operators.abstract_operator import AbstractOperator, OperatorCategory
from docpipe.core.orchestration.operator_loader.adapters.factories.operator_source_factory import (
    OperatorSourceFactory,
    register_operator_source,
)
from docpipe.core.orchestration.operator_loader.ports.operator_source import OperatorInfo
from docpipe.core.orchestration.operator_loader.validator import OperatorValidator
from docpipe.exceptions.docpipe_exceptions import DocpipeException

_INFO = OperatorInfo(
    name="SampleOp", short_name="sample_op", module_path="sample.py", category="Functional", source_location="test"
)


class _ValidOp(AbstractOperator):
    """A custom operator that satisfies every rule."""

    short_name: str = "valid_op"
    category: OperatorCategory = OperatorCategory.Functional
    owner: str = "custom"

    def transform(self, table: pa.Table, file_name: str | None = None):
        return [table], {}


def _errors(cls: Any) -> list[str]:
    return OperatorValidator.validate_operator_class(cls=cls, operator_info=_INFO).errors


class TestValidateOperatorClass:
    """One rule per test, each with a class that breaks exactly that rule."""

    def test_valid_operator_passes(self) -> None:
        result = OperatorValidator.validate_operator_class(cls=_ValidOp, operator_info=_INFO)

        assert (result.valid, result.errors, result.warnings) == (True, [], [])

    def test_non_class_is_rejected(self) -> None:
        result = OperatorValidator.validate_operator_class(cls=lambda: None, operator_info=_INFO)  # type: ignore[arg-type]

        assert (result.valid, result.errors) == (False, ["SampleOp is not a class"])

    def test_plain_class_reports_every_missing_part(self) -> None:
        class NotAnOperator:
            pass

        assert _errors(NotAnOperator) == [
            "NotAnOperator must inherit from AbstractOperator",
            "NotAnOperator must define 'short_name' class attribute",
            "NotAnOperator must define 'category' class attribute",
            "NotAnOperator has owner='None'. Custom operators should set owner='custom'",
            "NotAnOperator must implement 'transform' method",
            "NotAnOperator must have 'get_metadata' method",
            "NotAnOperator must have 'get_required_features' method",
        ]

    @pytest.mark.parametrize("short_name", ["", 42])
    def test_short_name_must_be_non_empty_string(self, short_name: Any) -> None:
        cls = type("BadNameOp", (_ValidOp,), {"short_name": short_name, "transform": _ValidOp.transform})

        assert _errors(cls) == ["BadNameOp.short_name must be a non-empty string"]

    def test_docpipe_owner_is_rejected(self) -> None:
        cls = type("OwnedOp", (_ValidOp,), {"owner": "docpipe", "transform": _ValidOp.transform})

        assert _errors(cls) == ["OwnedOp has owner='docpipe'. Custom operators should set owner='custom'"]

    def test_inherited_transform_is_not_enough(self) -> None:
        cls = type("InheritingOp", (_ValidOp,), {})

        assert _errors(cls) == ["InheritingOp must implement 'transform' method"]

    @pytest.mark.parametrize("attribute", ["transform", "get_metadata", "get_required_features"])
    def test_methods_must_be_callable(self, attribute: str) -> None:
        namespace = {"transform": _ValidOp.transform, attribute: "not callable"}
        cls = type("BrokenOp", (_ValidOp,), namespace)

        assert _errors(cls) == [f"BrokenOp.{attribute} must be callable"]

    def test_missing_docstring_is_a_warning(self) -> None:
        cls = type("UndocumentedOp", (_ValidOp,), {"transform": _ValidOp.transform, "__doc__": None})

        result = OperatorValidator.validate_operator_class(cls=cls, operator_info=_INFO)

        assert (result.valid, result.warnings) == (True, ["UndocumentedOp should have a docstring"])


class TestValidateModule:
    """Operator discovery inside a loaded module."""

    @staticmethod
    def _module(*classes: type) -> types.ModuleType:
        module = types.ModuleType("custom_operator_sample")
        for cls in classes:
            clone = type(cls.__name__, (cls,), {"transform": _ValidOp.transform, "__doc__": cls.__doc__})
            clone.__module__ = module.__name__
            setattr(module, cls.__name__, clone)
        return module

    def test_multiple_operator_classes_validate_the_named_class(self) -> None:
        first = type("AlphaOp", (_ValidOp,), {"__doc__": "Alpha."})
        second = type("BetaOp", (_ValidOp,), {"__doc__": "Beta."})

        result = OperatorValidator.validate_module(
            module=self._module(first, second), operator_info=replace(_INFO, name="BetaOp")
        )

        assert result.valid is True
        assert result.warnings == []

    def test_unnamed_metadata_keeps_first_class_warning(self) -> None:
        first = type("AlphaOp", (_ValidOp,), {"__doc__": "Alpha."})
        second = type("BetaOp", (_ValidOp,), {"__doc__": "Beta."})

        result = OperatorValidator.validate_module(
            module=self._module(first, second), operator_info=replace(_INFO, name="")
        )

        assert result.valid is True
        assert result.warnings == ["Multiple operator classes found in sample.py. Using first one: AlphaOp"]

    @pytest.mark.parametrize("name", ["MissingOp", "NotAnOperator", "ImportedOp", "AbstractOp"])
    def test_invalid_named_metadata_does_not_use_another_class(self, name: str) -> None:
        module = self._module(type("ValidOp", (_ValidOp,), {"__doc__": "Valid."}))
        module.__dict__["NotAnOperator"] = 42
        module.__dict__["ImportedOp"] = _ValidOp

        class AbstractOp(_ValidOp, ABC):
            __module__ = module.__name__

            @abstractmethod
            def extra(self) -> None: ...

        module.__dict__["AbstractOp"] = AbstractOp

        result = OperatorValidator.validate_module(module=module, operator_info=replace(_INFO, name=name))

        assert result.valid is False
        assert result.errors == [
            f"Operator class '{name}' is not a concrete operator defined in module {module.__name__}"
        ]

    def test_non_string_class_name_is_rejected(self) -> None:
        module = self._module(type("ValidOp", (_ValidOp,), {"__doc__": "Valid."}))

        result = OperatorValidator.validate_module(module=module, operator_info=replace(_INFO, name=None))

        assert result.valid is False
        assert result.errors == ["Operator class name must be a string"]

    def test_module_without_operator_classes(self) -> None:
        result = OperatorValidator.validate_module(module=types.ModuleType("empty"), operator_info=_INFO)

        assert (result.valid, result.errors) == (False, ["No operator classes found in module sample.py"])


@pytest.fixture
def isolated_registry(monkeypatch) -> dict[str, Any]:
    """Run against a copy of the adapter registry so test adapters do not leak."""
    registry = dict(OperatorSourceFactory._adapters)
    monkeypatch.setattr(OperatorSourceFactory, "_adapters", registry)
    return registry


class _RecordingSource:
    ADAPTER_NAME = "recording"
    ADAPTER_DISPLAY_NAME = "Recording Source"

    def __init__(self, *, location: str) -> None:
        if location == "explode":
            raise OSError("location is not readable")
        self.location = location


class TestOperatorSourceFactory:
    """Registration, creation and adapter info."""

    @pytest.mark.usefixtures("isolated_registry")
    def test_register_create_list_and_info(self) -> None:
        register_operator_source(_RecordingSource)  # type: ignore[arg-type]

        adapter = OperatorSourceFactory.create("recording", location="/operators")

        assert isinstance(adapter, _RecordingSource)
        assert adapter.location == "/operators"
        assert "recording" in OperatorSourceFactory.list_adapters()
        assert OperatorSourceFactory.get_adapter_info("recording") == {
            "name": "recording",
            "display_name": "Recording Source",
            "class": "_RecordingSource",
        }

    def test_re_registration_replaces_the_adapter(self, isolated_registry: dict[str, Any]) -> None:
        register_operator_source(_RecordingSource)  # type: ignore[arg-type]
        replacement = type("ReplacementSource", (_RecordingSource,), {})

        register_operator_source(replacement)  # type: ignore[arg-type]

        assert isolated_registry["recording"] is replacement

    @pytest.mark.usefixtures("isolated_registry")
    def test_class_without_adapter_name_is_rejected(self) -> None:
        class Nameless:
            pass

        with pytest.raises(DocpipeException, match="Nameless must define ADAPTER_NAME"):
            register_operator_source(Nameless)  # type: ignore[arg-type]

    @pytest.mark.usefixtures("isolated_registry")
    def test_construction_error_is_wrapped(self) -> None:
        register_operator_source(_RecordingSource)  # type: ignore[arg-type]

        with pytest.raises(DocpipeException, match="Failed to create operator source adapter 'recording'") as exc:
            OperatorSourceFactory.create("recording", location="explode")

        assert exc.value.status_code == 500
        assert isinstance(exc.value.__cause__, OSError)

    def test_unknown_adapter(self, isolated_registry: dict[str, Any]) -> None:
        with pytest.raises(DocpipeException, match="Unknown operator source adapter: 'ftp'") as exc:
            OperatorSourceFactory.create("ftp")
        assert exc.value.status_code == 400

        with pytest.raises(DocpipeException, match="Unknown operator source adapter: 'ftp'"):
            OperatorSourceFactory.get_adapter_info("ftp")

        isolated_registry.clear()
        with pytest.raises(DocpipeException, match="Available adapters: none"):
            OperatorSourceFactory.create("ftp")

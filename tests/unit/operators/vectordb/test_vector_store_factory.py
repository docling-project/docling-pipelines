# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Unit tests for VectorStoreFactory registration, lazy loading and adapter creation."""

from collections.abc import Iterator
from typing import Any
from unittest.mock import patch

import pytest

from docpipe.core.operators.vectordb.adapters.outbound.factories.vector_store_factory import (
    VectorStoreFactory,
    register_vector_store,
)
from docpipe.exceptions.docpipe_exceptions import DocpipeException
from docpipe.exceptions.error_codes import ErrorCode


class _FakeAdapter:
    ADAPTER_NAME = "fake"
    ADAPTER_DISPLAY_NAME = "Fake"

    def __init__(self, **config: Any) -> None:
        self.config = config


class _RejectingAdapter(_FakeAdapter):
    ADAPTER_NAME = "rejecting"

    def __init__(self, **config: Any) -> None:
        raise DocpipeException(
            message="invalid fake configuration",
            status_code=400,
            error_code=ErrorCode.OPERATOR_CONFIGURATION_INVALID,
        )


class _CrashingAdapter(_FakeAdapter):
    ADAPTER_NAME = "crashing"

    def __init__(self, **config: Any) -> None:
        raise RuntimeError("boom")


class _Unnamed:
    pass


@pytest.fixture(autouse=True)
def isolated_registry() -> Iterator[None]:
    """Run each test against empty registries so global adapter registrations are untouched."""
    with (
        patch.dict(VectorStoreFactory._adapters, clear=True),
        patch.dict(VectorStoreFactory._lazy_adapters, clear=True),
    ):
        yield


class TestRegister:
    def test_decorator_registers_the_adapter_and_returns_it(self) -> None:
        assert register_vector_store(_FakeAdapter) is _FakeAdapter  # type: ignore[arg-type]
        assert VectorStoreFactory.list_adapters() == ["fake"]

    def test_adapter_without_a_name_is_rejected(self) -> None:
        with pytest.raises(DocpipeException, match="must define ADAPTER_NAME"):
            VectorStoreFactory.register(_Unnamed)  # type: ignore[arg-type]

    def test_registering_again_overwrites_and_clears_the_lazy_entry(self) -> None:
        VectorStoreFactory.register_lazy("fake", "some.module", "Missing")
        VectorStoreFactory.register(_FakeAdapter)  # type: ignore[arg-type]

        assert "fake" not in VectorStoreFactory._lazy_adapters
        VectorStoreFactory.register(_FakeAdapter)  # type: ignore[arg-type]
        assert VectorStoreFactory._adapters["fake"] is _FakeAdapter

    def test_lazy_registration_is_skipped_for_an_eagerly_registered_adapter(self) -> None:
        VectorStoreFactory.register(_FakeAdapter)  # type: ignore[arg-type]

        VectorStoreFactory.register_lazy("fake", "some.module", "Other")

        assert "fake" not in VectorStoreFactory._lazy_adapters


class TestLazyLoading:
    def test_first_create_imports_the_adapter_and_moves_it_to_the_eager_registry(self) -> None:
        VectorStoreFactory.register_lazy("fake", __name__, "_FakeAdapter")

        adapter = VectorStoreFactory.create("fake", host="h")

        assert isinstance(adapter, _FakeAdapter)
        assert adapter.config == {"host": "h"}
        assert VectorStoreFactory._adapters["fake"] is _FakeAdapter
        assert "fake" not in VectorStoreFactory._lazy_adapters

    def test_missing_module_is_reported_and_stays_registered(self) -> None:
        VectorStoreFactory.register_lazy("fake", "docpipe.no_such_module", "Adapter")

        with pytest.raises(DocpipeException, match="missing optional dependencies") as exc_info:
            VectorStoreFactory.create("fake")

        assert exc_info.value.status_code == 500
        assert "fake" in VectorStoreFactory._lazy_adapters

    def test_missing_class_is_reported_and_stays_registered(self) -> None:
        VectorStoreFactory.register_lazy("fake", __name__, "NoSuchClass")

        with pytest.raises(DocpipeException, match="'NoSuchClass' not found"):
            VectorStoreFactory.create("fake")

        assert "fake" in VectorStoreFactory._lazy_adapters

    def test_loading_an_adapter_that_is_not_registered_lazily_fails(self) -> None:
        with pytest.raises(DocpipeException, match="not found in registry"):
            VectorStoreFactory._load_lazy_adapter("fake")


class TestCreate:
    def test_unknown_adapter_lists_the_available_ones(self) -> None:
        VectorStoreFactory.register(_FakeAdapter)  # type: ignore[arg-type]
        VectorStoreFactory.register_lazy("other", "some.module", "Other")

        with pytest.raises(DocpipeException, match=r"Unknown vector store adapter: 'nope'.*fake, other") as exc_info:
            VectorStoreFactory.create("nope")

        assert exc_info.value.status_code == 400

    def test_unknown_adapter_with_empty_registry_says_none_available(self) -> None:
        with pytest.raises(DocpipeException, match="Available adapters: none"):
            VectorStoreFactory.create("nope")

    def test_docpipe_exception_from_the_adapter_is_raised_as_is(self) -> None:
        VectorStoreFactory.register(_RejectingAdapter)  # type: ignore[arg-type]

        with pytest.raises(DocpipeException) as exc_info:
            VectorStoreFactory.create("rejecting")

        assert exc_info.value.status_code == 400
        assert str(exc_info.value) == "invalid fake configuration"

    def test_other_adapter_failures_are_wrapped_with_the_adapter_name(self) -> None:
        VectorStoreFactory.register(_CrashingAdapter)  # type: ignore[arg-type]

        with pytest.raises(
            DocpipeException, match="Failed to create vector store adapter 'crashing': boom"
        ) as exc_info:
            VectorStoreFactory.create("crashing")

        assert isinstance(exc_info.value.__cause__, RuntimeError)


class TestAdapterInfo:
    def test_loaded_adapter_reports_its_class(self) -> None:
        VectorStoreFactory.register(_FakeAdapter)  # type: ignore[arg-type]

        assert VectorStoreFactory.get_adapter_info("fake") == {
            "name": "fake",
            "display_name": "Fake",
            "class": "_FakeAdapter",
            "loaded": True,
        }

    def test_lazy_adapter_reports_its_module_without_loading_it(self) -> None:
        VectorStoreFactory.register_lazy("fake", "some.module", "Fake")

        assert VectorStoreFactory.get_adapter_info("fake") == {
            "name": "fake",
            "display_name": "Fake",
            "class": "Fake",
            "module": "some.module",
            "loaded": False,
        }

    def test_unknown_adapter_is_rejected(self) -> None:
        with pytest.raises(DocpipeException, match="Unknown vector store adapter: 'nope'") as exc_info:
            VectorStoreFactory.get_adapter_info("nope")

        assert exc_info.value.status_code == 400

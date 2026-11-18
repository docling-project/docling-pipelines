"""Unit tests for the Asset base class defaults."""

from dataclasses import dataclass
from typing import Any

import pytest

from docpipe.core.assets.common.domain.models.asset import Asset
from docpipe.core.assets.document_libraries.domain.models.document_library import DocumentLibrary
from docpipe.exceptions.docpipe_exceptions import AssetInvalidDataException


@dataclass(repr=False)
class _MinimalAsset(Asset):
    """Asset that relies on every default the base class provides (repr=False keeps Asset.__repr__)."""

    def get_asset_type(self) -> str:  # type: ignore[override]
        return "minimal"

    @staticmethod
    def get_config_key() -> str:
        return "minimal"

    @staticmethod
    def get_collection_name() -> str:
        return "minimals"

    def update_timestamp(self) -> None:
        return None

    @classmethod
    def from_dict(cls, *, data: dict[str, Any]) -> "_MinimalAsset":
        return cls(asset_id=data["asset_id"], name=data["name"], description=data.get("description"))


def test_base_to_dict_contains_common_fields() -> None:
    asset = _MinimalAsset(asset_id="a-1", name="Minimal", description="base fields only")

    assert asset.to_dict() == {
        "asset_id": "a-1",
        "asset_type": "minimal",
        "name": "Minimal",
        "description": "base fields only",
    }
    assert _MinimalAsset.from_dict(data=asset.to_dict()) == asset


def test_asset_id_is_generated_when_missing() -> None:
    first, second = _MinimalAsset(name="One"), _MinimalAsset(name="Two")

    assert first.asset_id and second.asset_id
    assert first.asset_id != second.asset_id


def test_timestamps_default_to_none() -> None:
    asset = _MinimalAsset(name="No timestamps")

    assert asset.get_created_at() is None
    assert asset.get_updated_at() is None


def test_document_library_uses_timestamp_defaults() -> None:
    library = DocumentLibrary(library_id="lib-1", name="Library")

    assert library.get_created_at() is None
    assert library.get_updated_at() is None


def test_str_and_repr() -> None:
    asset = _MinimalAsset(asset_id="a-1", name="Minimal")

    assert str(asset) == "minimal(id=a-1, name=Minimal)"
    assert repr(asset) == "_MinimalAsset(asset_id='a-1', name='Minimal')"


@pytest.mark.parametrize(
    ("name", "description", "message"),
    [
        ("", None, "name cannot be empty"),
        ("   ", None, "name cannot be empty"),
        ("x" * 256, None, "name cannot exceed 255 characters"),
        ("Valid", "d" * 2001, "description cannot exceed 2000 characters"),
    ],
)
def test_validate_rejects_invalid_common_fields(name: str, description: str | None, message: str) -> None:
    with pytest.raises(AssetInvalidDataException, match=message):
        _MinimalAsset(name=name, description=description).validate()


def test_validate_accepts_boundary_values() -> None:
    _MinimalAsset(name="x" * 255, description="d" * 2000).validate()

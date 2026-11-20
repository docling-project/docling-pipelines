# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Tests for DestinationAdapterFactory and the DestinationAdapterPort defaults."""

from typing import Any
from unittest.mock import patch

import pytest
from pydantic import BaseModel

# Import the adapters so they self-register with the factory.
import docpipe.core.operators.storage.adapters.outbound.destinations.filesystem.adapter
import docpipe.core.operators.storage.adapters.outbound.destinations.sharepoint.adapter  # noqa: F401
from docpipe.core.operators.storage.adapters.outbound.destinations.factories.destination_factory import (
    DestinationAdapterFactory,
    register_destination_adapter,
)
from docpipe.core.operators.storage.domain.models import WriteResult
from docpipe.core.operators.storage.ports.outbound.destination_adapter import DestinationAdapterPort


class _DummyConfig(BaseModel):
    """Config model of the dummy adapter."""

    root: str = "r"


class _DummyAdapter(DestinationAdapterPort[_DummyConfig]):
    """Minimal adapter that only implements the abstract methods."""

    DEST_NAME: str | None = "dummy_dest"

    def write_document(self, *, content: bytes, destination_path: str, overwrite: bool = True) -> WriteResult:
        """Pretend to write."""
        return WriteResult(doc_id="", doc_name=destination_path, success=True)

    def ensure_directory(self, *, path: str) -> None:
        """No-op."""

    def resolve_destination_path(self, *, relative_path: str, config: _DummyConfig) -> str:
        """Join root and relative path."""
        return f"{config.root}/{relative_path}"

    def build_config_from_operator_params(
        self, *, provider_config: dict[str, Any], credentials: dict[str, Any]
    ) -> _DummyConfig:
        """Build the dummy config."""
        return _DummyConfig(**provider_config)

    def get_config_schema(self) -> type[BaseModel]:
        """Return the dummy config model."""
        return _DummyConfig


class TestDestinationAdapterPortDefaults:
    """Default behaviour inherited from the port."""

    def test_default_validate_destination_accepts_any_config(self) -> None:
        """The port's default validate_destination performs no checks and returns None."""
        assert _DummyAdapter().validate_destination(config=_DummyConfig()) is None


class TestDestinationAdapterFactory:
    """Registration and lookup of destination adapters."""

    def test_register_requires_dest_name(self) -> None:
        """An adapter class without DEST_NAME is rejected and not registered."""

        class _Nameless(_DummyAdapter):
            DEST_NAME = None

        with patch.dict(DestinationAdapterFactory._adapters), pytest.raises(ValueError, match="_Nameless"):
            DestinationAdapterFactory.register(_Nameless)

    def test_decorator_registers_and_returns_class(self) -> None:
        """register_destination_adapter registers the class and returns it unchanged."""
        with patch.dict(DestinationAdapterFactory._adapters):
            assert register_destination_adapter(_DummyAdapter) is _DummyAdapter
            assert DestinationAdapterFactory.is_registered("dummy_dest")
            assert isinstance(DestinationAdapterFactory.create("dummy_dest"), _DummyAdapter)
        assert not DestinationAdapterFactory.is_registered("dummy_dest")

    def test_create_unknown_name_lists_available_adapters_and_aliases(self) -> None:
        """An unknown provider raises with the registered names and aliases."""
        with pytest.raises(ValueError, match="Unknown destination adapter: 'nope'") as exc_info:
            DestinationAdapterFactory.create("nope")

        message = str(exc_info.value)
        assert "filesystem" in message
        assert "onedrive" in message
        assert "ibm_cos" in message

    def test_alias_resolves_to_canonical_adapter(self) -> None:
        """onedrive creates the SharePoint adapter."""
        adapter = DestinationAdapterFactory.create("onedrive")
        assert adapter.DEST_NAME == "sharepoint"

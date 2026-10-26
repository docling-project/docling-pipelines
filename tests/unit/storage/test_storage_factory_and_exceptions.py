"""Tests for StorageFactory error handling and the storage exception types."""

import re

import pytest

from docpipe.exceptions.error_codes import ErrorCode
from docpipe.storage.exceptions import (
    StorageConnectionError,
    StorageException,
    StorageNotFoundError,
)
from docpipe.storage.factory import StorageFactory


class TestStorageFactoryUnsupportedTypes:
    """Unknown storage types are rejected with the list of supported ones."""

    def test_unknown_key_value_storage_type_raises_value_error(self):
        """create_key_value_storage names the supported key-value backends."""
        with pytest.raises(
            ValueError,
            match=re.escape("Unsupported key-value storage type: 'redis'. Supported types: filesystem, duckdb"),
        ):
            StorageFactory.create_key_value_storage(storage_type="redis")

    def test_unknown_table_storage_type_raises_value_error(self):
        """create_table_storage names the supported table backends."""
        with pytest.raises(
            ValueError, match=re.escape("Unsupported table storage type: 'filesystem'. Supported types: duckdb")
        ):
            StorageFactory.create_table_storage(storage_type="filesystem")


class TestStorageExceptions:
    """HTTP status codes and error codes carried by the storage exceptions."""

    @pytest.mark.parametrize(
        ("exception_type", "status_code"),
        [(StorageNotFoundError, 404), (StorageConnectionError, 503)],
    )
    def test_exception_carries_status_and_storage_error_code(self, exception_type, status_code):
        """Each subclass is a StorageException with its own HTTP status code."""
        error = exception_type(message="storage unavailable")

        assert isinstance(error, StorageException)
        assert error.status_code == status_code
        assert error.error_code == ErrorCode.DOCUMENT_SET_STORAGE_ERROR
        assert "storage unavailable" in str(error)

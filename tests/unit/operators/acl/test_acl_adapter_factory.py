# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Unit tests for ACL Adapter Factory."""

import traceback
from unittest.mock import Mock

import pytest
from pydantic import BaseModel

from docpipe.core.operators.acl.adapters.outbound.factories.acl_adapter_factory import (
    _ACL_ADAPTER_REGISTRY,
    ACLAdapterFactory,
    register_acl_adapter,
)
from docpipe.core.operators.acl.ports.outbound.acl_extraction import ACLExtractionPort
from docpipe.exceptions.docpipe_exceptions import ConfigurationError


@pytest.fixture(autouse=True)
def _restore_acl_adapter_registry():
    """Put the registered providers back after a test that clears the registry, for the tests that run later."""
    saved = dict(_ACL_ADAPTER_REGISTRY)
    yield
    _ACL_ADAPTER_REGISTRY.clear()
    _ACL_ADAPTER_REGISTRY.update(saved)


class MockACLAdapter(ACLExtractionPort):
    """Mock ACL adapter for testing."""

    def __init__(self, connection_params=None, credentials=None, provider_metadata=None):
        super().__init__()
        self.connection_params = connection_params
        self.credentials = credentials
        self.provider_metadata = provider_metadata

    async def extract_acl(self, *, request):
        """Mock extract_acl implementation."""
        from docpipe.core.operators.acl.domain.models import ACLResponse

        return ACLResponse(
            resource_id=request.resource_id,
            resource_path=request.resource_path,
            allowed_users=set(),
            extraction_success=True,
        )

    async def extract_acls_batch(self, *, requests):
        """Mock extract_acls_batch implementation."""
        return [await self.extract_acl(request=req) for req in requests]

    async def resolve_inheritance(self, *, resource_id, resource_type, config):
        """Mock resolve_inheritance implementation."""
        return [resource_id]

    async def expand_group(self, *, group_id, config):
        """Mock expand_group implementation."""
        return set()

    def normalize_identity(self, *, principal_id, principal_type, config):
        """Mock normalize_identity implementation."""
        return principal_id.lower()

    async def test_connection(self, *, config):
        """Mock test_connection implementation."""
        return True

    def build_config_from_operator_params(self, *, connection_params, credentials, provider_metadata):
        """Mock build_config_from_operator_params implementation."""
        return Mock()


class TestACLAdapterFactoryRegistration:
    """Test adapter registration functionality."""

    def test_register_adapter_success(self):
        """Test successful adapter registration."""
        # Clear registry first
        _ACL_ADAPTER_REGISTRY.clear()

        ACLAdapterFactory.register_adapter(provider="test_provider", adapter_class=MockACLAdapter)

        assert "test_provider" in _ACL_ADAPTER_REGISTRY
        assert _ACL_ADAPTER_REGISTRY["test_provider"] == MockACLAdapter

    def test_register_adapter_case_insensitive(self):
        """Test adapter registration is case-insensitive."""
        _ACL_ADAPTER_REGISTRY.clear()

        ACLAdapterFactory.register_adapter(provider="TestProvider", adapter_class=MockACLAdapter)

        assert "testprovider" in _ACL_ADAPTER_REGISTRY

    def test_register_adapter_overwrites_existing(self):
        """Test registering same provider overwrites existing."""
        _ACL_ADAPTER_REGISTRY.clear()

        class FirstAdapter(ACLExtractionPort): ...

        class SecondAdapter(ACLExtractionPort): ...

        ACLAdapterFactory.register_adapter(provider="test_provider", adapter_class=FirstAdapter)

        ACLAdapterFactory.register_adapter(provider="test_provider", adapter_class=SecondAdapter)

        assert _ACL_ADAPTER_REGISTRY["test_provider"] == SecondAdapter

    def test_register_adapter_invalid_class(self):
        """Test registering invalid adapter class raises error."""
        _ACL_ADAPTER_REGISTRY.clear()

        class InvalidAdapter:
            """Not a subclass of ACLExtractionPort."""

        with pytest.raises(ValueError, match="must implement ACLExtractionPort"):
            ACLAdapterFactory.register_adapter(provider="test_provider", adapter_class=InvalidAdapter)


class TestACLAdapterFactoryDecorator:
    """Test decorator-based registration."""

    def test_decorator_registers_adapter(self):
        """Test decorator successfully registers adapter."""
        _ACL_ADAPTER_REGISTRY.clear()

        @register_acl_adapter("decorated_provider")
        class DecoratedAdapter(ACLExtractionPort): ...

        assert "decorated_provider" in _ACL_ADAPTER_REGISTRY
        assert _ACL_ADAPTER_REGISTRY["decorated_provider"] == DecoratedAdapter

    def test_decorator_returns_class(self):
        """Test decorator returns the original class."""
        _ACL_ADAPTER_REGISTRY.clear()

        @register_acl_adapter("decorated_provider")
        class DecoratedAdapter(MockACLAdapter): ...

        # Should be able to instantiate the class
        instance = DecoratedAdapter()
        assert isinstance(instance, ACLExtractionPort)


class TestACLAdapterFactoryCreation:
    """Test adapter creation functionality."""

    def test_create_adapter_success(self):
        """Test successful adapter creation."""
        _ACL_ADAPTER_REGISTRY.clear()
        ACLAdapterFactory.register_adapter(provider="test_provider", adapter_class=MockACLAdapter)

        # Factory now creates adapters with no parameters
        # Credentials/connection_params are passed per-request via extract_acl
        adapter = ACLAdapterFactory.create_adapter(provider="test_provider")

        assert isinstance(adapter, MockACLAdapter)
        # Adapter is created without parameters - they're passed at runtime
        assert adapter.connection_params is None
        assert adapter.credentials is None
        assert adapter.provider_metadata is None

    def test_create_adapter_case_insensitive(self):
        """Test adapter creation is case-insensitive."""
        _ACL_ADAPTER_REGISTRY.clear()
        ACLAdapterFactory.register_adapter(provider="test_provider", adapter_class=MockACLAdapter)

        # Should work with different case
        adapter = ACLAdapterFactory.create_adapter(provider="TEST_PROVIDER")

        assert isinstance(adapter, MockACLAdapter)

    def test_create_adapter_unknown_provider(self):
        """Test creating adapter for unknown provider raises error."""
        _ACL_ADAPTER_REGISTRY.clear()

        with pytest.raises(ConfigurationError) as exc_info:
            ACLAdapterFactory.create_adapter(provider="unknown_provider")

        assert "Unknown ACL provider" in str(exc_info.value)
        assert "unknown_provider" in str(exc_info.value)

    def test_create_adapter_with_none_provider_metadata(self):
        """Test creating adapter - metadata now passed at runtime, not construction."""
        _ACL_ADAPTER_REGISTRY.clear()
        ACLAdapterFactory.register_adapter(provider="test_provider", adapter_class=MockACLAdapter)

        adapter = ACLAdapterFactory.create_adapter(provider="test_provider")

        assert isinstance(adapter, MockACLAdapter)
        # Adapter created without metadata - passed at runtime via extract_acl
        assert adapter.provider_metadata is None

    def test_create_adapter_initialization_failure(self):
        """Test adapter creation when initialization fails."""
        _ACL_ADAPTER_REGISTRY.clear()

        class FailingAdapter(ACLExtractionPort):
            def __init__(self, connection_params=None, credentials=None, provider_metadata=None):
                raise ValueError("Initialization failed")

        ACLAdapterFactory.register_adapter(provider="failing_provider", adapter_class=FailingAdapter)

        with pytest.raises(ConfigurationError) as exc_info:
            ACLAdapterFactory.create_adapter(provider="failing_provider", connection_params={}, credentials={})

        assert "Failed to create ACL adapter" in str(exc_info.value)

    def test_create_adapter_initialization_failure_omits_rejected_input(self, caplog):
        """A ValidationError raised by an adapter constructor must not echo the rejected input."""
        sentinel = "SENTINEL_FACTORY_2b9e"

        class _Settings(BaseModel):
            limit: int

        _ACL_ADAPTER_REGISTRY.clear()

        class RejectingAdapter(MockACLAdapter):
            def __init__(self):
                _Settings(limit=sentinel)  # type: ignore[arg-type]

        ACLAdapterFactory.register_adapter(provider="rejecting_provider", adapter_class=RejectingAdapter)

        with caplog.at_level("DEBUG"):
            with pytest.raises(ConfigurationError) as exc_info:
                ACLAdapterFactory.create_adapter(provider="rejecting_provider")

        assert "limit" in str(exc_info.value)
        assert sentinel not in str(exc_info.value)
        assert "input_value" not in str(exc_info.value)
        # The traceback a job handler prints walks the whole cause and context chain
        printed = "".join(traceback.format_exception(exc_info.value))
        assert sentinel not in printed
        assert "input_value" not in printed
        assert exc_info.value.__context__ is None
        assert caplog.records
        for record in caplog.records:
            assert sentinel not in record.getMessage()
            assert record.exc_info is None
            assert sentinel not in (record.exc_text or "")


class TestACLAdapterFactoryQuery:
    """Test factory query methods."""

    def test_get_registered_providers(self):
        """Test getting list of registered providers."""
        _ACL_ADAPTER_REGISTRY.clear()

        ACLAdapterFactory.register_adapter(provider="provider_a", adapter_class=MockACLAdapter)
        ACLAdapterFactory.register_adapter(provider="provider_b", adapter_class=MockACLAdapter)
        ACLAdapterFactory.register_adapter(provider="provider_c", adapter_class=MockACLAdapter)

        providers = ACLAdapterFactory.get_registered_providers()

        assert len(providers) == 3
        assert "provider_a" in providers
        assert "provider_b" in providers
        assert "provider_c" in providers
        # Should be sorted
        assert providers == sorted(providers)

    def test_get_registered_providers_empty(self):
        """Test getting providers when none registered."""
        _ACL_ADAPTER_REGISTRY.clear()

        providers = ACLAdapterFactory.get_registered_providers()

        assert len(providers) == 0
        assert isinstance(providers, list)

    def test_is_provider_registered_true(self):
        """Test checking if provider is registered (true case)."""
        _ACL_ADAPTER_REGISTRY.clear()

        ACLAdapterFactory.register_adapter(provider="test_provider", adapter_class=MockACLAdapter)

        assert ACLAdapterFactory.is_provider_registered(provider="test_provider") is True

    def test_is_provider_registered_false(self):
        """Test checking if provider is registered (false case)."""
        _ACL_ADAPTER_REGISTRY.clear()

        assert ACLAdapterFactory.is_provider_registered(provider="unknown_provider") is False

    def test_is_provider_registered_case_insensitive(self):
        """Test provider check is case-insensitive."""
        _ACL_ADAPTER_REGISTRY.clear()

        ACLAdapterFactory.register_adapter(provider="test_provider", adapter_class=MockACLAdapter)

        assert ACLAdapterFactory.is_provider_registered(provider="TEST_PROVIDER") is True
        assert ACLAdapterFactory.is_provider_registered(provider="Test_Provider") is True


class TestACLAdapterFactoryIntegration:
    """Integration tests for factory with multiple adapters."""

    def test_multiple_adapters_registration(self):
        """Test registering multiple different adapters."""
        _ACL_ADAPTER_REGISTRY.clear()

        class SharePointAdapter(MockACLAdapter): ...

        class S3Adapter(MockACLAdapter): ...

        class GoogleDriveAdapter(MockACLAdapter): ...

        ACLAdapterFactory.register_adapter(provider="sharepoint", adapter_class=SharePointAdapter)
        ACLAdapterFactory.register_adapter(provider="s3", adapter_class=S3Adapter)
        ACLAdapterFactory.register_adapter(provider="google_drive", adapter_class=GoogleDriveAdapter)

        providers = ACLAdapterFactory.get_registered_providers()
        assert len(providers) == 3

        # Create each adapter
        sp_adapter = ACLAdapterFactory.create_adapter(provider="sharepoint", connection_params={}, credentials={})
        assert isinstance(sp_adapter, SharePointAdapter)

        s3_adapter = ACLAdapterFactory.create_adapter(provider="s3", connection_params={}, credentials={})
        assert isinstance(s3_adapter, S3Adapter)

        gd_adapter = ACLAdapterFactory.create_adapter(provider="google_drive", connection_params={}, credentials={})
        assert isinstance(gd_adapter, GoogleDriveAdapter)

    def test_error_message_includes_available_providers(self):
        """Test error message includes list of available providers."""
        _ACL_ADAPTER_REGISTRY.clear()

        ACLAdapterFactory.register_adapter(provider="provider_a", adapter_class=MockACLAdapter)
        ACLAdapterFactory.register_adapter(provider="provider_b", adapter_class=MockACLAdapter)

        with pytest.raises(ConfigurationError) as exc_info:
            ACLAdapterFactory.create_adapter(provider="unknown", connection_params={}, credentials={})

        error_message = str(exc_info.value)
        assert "Available providers:" in error_message
        assert "provider_a" in error_message
        assert "provider_b" in error_message


class TestACLAdapterFactoryEdgeCases:
    """Test edge cases and error conditions."""

    def test_create_adapter_with_empty_provider_name(self):
        """Test creating adapter with empty provider name."""
        _ACL_ADAPTER_REGISTRY.clear()

        with pytest.raises(ConfigurationError):
            ACLAdapterFactory.create_adapter(provider="", connection_params={}, credentials={})

    def test_register_adapter_with_empty_provider_name(self):
        """Test registering adapter with empty provider name."""
        _ACL_ADAPTER_REGISTRY.clear()

        # Should register with empty string key (though not recommended)
        ACLAdapterFactory.register_adapter(provider="", adapter_class=MockACLAdapter)

        assert "" in _ACL_ADAPTER_REGISTRY

    def test_create_adapter_preserves_configuration_error(self):
        """Test that ConfigurationError from adapter is preserved."""
        _ACL_ADAPTER_REGISTRY.clear()

        class ConfigErrorAdapter(MockACLAdapter):
            def __init__(self, connection_params=None, credentials=None, provider_metadata=None):
                raise ConfigurationError("Missing required config")

        ACLAdapterFactory.register_adapter(provider="config_error_provider", adapter_class=ConfigErrorAdapter)

        with pytest.raises(ConfigurationError) as exc_info:
            ACLAdapterFactory.create_adapter(provider="config_error_provider", connection_params={}, credentials={})

        # Should preserve the original ConfigurationError
        assert "Missing required config" in str(exc_info.value)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])

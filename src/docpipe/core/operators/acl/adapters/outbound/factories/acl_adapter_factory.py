# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Factory for creating ACL extraction adapters.

This module provides a factory pattern for creating ACL extraction adapters
based on provider type. It uses a registry pattern to allow dynamic registration
of new adapters without modifying the factory code.
"""

import logging
from typing import Any, Callable

from docpipe.core.operators.acl.ports.outbound.acl_extraction import ACLExtractionPort
from docpipe.exceptions.docpipe_exceptions import ConfigurationError
from docpipe.exceptions.error_codes import ErrorCode
from docpipe.utils.infrastructure.exception_sanitizer import (
    is_sensitive_chain,
    sanitize_exception,
    sanitized_cause,
)

logger = logging.getLogger(__name__)

# Type alias for adapter constructor
AdapterConstructor = Callable[..., ACLExtractionPort]

# Global registry of ACL adapters
_ACL_ADAPTER_REGISTRY: dict[str, AdapterConstructor] = {}


class ACLAdapterFactory:
    """Factory for creating ACL extraction adapters.

    This factory uses a registry pattern to create adapters based on provider
    type. Adapters can be registered using the @register_acl_adapter decorator
    or by calling register_adapter() directly.

    Example:
        # Register an adapter
        @register_acl_adapter("sharepoint")
        class SharePointACLAdapter(ACLExtractionPort):
            ...

        # Create an adapter
        adapter = ACLAdapterFactory.create_adapter(
            provider="sharepoint",
            connection_params={...},
            credentials={...}
        )
    """

    @classmethod
    def create_adapter(
        cls,
        *,
        provider: str,
        connection_params: dict[str, Any] | None = None,
        credentials: dict[str, Any] | None = None,
        provider_metadata: dict[str, Any] | None = None,
    ) -> ACLExtractionPort:
        """Create an ACL extraction adapter for the specified provider.

        Note: connection_params, credentials, and provider_metadata are deprecated
        and ignored. These are now passed per-request via extract_acl() method.

        Args:
            provider: Provider name (e.g., "sharepoint", "s3", "google_drive")
            connection_params: (Deprecated) Not used - kept for backward compatibility
            credentials: (Deprecated) Not used - kept for backward compatibility
            provider_metadata: (Deprecated) Not used - kept for backward compatibility

        Returns:
            ACL extraction adapter instance

        Raises:
            ValueError: If provider is not registered or parameters are invalid
        """
        provider_lower = provider.lower()

        if provider_lower not in _ACL_ADAPTER_REGISTRY:
            available_providers = ", ".join(sorted(_ACL_ADAPTER_REGISTRY.keys()))
            raise ConfigurationError(
                f"Unknown ACL provider: {provider}. Available providers: {available_providers}",
                error_code=ErrorCode.ACL_PROVIDER_NOT_SUPPORTED,
            )

        adapter_constructor = _ACL_ADAPTER_REGISTRY[provider_lower]

        failure: tuple[BaseException, ConfigurationError] | None = None
        try:
            # Create adapter instance (no parameters - adapters configure themselves)
            adapter = adapter_constructor()

            logger.info("Created ACL adapter for provider: %s", provider)
            return adapter

        except ConfigurationError as e:
            if not is_sensitive_chain(exc=e):
                # Re-raise configuration errors as-is
                raise
            # A constructor wrapped a secret-bearing cause (for example a ValidationError) in its own
            # ConfigurationError. Keep its status, error code and extra fields, and replace the cause.
            sanitized = sanitize_exception(exc=e, config_key=provider_lower)
            logger.error("Failed to create ACL adapter for provider %s: %s", provider, sanitized)
            replacement = ConfigurationError(sanitized, error_code=e.error_code, status_code=e.status_code)
            replacement.more_info = e.more_info
            replacement.message_code = e.message_code
            failure = (sanitized_cause(exc=e, config_key=provider_lower), replacement)
        except Exception as e:
            # Sanitized text, no traceback: an adapter constructor may fail on a config ValidationError. The
            # wrapper is raised after this block so no __context__ keeps the original reachable (see sanitized_cause).
            sanitized = sanitize_exception(exc=e, config_key=provider_lower)
            logger.error("Failed to create ACL adapter for provider %s: %s", provider, sanitized)
            wrapper = ConfigurationError(
                f"Failed to create ACL adapter for provider {provider}: {sanitized}",
                error_code=ErrorCode.ACL_ADAPTER_INITIALIZATION_FAILED,
            )
            failure = (sanitized_cause(exc=e, config_key=provider_lower), wrapper)

        cause, error = failure
        raise error from cause

    @classmethod
    def register_adapter(cls, *, provider: str, adapter_class: type[ACLExtractionPort]) -> None:
        """Register an ACL adapter for a provider.

        Args:
            provider: Provider name (e.g., "sharepoint", "s3")
            adapter_class: Adapter class that implements ACLExtractionPort

        Raises:
            ValueError: If adapter_class does not implement ACLExtractionPort
        """
        if not issubclass(adapter_class, ACLExtractionPort):
            raise ValueError(f"Adapter class {adapter_class.__name__} must implement ACLExtractionPort")

        provider_lower = provider.lower()

        if provider_lower in _ACL_ADAPTER_REGISTRY:
            logger.warning("Overwriting existing ACL adapter registration for provider: %s", provider)

        _ACL_ADAPTER_REGISTRY[provider_lower] = adapter_class
        logger.info("Registered ACL adapter for provider: %s", provider)

    @classmethod
    def get_registered_providers(cls) -> list[str]:
        """Get list of registered provider names.

        Returns:
            Sorted list of registered provider names
        """
        return sorted(_ACL_ADAPTER_REGISTRY.keys())

    @classmethod
    def is_provider_registered(cls, *, provider: str) -> bool:
        """Check if a provider is registered.

        Args:
            provider: Provider name to check

        Returns:
            True if provider is registered, False otherwise
        """
        return provider.lower() in _ACL_ADAPTER_REGISTRY


def register_acl_adapter(provider: str) -> Callable[[type[ACLExtractionPort]], type[ACLExtractionPort]]:
    """Decorator to register an ACL adapter for a provider.

    This decorator provides a convenient way to register adapters at module
    import time.

    Args:
        provider: Provider name (e.g., "sharepoint", "s3")

    Returns:
        Decorator function that registers the adapter class

    Example:
        @register_acl_adapter("sharepoint")
        class SharePointACLAdapter(ACLExtractionPort):
            ...
    """

    def decorator(adapter_class: type[ACLExtractionPort]) -> type[ACLExtractionPort]:
        """Register the decorated adapter class and return it unchanged."""
        ACLAdapterFactory.register_adapter(provider=provider, adapter_class=adapter_class)
        return adapter_class

    return decorator

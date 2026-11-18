"""Document class provider port and default static implementation.

This port defines the contract for resolving document class metadata (types,
descriptions, and extraction schemas).

Two implementations are shipped here:

- ``DocumentClassProvider`` — abstract base class that any implementation
  must subclass.
- ``StaticDocumentClassProvider`` — the default local-file-backed
  implementation that wraps ``DocumentClassUtils``.  It is used automatically
  when no provider is explicitly injected into ``ExtractOperator``, preserving
  all existing local / dev behaviour.

Note: Docling-specific template generation (previously
``generate_docling_templates_for_types``) has been moved to
:mod:`docpipe.core.operators.extract.adapters.outbound.entity_extraction.docling_entity_adapter`.
The port only exposes domain-level contracts.
"""

from abc import ABC, abstractmethod


class DocumentClassProvider(ABC):
    """Abstract base class for resolving document class metadata.

    Implementations must provide document types and schema templates.
    Concrete subclasses must inherit from this class and implement all
    abstract methods.
    """

    @abstractmethod
    def get_document_types(self) -> dict[str, str]:
        """Return a mapping of ``document_type → document_description``.

        Returns:
            Dict mapping document type identifiers to human-readable
            descriptions.
        """
        ...

    @abstractmethod
    def get_schema_templates(self, *, document_types: list[str]) -> dict[str, dict]:
        """Return the raw document-class schemas for the requested types.

        Args:
            document_types: List of document type names to load.

        Returns:
            Dict mapping document type to its schema dict.
        """
        ...


class StaticDocumentClassProvider(DocumentClassProvider):
    """Default local-file-backed implementation of :class:`DocumentClassProvider`.

    Delegates every method directly to :class:`~docpipe.utils.document_class_utils.DocumentClassUtils`,
    keeping the existing behaviour intact when no external provider is injected.
    """

    def get_document_types(self) -> dict[str, str]:
        """Return a mapping of ``document_type → document_description`` from local files.

        Returns:
            Dict mapping document type identifiers to human-readable
            descriptions.
        """
        from docpipe.utils.document_class_utils import DocumentClassUtils

        return dict(DocumentClassUtils.get_document_types())

    def get_schema_templates(self, *, document_types: list[str]) -> dict[str, dict]:
        """Return the raw document-class schemas for the requested types from local files.

        Args:
            document_types: List of document type names to load.

        Returns:
            Dict mapping document type to its schema dict.
        """
        from docpipe.utils.document_class_utils import DocumentClassUtils

        return DocumentClassUtils.get_schema_templates(document_types)


_DEFAULT_PROVIDER = StaticDocumentClassProvider()


def get_default_document_class_provider() -> DocumentClassProvider:
    """Return the shared stateless :class:`StaticDocumentClassProvider`.

    Use this instead of instantiating ``StaticDocumentClassProvider()`` at every
    call site that falls back to the local-file default.
    """
    return _DEFAULT_PROVIDER

"""Outbound adapters for document classification.

Importing this package triggers auto-registration of all adapters with
ClassificationAdapterFactory via the @register_classification_adapter decorator.
"""

from .standard_llm_adapter import StandardLLMClassificationAdapter

__all__ = ["StandardLLMClassificationAdapter"]

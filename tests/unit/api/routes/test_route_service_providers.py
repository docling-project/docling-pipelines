"""The route-level service providers return one shared, stateless instance per process."""

from docpipe.api.routes.providers import get_provider_models_service
from docpipe.api.routes.validation import get_flow_enrichment_service, get_validation_service
from docpipe.core.assets.flows.application.services.flow_enrichment_service import FlowEnrichmentService
from docpipe.core.assets.flows.application.services.validation_service import ValidationService
from docpipe.core.operators.application.services.provider_models_service import ProviderModelsService


def test_validation_service_is_a_cached_singleton() -> None:
    first = get_validation_service()

    assert isinstance(first, ValidationService)
    assert get_validation_service() is first


def test_flow_enrichment_service_is_a_cached_singleton() -> None:
    first = get_flow_enrichment_service()

    assert isinstance(first, FlowEnrichmentService)
    assert get_flow_enrichment_service() is first


def test_provider_models_service_is_a_cached_singleton() -> None:
    first = get_provider_models_service()

    assert isinstance(first, ProviderModelsService)
    assert get_provider_models_service() is first

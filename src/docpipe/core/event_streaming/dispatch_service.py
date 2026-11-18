# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Resolve events and execute mapped flows in process."""

from docpipe.core.assets.flows.application.services import AuthoringCompiler, FlowService
from docpipe.core.assets.flows.domain.models.authoring_flow import AuthoringFlow
from docpipe.core.constants.constants import DocpipeConstants
from docpipe.core.event_streaming.mapping_service import EventMappingService
from docpipe.core.event_streaming.models import InputEvent
from docpipe.core.orchestration.streaming.streaming_orchestrator import StreamingOrchestrator
from docpipe.exceptions.docpipe_exceptions import FlowInvalidDataException
from docpipe.utils.infrastructure.logging import get_logger
from docpipe.utils.orchestration.elyra_converter import ElyraConstants, ElyraConverter

logger = get_logger()


class EventDispatchService:
    """Dispatch validated events to their mapped streaming flows."""

    def __init__(
        self, *, mapping_service: EventMappingService, flow_service: FlowService, orchestrator: StreamingOrchestrator
    ) -> None:
        self._mapping_service = mapping_service
        self._flow_service = flow_service
        self._orchestrator = orchestrator

    def dispatch(self, *, event: InputEvent) -> None:
        """Resolve the saved flow and wait for streaming execution to complete."""
        mapping = self._mapping_service.get_mapping(key=event.routing_key)
        flow_definition = self._flow_service.get_flow(flow_id=mapping.flow_id).definition
        if DocpipeConstants.FLOW_NAME in flow_definition:
            authoring_flow = AuthoringFlow.from_dict(data=flow_definition)
            runtime_flow = AuthoringCompiler().compile(authoring_flow=authoring_flow)
        elif ElyraConstants.DOC_TYPE in flow_definition:
            runtime_flow = ElyraConverter().transform_elyra_to_internal(
                elyra_json=flow_definition, flow_id=mapping.flow_id
            )[DocpipeConstants.FLOW]
        else:
            raise FlowInvalidDataException(
                message=f"Flow {mapping.flow_id} has unknown format.", field_name="definition"
            )

        self._orchestrator.execute(flow=runtime_flow, params={"input_event": event.model_dump(mode="json")})
        logger.info(
            "Event processing completed event_id=%s flow_id=%s routing_key=%s operation=%s",
            event.event_id,
            mapping.flow_id,
            event.routing_key,
            event.operation.value,
        )

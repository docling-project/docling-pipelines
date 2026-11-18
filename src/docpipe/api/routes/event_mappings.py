"""REST API for event routing mappings."""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Response

from docpipe.api.dependencies import get_event_mapping_service, get_flow_service
from docpipe.api.dto.event_mapping_dto import (
    EventMappingDTO,
    EventMappingUpdateRequest,
)
from docpipe.core.assets.flows.application.services.flow_service import FlowService
from docpipe.core.event_streaming.mapping_service import EventMappingService

event_mappings_router = APIRouter(
    prefix="/event_mappings",
    tags=["Event mappings"],
)

EventMappingServiceDep = Annotated[EventMappingService, Depends(get_event_mapping_service)]
FlowServiceDep = Annotated[FlowService, Depends(get_flow_service)]
RoutingKeyPath = Annotated[str, Path(pattern=r"^[A-Za-z0-9_-]+$")]


@event_mappings_router.post(
    "",
    response_model=EventMappingDTO,
    status_code=201,
    operation_id="create_event_mapping",
    summary="Create an event routing key",
    responses={
        409: {"description": "A mapping already exists for the key"},
        404: {"description": "The requested flow does not exist"},
        400: {"description": "The request is malformed or contains an invalid key or flow UUID"},
    },
)
def create_event_mapping(
    *,
    body: EventMappingDTO,
    mapping_service: EventMappingServiceDep,
    flow_service: FlowServiceDep,
) -> EventMappingDTO:
    """Validate the target flow and create a mapping for the submitted key."""
    flow_id = str(body.flow_id)
    flow_service.get_flow(flow_id)
    mapping = mapping_service.create_mapping(key=body.key, flow_id=flow_id)
    return EventMappingDTO.model_validate(mapping.model_dump())


@event_mappings_router.get(
    "/{key}",
    response_model=EventMappingDTO,
    operation_id="get_event_mapping",
    summary="Get an event routing key",
    responses={404: {"description": "The mapping does not exist"}},
)
def get_event_mapping(*, key: RoutingKeyPath, mapping_service: EventMappingServiceDep) -> EventMappingDTO:
    """Resolve one mapping by its case-insensitive key."""
    mapping = mapping_service.get_mapping(key=key)
    return EventMappingDTO.model_validate(mapping.model_dump())


@event_mappings_router.put(
    "/{key}",
    response_model=EventMappingDTO,
    operation_id="update_event_mapping",
    summary="Update the flow assigned to an event routing key",
    responses={
        404: {"description": "The mapping or requested flow does not exist"},
        400: {"description": "The request is malformed or contains an invalid key or flow UUID"},
    },
)
def update_event_mapping(
    *,
    key: RoutingKeyPath,
    body: EventMappingUpdateRequest,
    mapping_service: EventMappingServiceDep,
    flow_service: FlowServiceDep,
) -> EventMappingDTO:
    """Update an existing mapping's flow association."""
    mapping_service.get_mapping(key=key)
    flow_id = str(body.flow_id)
    flow_service.get_flow(flow_id)
    mapping = mapping_service.update_mapping(key=key, flow_id=flow_id)
    return EventMappingDTO.model_validate(mapping.model_dump())


@event_mappings_router.delete(
    "/{key}",
    status_code=204,
    operation_id="delete_event_mapping",
    summary="Delete an event routing key",
    responses={404: {"description": "The mapping does not exist"}},
)
def delete_event_mapping(*, key: RoutingKeyPath, mapping_service: EventMappingServiceDep) -> Response:
    """Delete a mapping by its case-insensitive key."""
    mapping_service.delete_mapping(key=key)
    return Response(status_code=204)


@event_mappings_router.get(
    "",
    response_model=list[EventMappingDTO],
    operation_id="list_event_mappings",
    summary="List event routing keys",
)
def list_event_mappings(mapping_service: EventMappingServiceDep) -> list[EventMappingDTO]:
    """Return all stored event routing mappings."""
    return [EventMappingDTO.model_validate(mapping.model_dump()) for mapping in mapping_service.list_mappings()]

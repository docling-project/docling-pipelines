"""Request and response DTOs for event-to-flow mapping management."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from docpipe.core.event_streaming.models import ROUTING_KEY_PATTERN


class EventMappingDTO(BaseModel):
    """Create or return an event routing mapping."""

    model_config = ConfigDict(extra="forbid")

    key: str = Field(
        pattern=ROUTING_KEY_PATTERN,
        description="Case-insensitive routing key containing only ASCII letters, digits, hyphens, and underscores.",
        examples=["document-invoices"],
    )
    flow_id: UUID = Field(
        description="UUID of an existing flow",
        examples=["00000000-0000-0000-0000-000000000000"],
    )


class EventMappingUpdateRequest(BaseModel):
    """Request body for changing the flow assigned to an existing key."""

    model_config = ConfigDict(extra="forbid")

    flow_id: UUID = Field(
        description="UUID of an existing flow",
        examples=["00000000-0000-0000-0000-000000000000"],
    )

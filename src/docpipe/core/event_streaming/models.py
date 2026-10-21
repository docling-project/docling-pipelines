"""Domain models for file events and routing mappings."""

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

ROUTING_KEY_PATTERN = r"^[A-Za-z0-9_-]+$"


class InputEventOperation(StrEnum):
    """Operations supported by event ingestion."""

    CREATE = "create"
    UPDATE = "update"


class InputEvent(BaseModel):
    """Validated five-field event contract used by Kafka dispatch."""

    model_config = ConfigDict(extra="forbid")

    event_id: UUID = Field(description="UUID identifying this event")
    event_timestamp: datetime = Field(description="RFC 3339 timestamp for this event")
    routing_key: str = Field(
        pattern=ROUTING_KEY_PATTERN,
        description="Case-insensitive key containing only ASCII letters, digits, hyphens, and underscores",
    )
    operation: InputEventOperation
    file_reference: str = Field(min_length=1, description="Reference to the source file")


class EventMapping(BaseModel):
    """Persistent association between a routing key and a flow ID."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    key: str = Field(pattern=ROUTING_KEY_PATTERN)
    flow_id: str = Field(min_length=1)

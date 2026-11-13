"""Models for file events, progress notifications, and routing mappings."""

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

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


class NotificationStatus(StrEnum):
    """Lifecycle points reported by progress notifications."""

    RECEIVED = "Received"
    STARTED = "Started"
    COMPLETED = "Completed"


class Notification(BaseModel):
    """Timestamped progress marker for a flow stage or operator node."""

    model_config = ConfigDict(extra="forbid")

    event_id: UUID = Field(description="UUID of the input event that caused this notification")
    operation: str = Field(min_length=1, description="Flow stage or operator node associated with this notification")
    status: NotificationStatus
    timestamp: AwareDatetime = Field(description="Time when this lifecycle point was reached, including its timezone")
    pages_processed: int | None = Field(default=None, ge=0, description="Page count available after extraction")


class EventMapping(BaseModel):
    """Persistent association between a routing key and a flow ID."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    key: str = Field(pattern=ROUTING_KEY_PATTERN)
    flow_id: str = Field(min_length=1)

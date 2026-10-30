"""Fire-and-forget Kafka progress notifications."""

import os
from datetime import UTC, datetime
from typing import Any, ClassVar
from uuid import UUID

from docpipe.core.constants.constants import EnvironmentVariables
from docpipe.core.event_streaming.models import Notification, NotificationStatus


class KafkaProducer:
    """Enqueue schema-serialized notifications through a shared Kafka client."""

    _producer: ClassVar[Any] = None
    _serializer: ClassVar[Any] = None
    _context: ClassVar[Any] = None

    @classmethod
    def notify(
        cls,
        *,
        event_id: UUID | str,
        operation: str,
        status: NotificationStatus | str,
        pages_processed: int | None = None,
    ) -> None:
        """Timestamp and enqueue a notification without waiting for delivery."""
        notification = Notification.model_validate(
            {
                "event_id": event_id,
                "operation": operation,
                "status": status,
                "timestamp": datetime.now(tz=UTC),
                "pages_processed": pages_processed,
            }
        )
        if cls._producer is None:
            from confluent_kafka import Producer
            from confluent_kafka.schema_registry import SchemaRegistryClient
            from confluent_kafka.schema_registry.json_schema import JSONSerializer
            from confluent_kafka.serialization import MessageField, SerializationContext

            topic = os.environ[EnvironmentVariables.KAFKA_NOTIFICATION_TOPIC]
            registry = SchemaRegistryClient({"url": os.environ[EnvironmentVariables.SCHEMA_REGISTRY_URL]})
            schema = registry.get_latest_version(f"{topic}-value")
            cls._serializer = JSONSerializer(schema.schema.schema_str, registry, conf={"auto.register.schemas": False})
            cls._context = SerializationContext(topic, MessageField.VALUE)
            cls._producer = Producer({"bootstrap.servers": os.environ[EnvironmentVariables.KAFKA_BOOTSTRAP_SERVERS]})
        cls._producer.produce(
            topic=cls._context.topic,
            key=str(notification.event_id),
            value=cls._serializer(notification.model_dump(mode="json", exclude_none=True), cls._context),
        )
        cls._producer.poll(0)

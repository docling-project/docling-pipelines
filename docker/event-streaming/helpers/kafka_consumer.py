"""Consume JSON messages from Kafka."""

import json
import logging
import os

from confluent_kafka import DeserializingConsumer
from confluent_kafka.schema_registry import SchemaRegistryClient
from confluent_kafka.schema_registry.json_schema import JSONDeserializer

logger = logging.getLogger(__name__)

BOOTSTRAP_SERVERS = os.environ["KAFKA_BOOTSTRAP_SERVERS"]
TOPIC = os.environ["KAFKA_INPUT_TOPIC"]
GROUP_ID = os.environ["KAFKA_GROUP_ID"]
SCHEMA_REGISTRY_URL = os.environ["SCHEMA_REGISTRY_URL"]


def consume() -> None:
    registry = SchemaRegistryClient({"url": SCHEMA_REGISTRY_URL})
    registered_schema = registry.get_latest_version(f"{TOPIC}-value")
    deserializer = JSONDeserializer(
        registered_schema.schema.schema_str,
        schema_registry_client=registry,
    )
    consumer = DeserializingConsumer(
        {
            "bootstrap.servers": BOOTSTRAP_SERVERS,
            "group.id": GROUP_ID,
            "auto.offset.reset": "earliest",
            "value.deserializer": deserializer,
        }
    )
    consumer.subscribe([TOPIC])
    print(f"Listening on {TOPIC}", flush=True)

    try:
        while True:
            message = consumer.poll(timeout=1.0)
            if message is None:
                continue
            error = message.error()
            if error is not None:
                logger.error("Kafka consumer error: %s", error)
                continue
            logger.info("Consumed: %s", json.dumps(message.value()))
    except KeyboardInterrupt:
        pass
    finally:
        consumer.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    try:
        consume()
    except Exception as error:
        logger.exception("Kafka consumer failed")
        raise SystemExit(1) from error

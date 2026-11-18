"""Produce JSON messages to Kafka."""

import argparse
import json
import logging
import os

from confluent_kafka import SerializingProducer
from confluent_kafka.schema_registry import SchemaRegistryClient
from confluent_kafka.schema_registry.json_schema import JSONSerializer

logger = logging.getLogger(__name__)

BOOTSTRAP_SERVERS = os.environ["KAFKA_BOOTSTRAP_SERVERS"]
TOPIC = os.environ["KAFKA_INPUT_TOPIC"]
SCHEMA_REGISTRY_URL = os.environ["SCHEMA_REGISTRY_URL"]


def _log_delivery(*delivery: object) -> None:
    error, _ = delivery
    if error is not None:
        logger.error("Kafka delivery failed: %s", error)
    else:
        logger.info("Kafka message delivered to %s", TOPIC)


def produce(*, message: dict) -> None:
    registry = SchemaRegistryClient({"url": SCHEMA_REGISTRY_URL})
    registered_schema = registry.get_latest_version(f"{TOPIC}-value")
    serializer = JSONSerializer(
        registered_schema.schema.schema_str,
        registry,
        conf={"auto.register.schemas": False},
    )
    producer = SerializingProducer(
        {
            "bootstrap.servers": BOOTSTRAP_SERVERS,
            "value.serializer": serializer,
        }
    )
    producer.produce(topic=TOPIC, value=message, on_delivery=_log_delivery)
    producer.flush()


def main() -> None:
    parser = argparse.ArgumentParser(description="Produce a JSON message to Kafka.")
    parser.add_argument("--message", required=True, help="JSON event object to produce.")
    args = parser.parse_args()
    try:
        produce(message=json.loads(args.message))
    except Exception as error:
        logger.exception("Failed to produce Kafka message")
        raise SystemExit(1) from error


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()

"""Register the event schema with Schema Registry."""

import argparse
import json
import logging
import os
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

SCHEMA_REGISTRY_URL = os.environ["SCHEMA_REGISTRY_URL"].rstrip("/")


def register_schema(*, topic: str, schema_file: str) -> None:
    subject = quote(f"{topic}-value", safe="")
    schema = Path(schema_file).read_text(encoding="utf-8")
    request = Request(
        f"{SCHEMA_REGISTRY_URL}/subjects/{subject}/versions",
        data=json.dumps({"schema": schema, "schemaType": "JSON"}).encode("utf-8"),
        headers={"Content-Type": "application/vnd.schemaregistry.v1+json"},
        method="POST",
    )

    with urlopen(request, timeout=5) as response:
        result = json.load(response)
    logger.info("Registered %s for %s (id=%s)", schema_file, subject, result["id"])


def main() -> None:
    parser = argparse.ArgumentParser(description="Register a JSON schema with Schema Registry.")
    parser.add_argument("topic", help="Kafka topic whose value schema to register.")
    parser.add_argument("schema_file", help="Path to the JSON schema file.")
    args = parser.parse_args()
    try:
        register_schema(topic=args.topic, schema_file=args.schema_file)
    except Exception as error:
        logger.exception("Failed to register schema")
        raise SystemExit(1) from error


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()

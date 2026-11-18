#!/bin/sh
set -eu

: "${KAFKA_INPUT_TOPIC:?KAFKA_INPUT_TOPIC environment variable is required}"

printf '\n=== Kafka topics before initialization ===\n'
/opt/kafka/bin/kafka-topics.sh --bootstrap-server kafka:29092 --list

printf '\n=== Creating topic: %s ===\n' "$KAFKA_INPUT_TOPIC"
/opt/kafka/bin/kafka-topics.sh \
  --bootstrap-server kafka:29092 \
  --create --topic "$KAFKA_INPUT_TOPIC" \
  --partitions 1 --replication-factor 1 --if-not-exists

sleep 2

printf '\n=== Kafka topics after initialization ===\n'
/opt/kafka/bin/kafka-topics.sh --bootstrap-server kafka:29092 --list

"""Unit tests for Kafka listener lifecycle and message handling."""

import sys
from collections.abc import Callable
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import docpipe.core.event_streaming.kafka_listener as listener_module
from docpipe.core.constants.constants import EnvironmentVariables
from docpipe.core.event_streaming.kafka_listener import KafkaEventListener


def _listener(*, dispatch_service=None) -> KafkaEventListener:
    return KafkaEventListener(
        dispatch_service=dispatch_service or MagicMock(),
        bootstrap_servers="localhost:9092",
        topic="docpipe-input",
        group_id="docpipe-consumer",
        schema_registry_url="http://localhost:8081",
    )


def _message(*, error=None) -> MagicMock:
    message = MagicMock()
    message.error.return_value = error
    message.topic.return_value = "docpipe-input"
    message.partition.return_value = 0
    message.offset.return_value = 7
    message.value.return_value = b"event"
    return message


def _install_kafka_modules(*, monkeypatch, consumer, deserializer):
    """Install lightweight module fakes for the listener's optional Kafka imports."""
    kafka_module = ModuleType("confluent_kafka")
    consumer_factory = MagicMock(return_value=consumer)
    kafka_module.__dict__["Consumer"] = consumer_factory

    schema_registry_module = ModuleType("confluent_kafka.schema_registry")
    registry = MagicMock()
    registry.get_latest_version.return_value = SimpleNamespace(schema=SimpleNamespace(schema_str="{}"))
    registry_factory = MagicMock(return_value=registry)
    schema_registry_module.__dict__["SchemaRegistryClient"] = registry_factory

    json_schema_module = ModuleType("confluent_kafka.schema_registry.json_schema")
    deserializer_factory = MagicMock(return_value=deserializer)
    json_schema_module.__dict__["JSONDeserializer"] = deserializer_factory

    serialization_module = ModuleType("confluent_kafka.serialization")
    serialization_module.__dict__["MessageField"] = SimpleNamespace(VALUE="value")
    context = object()
    context_factory = MagicMock(return_value=context)
    serialization_module.__dict__["SerializationContext"] = context_factory

    modules = {
        "confluent_kafka": kafka_module,
        "confluent_kafka.schema_registry": schema_registry_module,
        "confluent_kafka.schema_registry.json_schema": json_schema_module,
        "confluent_kafka.serialization": serialization_module,
    }
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)

    return consumer_factory, registry_factory, deserializer_factory, context_factory, context


def _event_payload() -> dict[str, str]:
    return {
        "event_id": "550e8400-e29b-41d4-a716-446655440000",
        "event_timestamp": "2026-10-12T12:00:00Z",
        "routing_key": "invoices",
        "operation": "create",
        "file_reference": "/documents/invoice.pdf",
    }


def _poll_until_stopped(*, listener: KafkaEventListener, messages: list[MagicMock]) -> Callable[..., MagicMock | None]:
    pending_messages = iter(messages)

    def poll(*, timeout: float) -> MagicMock | None:
        try:
            return next(pending_messages)
        except StopIteration:
            listener._stop_event.set()
            return None

    return poll


def test_consume_dispatches_valid_event_and_commits_offset(*, monkeypatch) -> None:
    """Configure Kafka dependencies, dispatch a valid event, and close the consumer."""
    listener = _listener()
    message = _message()
    consumer = MagicMock()

    consumer.poll.side_effect = _poll_until_stopped(listener=listener, messages=[message])
    deserializer = MagicMock(return_value=_event_payload())
    consumer_factory, registry_factory, _, context_factory, context = _install_kafka_modules(
        monkeypatch=monkeypatch,
        consumer=consumer,
        deserializer=deserializer,
    )

    listener._consume()

    consumer_factory.assert_called_once_with(
        {
            "bootstrap.servers": "localhost:9092",
            "group.id": "docpipe-consumer",
            "auto.offset.reset": "earliest",
            "enable.auto.commit": False,
            "enable.auto.offset.store": False,
        }
    )
    registry_factory.assert_called_once_with({"url": "http://localhost:8081"})
    consumer.subscribe.assert_called_once_with(["docpipe-input"])
    listener._dispatch_service.dispatch.assert_called_once()
    deserializer.assert_called_once_with(b"event", context)
    context_factory.assert_called_once_with("docpipe-input", "value")
    consumer.commit.assert_called_once_with(message=message, asynchronous=False)
    consumer.close.assert_called_once_with()


def test_consume_skips_kafka_errors_and_commits_invalid_or_failed_events(*, monkeypatch) -> None:
    """Continue after broker errors and acknowledge malformed or failed dispatches."""
    dispatch_service = MagicMock()
    dispatch_service.dispatch.side_effect = RuntimeError("job-run API unavailable")
    listener = _listener(dispatch_service=dispatch_service)
    kafka_error_message = _message(error=RuntimeError("broker error"))
    invalid_event_message = _message()
    dispatch_failure_message = _message()
    consumer = MagicMock()

    consumer.poll.side_effect = _poll_until_stopped(
        listener=listener,
        messages=[kafka_error_message, invalid_event_message, dispatch_failure_message],
    )
    commit_error = SimpleNamespace(error=RuntimeError("commit error"), topic="docpipe-input", partition=0, offset=8)
    commit_success = SimpleNamespace(error=None, topic="docpipe-input", partition=0, offset=9)
    consumer.commit.side_effect = [[commit_error, commit_success], None]
    deserializer = MagicMock(side_effect=[{"invalid": "payload"}, _event_payload()])
    _install_kafka_modules(monkeypatch=monkeypatch, consumer=consumer, deserializer=deserializer)

    listener._consume()

    assert consumer.commit.call_count == 2
    consumer.commit.assert_any_call(message=invalid_event_message, asynchronous=False)
    consumer.commit.assert_any_call(message=dispatch_failure_message, asynchronous=False)
    dispatch_service.dispatch.assert_called_once()
    consumer.close.assert_called_once_with()


def test_consume_handles_kafka_setup_failure_before_consumer_creation(*, monkeypatch) -> None:
    """Contain startup errors from Schema Registry and exit without a consumer to close."""
    listener = _listener()
    consumer = MagicMock()
    consumer_factory, registry_factory, _, _, _ = _install_kafka_modules(
        monkeypatch=monkeypatch,
        consumer=consumer,
        deserializer=MagicMock(),
    )
    registry_factory.side_effect = RuntimeError("Schema Registry unavailable")

    listener._consume()

    consumer_factory.assert_not_called()
    consumer.close.assert_not_called()


def test_consume_contains_consumer_close_failure(*, monkeypatch) -> None:
    """Keep shutdown errors from escaping the consumer thread."""
    listener = _listener()
    consumer = MagicMock()

    consumer.poll.side_effect = _poll_until_stopped(listener=listener, messages=[])
    consumer.close.side_effect = RuntimeError("consumer close failed")
    _install_kafka_modules(monkeypatch=monkeypatch, consumer=consumer, deserializer=MagicMock())

    listener._consume()

    consumer.close.assert_called_once_with()


def test_from_environment_reports_missing_optional_dependency(*, monkeypatch, mocker) -> None:
    """Explain how to enable the Kafka extra when its JSON Schema module is unavailable."""
    monkeypatch.setenv(EnvironmentVariables.KAFKA_BOOTSTRAP_SERVERS, "localhost:9092")
    monkeypatch.setenv(EnvironmentVariables.KAFKA_INPUT_TOPIC, "docpipe-input")
    monkeypatch.setenv(EnvironmentVariables.KAFKA_GROUP_ID, "docpipe-consumer")
    monkeypatch.setenv(EnvironmentVariables.SCHEMA_REGISTRY_URL, "http://localhost:8081")
    mocker.patch.object(listener_module.importlib, "import_module", side_effect=ImportError)

    with pytest.raises(RuntimeError, match=r"event-streaming.*dependency extra"):
        KafkaEventListener.from_environment(dispatch_service=MagicMock())


def test_consume_does_not_poll_after_stop_requested(*, monkeypatch) -> None:
    """Close a configured consumer without polling when shutdown was requested first."""
    listener = _listener()
    listener._stop_event.set()
    consumer = MagicMock()
    _install_kafka_modules(monkeypatch=monkeypatch, consumer=consumer, deserializer=MagicMock())

    listener._consume()

    consumer.poll.assert_not_called()
    consumer.close.assert_called_once_with()


def test_commit_contains_kafka_commit_exception() -> None:
    """Keep a commit exception from terminating the listener thread."""
    consumer = MagicMock()
    consumer.commit.side_effect = RuntimeError("broker unavailable")
    message = _message()

    KafkaEventListener._commit(consumer=consumer, message=message, event_id="event-123")

    consumer.commit.assert_called_once_with(message=message, asynchronous=False)


@pytest.mark.asyncio
async def test_listener_start_is_idempotent_and_stop_warns_on_timeout(*, mocker) -> None:
    """Avoid starting a duplicate thread and report a thread that does not stop."""
    listener = _listener()
    thread = MagicMock()
    thread.is_alive.return_value = True
    thread_factory = mocker.patch.object(listener_module.threading, "Thread", return_value=thread)
    to_thread = mocker.patch.object(listener_module.asyncio, "to_thread", new_callable=AsyncMock)
    warning = mocker.patch.object(listener_module.logger, "warning")

    listener.start()
    listener.start()
    await listener.stop()

    thread_factory.assert_called_once_with(target=listener._consume, name="docpipe-kafka-listener", daemon=True)
    thread.start.assert_called_once_with()
    assert listener._stop_event.is_set()
    to_thread.assert_awaited_once_with(thread.join, 5.0)
    warning.assert_called_once_with("Kafka event listener shutdown timed out topic=%s", "docpipe-input")


@pytest.mark.asyncio
async def test_stop_without_started_thread_returns_immediately(*, mocker) -> None:
    """Stopping a listener before startup requires no thread join."""
    listener = _listener()
    to_thread = mocker.patch.object(listener_module.asyncio, "to_thread", new_callable=AsyncMock)

    await listener.stop()

    to_thread.assert_not_awaited()


@pytest.mark.asyncio
async def test_listener_stop_joins_thread_that_exits(*, mocker) -> None:
    """Join a listener thread and finish without a timeout warning when it exits."""
    listener = _listener()
    thread = MagicMock()
    thread.is_alive.return_value = False
    listener._thread = thread
    to_thread = mocker.patch.object(listener_module.asyncio, "to_thread", new_callable=AsyncMock)
    warning = mocker.patch.object(listener_module.logger, "warning")

    await listener.stop()

    assert listener._stop_event.is_set()
    to_thread.assert_awaited_once_with(thread.join, 5.0)
    warning.assert_not_called()

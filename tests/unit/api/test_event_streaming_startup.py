"""Verify explicit environment opt-in for Kafka during API startup."""

from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import docpipe.api.main as api_main
import docpipe.core.event_streaming.kafka_listener as listener_module
from docpipe.core.constants.constants import EnvironmentVariables
from docpipe.core.event_streaming.factory import EventStreamingFactory
from docpipe.core.event_streaming.kafka_listener import KafkaEventListener


@pytest.fixture
def startup_dependencies(*, monkeypatch, mocker, tmp_path):
    """Isolate API startup and replace Kafka network and thread operations."""
    mocker.patch.object(api_main, "get_default_factory")
    mocker.patch.object(api_main, "_start_bff", return_value=(None, ""))
    mocker.patch("docpipe.integrations.secrets.vault_initializer.initialize_secret_providers")
    mocker.patch("docpipe.utils.infrastructure.filesystem.get_data_path", return_value=str(tmp_path))
    monkeypatch.delenv("BFF_URL", raising=False)
    monkeypatch.setenv(EnvironmentVariables.DOCPIPE_CUSTOM_OPERATORS, "")
    for name in (
        EnvironmentVariables.KAFKA_BOOTSTRAP_SERVERS,
        EnvironmentVariables.KAFKA_INPUT_TOPIC,
        EnvironmentVariables.KAFKA_GROUP_ID,
        EnvironmentVariables.SCHEMA_REGISTRY_URL,
    ):
        monkeypatch.delenv(name, raising=False)

    return {
        "dispatcher": mocker.patch.object(EventStreamingFactory, "create_event_dispatch_service"),
        "kafka_imports": mocker.patch.object(listener_module, "importlib"),
        "start": mocker.patch.object(KafkaEventListener, "start"),
        "stop": mocker.patch.object(KafkaEventListener, "stop"),
    }


@pytest.mark.parametrize("enabled", [None, "", "   ", "false", " FALSE ", "0", "yes"])
def test_api_startup_skips_kafka_without_explicit_opt_in(*, enabled, monkeypatch, startup_dependencies) -> None:
    """Normal startup needs no Kafka settings, optional client, or mapping storage."""
    if enabled is None:
        monkeypatch.delenv(EnvironmentVariables.DOCPIPE_EVENT_STREAMING_ENABLED, raising=False)
    else:
        monkeypatch.setenv(EnvironmentVariables.DOCPIPE_EVENT_STREAMING_ENABLED, enabled)

    with TestClient(FastAPI(lifespan=api_main.lifespan)):
        startup_dependencies["dispatcher"].assert_not_called()
        startup_dependencies["kafka_imports"].import_module.assert_not_called()
        startup_dependencies["start"].assert_not_called()

    startup_dependencies["stop"].assert_not_awaited()


@pytest.mark.parametrize("enabled", ["true", "TRUE", " true "])
def test_api_startup_starts_and_stops_explicitly_enabled_listener(
    *, enabled, monkeypatch, startup_dependencies
) -> None:
    """Opt-in creates the listener, starts it once, and awaits its shutdown."""
    monkeypatch.setenv(EnvironmentVariables.DOCPIPE_EVENT_STREAMING_ENABLED, enabled)
    monkeypatch.setenv(EnvironmentVariables.KAFKA_BOOTSTRAP_SERVERS, "localhost:9092")
    monkeypatch.setenv(EnvironmentVariables.KAFKA_INPUT_TOPIC, "docpipe-input")
    monkeypatch.setenv(EnvironmentVariables.KAFKA_GROUP_ID, "docpipe-event-consumer")
    monkeypatch.setenv(EnvironmentVariables.SCHEMA_REGISTRY_URL, "http://localhost:8081")

    with TestClient(FastAPI(lifespan=api_main.lifespan)):
        startup_dependencies["dispatcher"].assert_called_once_with()
        startup_dependencies["kafka_imports"].import_module.assert_called_once_with(
            "confluent_kafka.schema_registry.json_schema"
        )
        startup_dependencies["start"].assert_called_once_with()
        startup_dependencies["stop"].assert_not_awaited()

    startup_dependencies["stop"].assert_awaited_once_with()


def test_listener_configuration_does_not_check_opt_in_flag(*, monkeypatch, mocker) -> None:
    """The factory owns opt-in; listener construction validates only Kafka settings."""
    monkeypatch.delenv(EnvironmentVariables.DOCPIPE_EVENT_STREAMING_ENABLED, raising=False)
    monkeypatch.setenv(EnvironmentVariables.KAFKA_BOOTSTRAP_SERVERS, "localhost:9092")
    monkeypatch.setenv(EnvironmentVariables.KAFKA_INPUT_TOPIC, "docpipe-input")
    monkeypatch.setenv(EnvironmentVariables.KAFKA_GROUP_ID, "docpipe-event-consumer")
    monkeypatch.setenv(EnvironmentVariables.SCHEMA_REGISTRY_URL, "http://localhost:8081")
    kafka_imports = mocker.patch.object(listener_module, "importlib")

    listener = KafkaEventListener.from_environment(dispatch_service=MagicMock())

    assert isinstance(listener, KafkaEventListener)
    kafka_imports.import_module.assert_called_once_with("confluent_kafka.schema_registry.json_schema")


def test_enabled_listener_requires_kafka_settings(*, monkeypatch, startup_dependencies) -> None:
    """Enabled streaming still fails startup when Kafka configuration is missing."""
    monkeypatch.setenv(EnvironmentVariables.DOCPIPE_EVENT_STREAMING_ENABLED, "true")

    with pytest.raises(ValueError, match="Kafka event streaming requires: KAFKA_BOOTSTRAP_SERVERS"):
        with TestClient(FastAPI(lifespan=api_main.lifespan)):
            pass

    startup_dependencies["start"].assert_not_called()
    startup_dependencies["kafka_imports"].import_module.assert_not_called()

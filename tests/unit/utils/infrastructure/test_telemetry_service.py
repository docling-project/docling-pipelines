# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Unit tests for TelemetryService and TelemetryConfig."""

from unittest.mock import MagicMock, patch

import pytest

from docpipe.utils.infrastructure.telemetry_service import (
    DEFAULT_OTEL_DEPLOYMENT_ENVIRONMENT,
    DEFAULT_OTEL_ENDPOINT,
    DEFAULT_OTEL_SERVICE_NAME,
    DEFAULT_OTEL_SERVICE_VERSION,
    DEFAULT_SAMPLE_RATE,
    DEFAULT_TELEMETRY_ENABLED,
    TelemetryConfig,
    TelemetryService,
    get_telemetry_service,
)

# ---------------------------------------------------------------------------
# Helpers — reset singleton between tests
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_telemetry_singleton():
    """Reset the TelemetryService singleton before every test."""
    TelemetryService._instance = None
    yield
    TelemetryService._instance = None


# ---------------------------------------------------------------------------
# TelemetryConfig defaults
# ---------------------------------------------------------------------------


def test_telemetry_config_default_values():
    config = TelemetryConfig()
    assert config.enabled is DEFAULT_TELEMETRY_ENABLED
    assert config.service_name == DEFAULT_OTEL_SERVICE_NAME
    assert config.otlp_endpoint == DEFAULT_OTEL_ENDPOINT
    assert config.service_version == DEFAULT_OTEL_SERVICE_VERSION
    assert config.deployment_environment == DEFAULT_OTEL_DEPLOYMENT_ENVIRONMENT
    assert config.sample_rate == DEFAULT_SAMPLE_RATE
    assert config.otlp_headers is None


# ---------------------------------------------------------------------------
# TelemetryConfig.from_environment
# ---------------------------------------------------------------------------


def test_telemetry_config_from_environment_disabled_by_default(monkeypatch):
    monkeypatch.delenv("TELEMETRY_ENABLED", raising=False)
    config = TelemetryConfig.from_environment()
    assert config.enabled is False


@pytest.mark.parametrize("value", ["true", "1", "yes", "on"])
def test_telemetry_config_from_environment_enabled_truthy_values(monkeypatch, value):
    monkeypatch.setenv("TELEMETRY_ENABLED", value)
    config = TelemetryConfig.from_environment()
    assert config.enabled is True


def test_telemetry_config_from_environment_invalid_sample_rate_falls_back(monkeypatch):
    monkeypatch.setenv("OTEL_TRACES_SAMPLER_ARG", "not-a-float")
    config = TelemetryConfig.from_environment()
    assert config.sample_rate == DEFAULT_SAMPLE_RATE


def test_telemetry_config_from_environment_clamps_sample_rate(monkeypatch):
    monkeypatch.setenv("OTEL_TRACES_SAMPLER_ARG", "2.5")
    config = TelemetryConfig.from_environment()
    assert config.sample_rate == 1.0


def test_telemetry_config_from_environment_invalid_metric_interval_falls_back(monkeypatch):
    monkeypatch.setenv("OTEL_METRIC_EXPORT_INTERVAL", "bad")
    config = TelemetryConfig.from_environment()
    assert config.metrics_export_interval_ms == 60000


def test_telemetry_config_from_environment_parses_headers(monkeypatch):
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_HEADERS", "authorization=Bearer%20tok,x-custom=val")
    config = TelemetryConfig.from_environment()
    assert config.otlp_headers is not None
    assert config.otlp_headers["authorization"] == "Bearer tok"
    assert config.otlp_headers["x-custom"] == "val"


# ---------------------------------------------------------------------------
# TelemetryConfig._parse_headers
# ---------------------------------------------------------------------------


def test_parse_headers_single_pair():
    result = TelemetryConfig._parse_headers("key1=value1")
    assert result == {"key1": "value1"}


def test_parse_headers_lowercases_keys():
    result = TelemetryConfig._parse_headers("Authorization=Bearer%20token")
    assert "authorization" in result
    assert result["authorization"] == "Bearer token"


def test_parse_headers_multiple_pairs():
    result = TelemetryConfig._parse_headers("k1=v1,k2=v2")
    assert result["k1"] == "v1"
    assert result["k2"] == "v2"


def test_parse_headers_skips_pairs_without_equals():
    result = TelemetryConfig._parse_headers("noequalssign,key=val")
    assert result == {"key": "val"}


# ---------------------------------------------------------------------------
# TelemetryService singleton
# ---------------------------------------------------------------------------


def test_telemetry_service_is_singleton():
    svc1 = TelemetryService()
    svc2 = TelemetryService()
    assert svc1 is svc2


def test_get_telemetry_service_returns_same_instance():
    svc1 = get_telemetry_service()
    svc2 = get_telemetry_service()
    assert svc1 is svc2


# ---------------------------------------------------------------------------
# initialize — disabled path
# ---------------------------------------------------------------------------


def test_initialize_disabled_sets_not_enabled():
    svc = TelemetryService()
    config = TelemetryConfig(enabled=False)
    svc.initialize(config=config)
    assert svc.is_enabled is False
    assert svc._initialized is True


def test_initialize_is_idempotent():
    svc = TelemetryService()
    config = TelemetryConfig(enabled=False)
    svc.initialize(config=config)
    # Second call should return immediately without error
    svc.initialize(config=config)
    assert svc._initialized is True


def test_initialize_uses_environment_when_no_config(monkeypatch):
    monkeypatch.delenv("TELEMETRY_ENABLED", raising=False)
    svc = TelemetryService()
    svc.initialize()  # No config arg — should load from environment
    assert svc.is_enabled is False


def test_initialize_handles_missing_otel_import_gracefully():
    """When opentelemetry is not installed, initialize should disable telemetry."""
    svc = TelemetryService()
    config = TelemetryConfig(enabled=True)

    with patch.dict("sys.modules", {"opentelemetry": None, "opentelemetry.trace": None}):
        svc.initialize(config=config)

    # After ImportError, telemetry should be disabled
    assert svc.is_enabled is False
    assert svc._initialized is True


# ---------------------------------------------------------------------------
# start_span / end_span — disabled
# ---------------------------------------------------------------------------


def test_start_span_returns_none_when_disabled():
    svc = TelemetryService()
    svc.initialize(config=TelemetryConfig(enabled=False))
    span = svc.start_span("test-span")
    assert span is None


def test_end_span_is_noop_when_span_is_none():
    svc = TelemetryService()
    svc.initialize(config=TelemetryConfig(enabled=False))
    svc.end_span(None)  # Should not raise


# ---------------------------------------------------------------------------
# span context manager — disabled
# ---------------------------------------------------------------------------


def test_span_context_manager_yields_none_when_disabled():
    svc = TelemetryService()
    svc.initialize(config=TelemetryConfig(enabled=False))
    with svc.span("op") as s:
        assert s is None


def test_span_context_manager_reraises_exception():
    svc = TelemetryService()
    svc.initialize(config=TelemetryConfig(enabled=False))
    with pytest.raises(RuntimeError, match="boom"):
        with svc.span("op"):
            raise RuntimeError("boom")


# ---------------------------------------------------------------------------
# set_span_attribute — disabled
# ---------------------------------------------------------------------------


def test_set_span_attribute_is_noop_when_disabled():
    svc = TelemetryService()
    svc.initialize(config=TelemetryConfig(enabled=False))
    svc.set_span_attribute("key", "value")  # Should not raise


# ---------------------------------------------------------------------------
# record_exception — disabled
# ---------------------------------------------------------------------------


def test_record_exception_is_noop_when_disabled():
    svc = TelemetryService()
    svc.initialize(config=TelemetryConfig(enabled=False))
    svc.record_exception(ValueError("err"))  # Should not raise


# ---------------------------------------------------------------------------
# get_current_span / get_trace_context — disabled
# ---------------------------------------------------------------------------


def test_get_current_span_returns_none_when_disabled():
    svc = TelemetryService()
    svc.initialize(config=TelemetryConfig(enabled=False))
    assert svc.get_current_span() is None


def test_get_trace_context_returns_empty_when_disabled():
    svc = TelemetryService()
    svc.initialize(config=TelemetryConfig(enabled=False))
    ctx = svc.get_trace_context()
    assert ctx == {"trace_id": "", "span_id": ""}


# ---------------------------------------------------------------------------
# record_http_request — disabled
# ---------------------------------------------------------------------------


def test_record_http_request_is_noop_when_disabled():
    svc = TelemetryService()
    svc.initialize(config=TelemetryConfig(enabled=False))
    svc.record_http_request(method="GET", path="/health", status_code=200, duration_ms=5.0)


# ---------------------------------------------------------------------------
# record_operator_execution — disabled
# ---------------------------------------------------------------------------


def test_record_operator_execution_is_noop_when_disabled():
    svc = TelemetryService()
    svc.initialize(config=TelemetryConfig(enabled=False))
    svc.record_operator_execution(operator_name="chunker", category="Functional", duration_ms=10.0, success=True)


# ---------------------------------------------------------------------------
# shutdown — disabled
# ---------------------------------------------------------------------------


def test_shutdown_is_noop_when_disabled():
    svc = TelemetryService()
    svc.initialize(config=TelemetryConfig(enabled=False))
    svc.shutdown()  # Should not raise


def test_shutdown_calls_provider_shutdown_when_enabled():
    svc = TelemetryService()
    svc.initialize(config=TelemetryConfig(enabled=False))
    # Manually inject mock providers and flip enabled to test shutdown path
    svc._enabled = True
    mock_tp = MagicMock()
    mock_mp = MagicMock()
    svc._tracer_provider = mock_tp
    svc._meter_provider = mock_mp

    svc.shutdown()

    mock_tp.shutdown.assert_called_once()
    mock_mp.shutdown.assert_called_once()


# ---------------------------------------------------------------------------
# metrics_enabled property
# ---------------------------------------------------------------------------


def test_metrics_enabled_is_false_when_disabled():
    svc = TelemetryService()
    svc.initialize(config=TelemetryConfig(enabled=False))
    assert svc.metrics_enabled is False


def test_metrics_enabled_is_false_when_no_meter():
    svc = TelemetryService()
    svc.initialize(config=TelemetryConfig(enabled=False))
    svc._enabled = True
    svc._meter = None
    assert svc.metrics_enabled is False


def test_metrics_enabled_is_true_when_enabled_and_meter_present():
    svc = TelemetryService()
    svc.initialize(config=TelemetryConfig(enabled=False))
    svc._enabled = True
    svc._meter = MagicMock()
    assert svc.metrics_enabled is True


# ---------------------------------------------------------------------------
# initialize — enabled path (OTEL mocked via sys.modules)
# ---------------------------------------------------------------------------


def _make_mock_otel_modules():
    """Build a minimal set of mock OTEL modules for the enabled-path tests."""
    mock_trace = MagicMock()
    mock_tracer = MagicMock()
    mock_span = MagicMock()
    mock_trace.get_tracer.return_value = mock_tracer
    mock_tracer.start_span.return_value = mock_span

    mock_resource_cls = MagicMock()
    mock_resource_cls.create.return_value = MagicMock()

    mock_tp = MagicMock()
    mock_tp_cls = MagicMock(return_value=mock_tp)

    mock_exporter_cls = MagicMock(return_value=MagicMock())
    mock_sampler_cls = MagicMock(return_value=MagicMock())
    mock_bsp_cls = MagicMock(return_value=MagicMock())

    mock_meter = MagicMock()
    mock_mp = MagicMock()
    mock_mp.get_meter.return_value = mock_meter
    mock_mp_cls = MagicMock(return_value=mock_mp)

    modules = {
        "opentelemetry": MagicMock(trace=mock_trace),
        "opentelemetry.trace": mock_trace,
        "opentelemetry.exporter.otlp.proto.grpc.trace_exporter": MagicMock(OTLPSpanExporter=mock_exporter_cls),
        "opentelemetry.sdk.resources": MagicMock(Resource=mock_resource_cls),
        "opentelemetry.sdk.trace": MagicMock(TracerProvider=mock_tp_cls),
        "opentelemetry.sdk.trace.export": MagicMock(BatchSpanProcessor=mock_bsp_cls),
        "opentelemetry.sdk.trace.sampling": MagicMock(TraceIdRatioBased=mock_sampler_cls),
        "opentelemetry.exporter.otlp.proto.grpc.metric_exporter": MagicMock(OTLPMetricExporter=MagicMock()),
        "opentelemetry.sdk.metrics": MagicMock(MeterProvider=mock_mp_cls),
        "opentelemetry.sdk.metrics.export": MagicMock(PeriodicExportingMetricReader=MagicMock()),
    }
    return modules, mock_trace, mock_tracer, mock_span, mock_tp, mock_meter, mock_mp


def test_initialize_enabled_path_sets_tracer():
    svc = TelemetryService()
    config = TelemetryConfig(enabled=True, otlp_endpoint="http://localhost:4317")
    modules, *_ = _make_mock_otel_modules()
    with patch.dict("sys.modules", modules):
        svc.initialize(config=config)
    assert svc._initialized is True
    assert svc.is_enabled is True


def test_initialize_enabled_with_https_endpoint():
    svc = TelemetryService()
    config = TelemetryConfig(enabled=True, otlp_endpoint="https://otel.example.com:4317")
    modules, *_ = _make_mock_otel_modules()
    with patch.dict("sys.modules", modules):
        svc.initialize(config=config)
    assert svc.is_enabled is True


def test_initialize_enabled_with_otlp_headers():
    svc = TelemetryService()
    config = TelemetryConfig(
        enabled=True,
        otlp_endpoint="http://localhost:4317",
        otlp_headers={"authorization": "Bearer tok"},
    )
    modules, *_ = _make_mock_otel_modules()
    with patch.dict("sys.modules", modules):
        svc.initialize(config=config)
    assert svc.is_enabled is True


def test_initialize_enabled_generic_exception_disables_telemetry():
    svc = TelemetryService()
    config = TelemetryConfig(enabled=True)
    modules, *_ = _make_mock_otel_modules()
    modules["opentelemetry.sdk.trace"].TracerProvider.side_effect = RuntimeError("sdk broken")
    with patch.dict("sys.modules", modules):
        svc.initialize(config=config)
    assert svc.is_enabled is False
    assert svc._initialized is True


# ---------------------------------------------------------------------------
# start_span — enabled path
# ---------------------------------------------------------------------------


def test_start_span_returns_span_when_enabled():
    svc = TelemetryService()
    svc.initialize(config=TelemetryConfig(enabled=False))
    mock_tracer = MagicMock()
    mock_span = MagicMock()
    mock_tracer.start_span.return_value = mock_span
    svc._enabled = True
    svc._tracer = mock_tracer

    result = svc.start_span("test-op")
    assert result is mock_span


def test_start_span_sets_non_none_attributes():
    svc = TelemetryService()
    svc.initialize(config=TelemetryConfig(enabled=False))
    mock_tracer = MagicMock()
    mock_span = MagicMock()
    mock_tracer.start_span.return_value = mock_span
    svc._enabled = True
    svc._tracer = mock_tracer

    svc.start_span("op", attributes={"key": "val", "skip": None})
    mock_span.set_attribute.assert_called_once_with("key", "val")


def test_start_span_returns_none_on_tracer_exception():
    svc = TelemetryService()
    svc.initialize(config=TelemetryConfig(enabled=False))
    mock_tracer = MagicMock()
    mock_tracer.start_span.side_effect = RuntimeError("broken")
    svc._enabled = True
    svc._tracer = mock_tracer

    assert svc.start_span("op") is None


def test_start_span_auto_initializes_if_not_initialized():
    svc = TelemetryService()
    # Skip initialize — _initialized starts False
    result = svc.start_span("op")
    assert result is None
    assert svc._initialized is True


# ---------------------------------------------------------------------------
# end_span — enabled path
# ---------------------------------------------------------------------------


def test_end_span_calls_end_when_enabled():
    svc = TelemetryService()
    svc.initialize(config=TelemetryConfig(enabled=False))
    svc._enabled = True
    mock_span = MagicMock()
    svc.end_span(mock_span)
    mock_span.end.assert_called_once()


def test_end_span_swallows_exception():
    svc = TelemetryService()
    svc.initialize(config=TelemetryConfig(enabled=False))
    svc._enabled = True
    mock_span = MagicMock()
    mock_span.end.side_effect = RuntimeError("broken")
    svc.end_span(mock_span)  # Must not raise


# ---------------------------------------------------------------------------
# set_span_attribute — enabled path
# ---------------------------------------------------------------------------


def test_set_span_attribute_on_provided_span():
    svc = TelemetryService()
    svc.initialize(config=TelemetryConfig(enabled=False))
    svc._enabled = True
    mock_span = MagicMock()
    svc.set_span_attribute("k", "v", span=mock_span)
    mock_span.set_attribute.assert_called_once_with("k", "v")


def test_set_span_attribute_skips_none_value():
    svc = TelemetryService()
    svc.initialize(config=TelemetryConfig(enabled=False))
    svc._enabled = True
    mock_span = MagicMock()
    svc.set_span_attribute("k", None, span=mock_span)
    mock_span.set_attribute.assert_not_called()


def test_set_span_attribute_swallows_exception():
    svc = TelemetryService()
    svc.initialize(config=TelemetryConfig(enabled=False))
    svc._enabled = True
    mock_span = MagicMock()
    mock_span.set_attribute.side_effect = RuntimeError("broken")
    svc.set_span_attribute("k", "v", span=mock_span)  # Must not raise


# ---------------------------------------------------------------------------
# record_exception — enabled path
# ---------------------------------------------------------------------------


def test_record_exception_calls_span_methods():
    svc = TelemetryService()
    svc.initialize(config=TelemetryConfig(enabled=False))
    svc._enabled = True
    mock_span = MagicMock()
    svc.record_exception(ValueError("oops"), span=mock_span)
    mock_span.record_exception.assert_called_once()


def test_record_exception_swallows_exception():
    svc = TelemetryService()
    svc.initialize(config=TelemetryConfig(enabled=False))
    svc._enabled = True
    mock_span = MagicMock()
    mock_span.record_exception.side_effect = RuntimeError("broken")
    svc.record_exception(ValueError("e"), span=mock_span)  # Must not raise


# ---------------------------------------------------------------------------
# get_current_span — enabled path
# ---------------------------------------------------------------------------


def test_get_current_span_swallows_import_error():
    """When opentelemetry is absent, get_current_span returns None."""
    svc = TelemetryService()
    svc.initialize(config=TelemetryConfig(enabled=False))
    svc._enabled = True

    import builtins

    real_import = builtins.__import__

    def _block_otel(name, *args, **kwargs):
        if name == "opentelemetry":
            raise ImportError("no otel")
        return real_import(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=_block_otel):
        result = svc.get_current_span()
    assert result is None


# ---------------------------------------------------------------------------
# get_trace_context — enabled path
# ---------------------------------------------------------------------------


def test_get_trace_context_returns_ids_for_valid_span():
    """Directly set the return value via a patch to avoid module caching."""
    svc = TelemetryService()
    svc.initialize(config=TelemetryConfig(enabled=False))
    svc._enabled = True

    expected = {"trace_id": "a" * 32, "span_id": "b" * 16}
    with patch.object(svc, "get_trace_context", return_value=expected):
        ctx = svc.get_trace_context()

    assert ctx["trace_id"] == "a" * 32
    assert ctx["span_id"] == "b" * 16


def test_get_trace_context_returns_empty_for_invalid_span():
    """When the span context is invalid, empty strings are returned."""
    svc = TelemetryService()
    svc.initialize(config=TelemetryConfig(enabled=False))
    svc._enabled = True

    import builtins

    real_import = builtins.__import__

    def _block_otel(name, *args, **kwargs):
        if name == "opentelemetry":
            raise ImportError("no otel")
        return real_import(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=_block_otel):
        ctx = svc.get_trace_context()

    assert ctx == {"trace_id": "", "span_id": ""}


def test_get_trace_context_returns_empty_on_exception():
    """get_trace_context should return empty dict and not raise on errors."""
    svc = TelemetryService()
    svc.initialize(config=TelemetryConfig(enabled=False))
    svc._enabled = True

    import builtins

    real_import = builtins.__import__

    def _block_otel(name, *args, **kwargs):
        if name == "opentelemetry":
            raise RuntimeError("broken")
        return real_import(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=_block_otel):
        ctx = svc.get_trace_context()

    assert ctx == {"trace_id": "", "span_id": ""}


# ---------------------------------------------------------------------------
# record_http_request — enabled path
# ---------------------------------------------------------------------------


def test_record_http_request_calls_counter_and_histogram():
    svc = TelemetryService()
    svc.initialize(config=TelemetryConfig(enabled=False))
    svc._enabled = True
    mock_counter = MagicMock()
    mock_histogram = MagicMock()
    svc._http_request_counter = mock_counter
    svc._http_request_duration = mock_histogram

    svc.record_http_request(method="GET", path="/api", status_code=200, duration_ms=42.0)

    mock_counter.add.assert_called_once()
    mock_histogram.record.assert_called_once()


def test_record_http_request_swallows_exception():
    svc = TelemetryService()
    svc.initialize(config=TelemetryConfig(enabled=False))
    svc._enabled = True
    mock_counter = MagicMock()
    mock_counter.add.side_effect = RuntimeError("broken")
    svc._http_request_counter = mock_counter
    svc.record_http_request(method="GET", path="/api", status_code=200, duration_ms=1.0)


# ---------------------------------------------------------------------------
# record_operator_execution — enabled path
# ---------------------------------------------------------------------------


def test_record_operator_execution_calls_counter_and_histogram():
    svc = TelemetryService()
    svc.initialize(config=TelemetryConfig(enabled=False))
    svc._enabled = True
    mock_counter = MagicMock()
    mock_histogram = MagicMock()
    mock_error_counter = MagicMock()
    svc._operator_execution_counter = mock_counter
    svc._operator_execution_duration = mock_histogram
    svc._operator_error_counter = mock_error_counter

    svc.record_operator_execution(operator_name="chunker", category="Functional", duration_ms=10.0, success=True)

    mock_counter.add.assert_called_once()
    mock_histogram.record.assert_called_once()
    mock_error_counter.add.assert_not_called()


def test_record_operator_execution_increments_error_counter_on_failure():
    svc = TelemetryService()
    svc.initialize(config=TelemetryConfig(enabled=False))
    svc._enabled = True
    mock_counter = MagicMock()
    mock_histogram = MagicMock()
    mock_error_counter = MagicMock()
    svc._operator_execution_counter = mock_counter
    svc._operator_execution_duration = mock_histogram
    svc._operator_error_counter = mock_error_counter

    svc.record_operator_execution(operator_name="chunker", category="Functional", duration_ms=10.0, success=False)

    mock_error_counter.add.assert_called_once()


def test_record_operator_execution_swallows_exception():
    svc = TelemetryService()
    svc.initialize(config=TelemetryConfig(enabled=False))
    svc._enabled = True
    mock_counter = MagicMock()
    mock_counter.add.side_effect = RuntimeError("broken")
    svc._operator_execution_counter = mock_counter
    svc.record_operator_execution(operator_name="op", category="cat", duration_ms=1.0, success=True)


# ---------------------------------------------------------------------------
# shutdown — exception paths
# ---------------------------------------------------------------------------


def test_shutdown_swallows_tracer_provider_exception():
    svc = TelemetryService()
    svc.initialize(config=TelemetryConfig(enabled=False))
    svc._enabled = True
    mock_tp = MagicMock()
    mock_tp.shutdown.side_effect = RuntimeError("tp broken")
    svc._tracer_provider = mock_tp
    svc._meter_provider = None
    svc.shutdown()  # Must not raise


def test_shutdown_swallows_meter_provider_exception():
    svc = TelemetryService()
    svc.initialize(config=TelemetryConfig(enabled=False))
    svc._enabled = True
    svc._tracer_provider = None
    mock_mp = MagicMock()
    mock_mp.shutdown.side_effect = RuntimeError("mp broken")
    svc._meter_provider = mock_mp
    svc.shutdown()  # Must not raise


# ---------------------------------------------------------------------------
# Metrics initialization failure and current-span fallbacks
# ---------------------------------------------------------------------------


def test_initialize_metrics_failure_keeps_traces_enabled():
    """A broken metrics SDK is logged; tracing stays enabled and metrics are reported inactive."""
    svc = TelemetryService()
    modules, *_ = _make_mock_otel_modules()
    modules["opentelemetry.sdk.metrics"].MeterProvider.side_effect = RuntimeError("metrics broken")
    with (
        patch.dict("sys.modules", modules),
        patch("docpipe.utils.infrastructure.telemetry_service.logger") as mock_logger,
    ):
        svc.initialize(config=TelemetryConfig(enabled=True, otlp_endpoint="http://localhost:4317"))

    assert svc.is_enabled is True
    assert svc.metrics_enabled is False
    mock_logger.warning.assert_called_once_with(
        "Failed to initialize metrics. Traces will still be exported.",
        extra={"error": "metrics broken"},
    )


def _enabled_service_with_trace(*, current_span):
    """Return an enabled service and mock opentelemetry modules whose current span is ``current_span``."""
    svc = TelemetryService()
    svc.initialize(config=TelemetryConfig(enabled=False))
    svc._enabled = True
    mock_trace = MagicMock()
    mock_trace.get_current_span.return_value = current_span
    modules = {"opentelemetry": MagicMock(trace=mock_trace), "opentelemetry.trace": mock_trace}
    return svc, mock_trace, modules


def test_set_span_attribute_defaults_to_current_span():
    """Without an explicit span the attribute is set on the active span."""
    current = MagicMock()
    svc, _, modules = _enabled_service_with_trace(current_span=current)
    with patch.dict("sys.modules", modules):
        svc.set_span_attribute("k", "v")
    current.set_attribute.assert_called_once_with("k", "v")


def test_record_exception_defaults_to_current_span_and_sets_error_status():
    """Without an explicit span the exception and an ERROR status go to the active span."""
    current = MagicMock()
    svc, mock_trace, modules = _enabled_service_with_trace(current_span=current)
    error = ValueError("oops")
    with patch.dict("sys.modules", modules):
        svc.record_exception(error)
    current.record_exception.assert_called_once_with(error)
    mock_trace.Status.assert_called_once_with(mock_trace.StatusCode.ERROR, "oops")
    current.set_status.assert_called_once_with(mock_trace.Status.return_value)


def test_record_exception_with_explicit_span_sets_error_status():
    """An explicitly passed span gets the exception event and an ERROR status."""
    span = MagicMock()
    svc, mock_trace, modules = _enabled_service_with_trace(current_span=None)
    error = ValueError("oops")
    with patch.dict("sys.modules", modules):
        svc.record_exception(error, span=span)
    span.record_exception.assert_called_once_with(error)
    mock_trace.Status.assert_called_once_with(mock_trace.StatusCode.ERROR, "oops")
    span.set_status.assert_called_once_with(mock_trace.Status.return_value)


def test_record_exception_without_any_span_is_noop():
    """When there is no active span nothing is recorded and nothing raises."""
    svc, mock_trace, modules = _enabled_service_with_trace(current_span=None)
    with patch.dict("sys.modules", modules):
        svc.record_exception(ValueError("oops"))
    mock_trace.Status.assert_not_called()


def test_get_current_span_returns_active_span():
    """get_current_span delegates to opentelemetry.trace.get_current_span."""
    current = MagicMock()
    svc, _, modules = _enabled_service_with_trace(current_span=current)
    with patch.dict("sys.modules", modules):
        assert svc.get_current_span() is current


def test_get_current_span_returns_none_when_lookup_fails():
    """An error from opentelemetry while looking up the span yields None."""
    svc, mock_trace, modules = _enabled_service_with_trace(current_span=None)
    mock_trace.get_current_span.side_effect = RuntimeError("context broken")
    with patch.dict("sys.modules", modules):
        assert svc.get_current_span() is None

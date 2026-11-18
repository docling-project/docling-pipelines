"""OpenTelemetry telemetry service for distributed tracing and metrics.

This module provides a singleton telemetry service that:
- Lazily initializes OpenTelemetry SDK when enabled
- Provides zero overhead when disabled
- Handles missing OTEL dependencies gracefully
- Integrates with existing transaction ID infrastructure
- Exports traces and metrics via OTLP (both controlled by TELEMETRY_ENABLED)
- Supports head-based sampling for high-volume deployments
- Exposes trace context for log-trace correlation
"""

import os
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from docpipe.utils.infrastructure.logging import get_logger

logger = get_logger()

# Default telemetry configuration constants
DEFAULT_TELEMETRY_ENABLED = False
DEFAULT_OTEL_SERVICE_NAME = "docling-pipelines"
DEFAULT_OTEL_ENDPOINT = "http://localhost:4317"
DEFAULT_OTEL_SERVICE_VERSION = "0.1.0"
DEFAULT_OTEL_DEPLOYMENT_ENVIRONMENT = "development"
DEFAULT_SAMPLE_RATE = 1.0  # 100% sampling by default


@dataclass
class TelemetryConfig:
    """Configuration for telemetry service.

    Attributes:
        enabled: Master switch — enables both traces and metrics when True.
                 Controlled by TELEMETRY_ENABLED env var.
        service_name: Name of the service in traces/metrics.
        otlp_endpoint: OTLP endpoint URL.
        service_version: Version of the service.
        deployment_environment: Deployment environment name.
        otlp_headers: Optional headers for OTLP exporter (e.g., authentication).
        sample_rate: Head-based sampling rate (0.0-1.0). 1.0 = 100%, 0.1 = 10%.
                     Controlled by OTEL_TRACES_SAMPLER_ARG env var.
        metrics_export_interval_ms: How often metrics are flushed to the backend.
                                    Controlled by OTEL_METRIC_EXPORT_INTERVAL env var.
    """

    enabled: bool = DEFAULT_TELEMETRY_ENABLED
    service_name: str = DEFAULT_OTEL_SERVICE_NAME
    otlp_endpoint: str = DEFAULT_OTEL_ENDPOINT
    service_version: str = DEFAULT_OTEL_SERVICE_VERSION
    deployment_environment: str = DEFAULT_OTEL_DEPLOYMENT_ENVIRONMENT
    otlp_headers: dict[str, str] | None = None
    sample_rate: float = DEFAULT_SAMPLE_RATE
    metrics_export_interval_ms: int = 60000

    @classmethod
    def from_environment(cls) -> "TelemetryConfig":
        """Load configuration from environment variables.

        Setting TELEMETRY_ENABLED=true turns on both traces and metrics.

        Returns:
            TelemetryConfig instance with values from environment
        """
        enabled_str = os.getenv("TELEMETRY_ENABLED", "false").lower()
        enabled = enabled_str in ("true", "1", "yes", "on")

        # Parse OTEL headers if provided
        headers = None
        headers_str = os.getenv("OTEL_EXPORTER_OTLP_HEADERS")
        if headers_str:
            headers = cls._parse_headers(headers_str)

        # Parse sample rate (0.0 to 1.0)
        try:
            sample_rate = float(os.getenv("OTEL_TRACES_SAMPLER_ARG", str(DEFAULT_SAMPLE_RATE)))
            sample_rate = max(0.0, min(1.0, sample_rate))
        except ValueError:
            sample_rate = DEFAULT_SAMPLE_RATE

        # Parse metrics export interval
        try:
            metrics_export_interval_ms = int(os.getenv("OTEL_METRIC_EXPORT_INTERVAL", "60000"))
        except ValueError:
            metrics_export_interval_ms = 60000

        return cls(
            enabled=enabled,
            service_name=os.getenv("OTEL_SERVICE_NAME", DEFAULT_OTEL_SERVICE_NAME),
            otlp_endpoint=os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", DEFAULT_OTEL_ENDPOINT),
            service_version=os.getenv("OTEL_SERVICE_VERSION", DEFAULT_OTEL_SERVICE_VERSION),
            deployment_environment=os.getenv("OTEL_DEPLOYMENT_ENVIRONMENT", DEFAULT_OTEL_DEPLOYMENT_ENVIRONMENT),
            otlp_headers=headers,
            sample_rate=sample_rate,
            metrics_export_interval_ms=metrics_export_interval_ms,
        )

    @staticmethod
    def _parse_headers(headers_str: str) -> dict[str, str]:
        """Parse OTEL headers from environment variable format.

        Supports formats:
        - key1=value1,key2=value2
        - Authorization=Basic <token> (keeps value together)

        Args:
            headers_str: Headers string from environment variable

        Returns:
            Dictionary of header key-value pairs with lowercase keys (gRPC requirement)
        """
        headers = {}
        # Split by comma first to handle multiple headers
        pairs = headers_str.split(",")
        for pair in pairs:
            pair = pair.strip()
            if "=" in pair:
                key, value = pair.split("=", 1)
                # URL decode the value if needed
                value = value.replace("%20", " ")
                # gRPC metadata keys must be lowercase
                headers[key.strip().lower()] = value.strip()
        return headers


class TelemetryService:
    """Singleton service for OpenTelemetry tracing and metrics.

    Enabling telemetry (TELEMETRY_ENABLED=true) activates both:
    - Distributed tracing: spans exported via OTLP
    - Metrics: counters and histograms exported via OTLP

    All operations are no-ops when disabled, with zero overhead.
    Missing OTEL dependencies are handled gracefully.
    """

    _instance: "TelemetryService | None" = None
    _initialized: bool
    _enabled: bool
    _tracer: Any
    _tracer_provider: Any
    _meter: Any
    _meter_provider: Any

    # Metric instruments (populated during initialize when enabled=True)
    _http_request_counter: Any
    _http_request_duration: Any
    _operator_execution_counter: Any
    _operator_execution_duration: Any
    _operator_error_counter: Any

    def __new__(cls) -> "TelemetryService":
        """Ensure singleton pattern."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
            cls._instance._enabled = False
            cls._instance._tracer = None
            cls._instance._tracer_provider = None
            cls._instance._meter = None
            cls._instance._meter_provider = None
            cls._instance._http_request_counter = None
            cls._instance._http_request_duration = None
            cls._instance._operator_execution_counter = None
            cls._instance._operator_execution_duration = None
            cls._instance._operator_error_counter = None
        return cls._instance

    def __init__(self):
        """Initialize telemetry service (called on every get_telemetry_service call)."""

    def initialize(self, *, config: TelemetryConfig | None = None) -> None:
        """Initialize OpenTelemetry SDK with configuration.

        When enabled, initializes both the tracer provider (traces) and the
        meter provider (metrics) sharing the same OTLP endpoint and resource.

        Args:
            config: Telemetry configuration. If None, loads from environment.
        """
        if self._initialized:
            logger.debug("Telemetry service already initialized")
            return

        if config is None:
            config = TelemetryConfig.from_environment()

        self._enabled = config.enabled

        if not self._enabled:
            logger.info("Telemetry is disabled")
            self._initialized = True
            return

        try:
            from opentelemetry import trace  # type: ignore[import-not-found]
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
                OTLPSpanExporter,  # type: ignore[import-not-found]
            )
            from opentelemetry.sdk.resources import Resource  # type: ignore[import-not-found]
            from opentelemetry.sdk.trace import TracerProvider  # type: ignore[import-not-found]
            from opentelemetry.sdk.trace.export import BatchSpanProcessor  # type: ignore[import-not-found]
            from opentelemetry.sdk.trace.sampling import TraceIdRatioBased  # type: ignore[import-not-found]

            # Shared resource for both traces and metrics
            resource = Resource.create(
                {
                    "service.name": config.service_name,
                    "service.version": config.service_version,
                    "deployment.environment": config.deployment_environment,
                }
            )

            # Head-based sampler
            sampler = TraceIdRatioBased(config.sample_rate)

            # Tracer provider
            self._tracer_provider = TracerProvider(resource=resource, sampler=sampler)

            is_secure = config.otlp_endpoint.startswith("https://")
            exporter_kwargs: dict[str, Any] = {
                "endpoint": config.otlp_endpoint,
                "insecure": not is_secure,
            }
            if config.otlp_headers:
                exporter_kwargs["headers"] = config.otlp_headers

            otlp_span_exporter = OTLPSpanExporter(**exporter_kwargs)
            self._tracer_provider.add_span_processor(BatchSpanProcessor(otlp_span_exporter))
            trace.set_tracer_provider(self._tracer_provider)
            self._tracer = trace.get_tracer(__name__)

            # Metrics initialised alongside traces
            self._initialize_metrics(config=config, resource=resource, exporter_kwargs=exporter_kwargs)

            logger.info(
                "Telemetry initialized successfully",
                extra={
                    "service_name": config.service_name,
                    "otlp_endpoint": config.otlp_endpoint,
                    "deployment_environment": config.deployment_environment,
                    "secure_connection": is_secure,
                    "headers_configured": bool(config.otlp_headers),
                    "sample_rate": config.sample_rate,
                },
            )

        except ImportError as e:
            logger.warning(
                "OpenTelemetry dependencies not installed. Install with: uv pip install -e '.[telemetry]'",
                extra={"error": str(e)},
            )
            self._enabled = False
        except Exception as e:
            logger.exception(
                "Failed to initialize telemetry",
                extra={"error": str(e)},
            )
            self._enabled = False

        self._initialized = True

    def _initialize_metrics(
        self,
        *,
        config: TelemetryConfig,
        resource: Any,
        exporter_kwargs: dict[str, Any],
    ) -> None:
        """Initialize OpenTelemetry metrics SDK.

        Creates a MeterProvider with a PeriodicExportingMetricReader backed by
        an OTLP exporter, then registers all metric instruments.

        Args:
            config: Telemetry configuration
            resource: Shared OTEL Resource instance
            exporter_kwargs: Kwargs forwarded to OTLPMetricExporter
        """
        try:
            from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import (
                OTLPMetricExporter,  # type: ignore[import-not-found]
            )
            from opentelemetry.sdk.metrics import MeterProvider  # type: ignore[import-not-found]
            from opentelemetry.sdk.metrics.export import (
                PeriodicExportingMetricReader,  # type: ignore[import-not-found]
            )

            reader = PeriodicExportingMetricReader(
                OTLPMetricExporter(**exporter_kwargs),
                export_interval_millis=config.metrics_export_interval_ms,
            )
            self._meter_provider = MeterProvider(resource=resource, metric_readers=[reader])
            self._meter = self._meter_provider.get_meter(__name__)

            self._http_request_counter = self._meter.create_counter(
                name="http.server.request.count",
                description="Total number of HTTP requests received",
                unit="1",
            )
            self._http_request_duration = self._meter.create_histogram(
                name="http.server.request.duration",
                description="Duration of HTTP requests in milliseconds",
                unit="ms",
            )
            self._operator_execution_counter = self._meter.create_counter(
                name="operator.execution.count",
                description="Total number of operator executions",
                unit="1",
            )
            self._operator_execution_duration = self._meter.create_histogram(
                name="operator.execution.duration",
                description="Duration of operator executions in milliseconds",
                unit="ms",
            )
            self._operator_error_counter = self._meter.create_counter(
                name="operator.error.count",
                description="Total number of operator execution errors",
                unit="1",
            )

            logger.debug("Metrics initialized successfully")

        except Exception as e:
            # Metrics are best-effort — traces still work without them
            logger.warning(
                "Failed to initialize metrics. Traces will still be exported.",
                extra={"error": str(e)},
            )

    # ------------------------------------------------------------------
    # Tracing API
    # ------------------------------------------------------------------

    def start_span(self, name: str, *, attributes: dict[str, Any] | None = None):
        """Start a new span.

        Auto-initializes telemetry on first use if not already initialized.

        Args:
            name: Name of the span
            attributes: Optional attributes to add to the span

        Returns:
            Span object if enabled, None otherwise
        """
        if not self._initialized:
            self.initialize()

        if not self._enabled or self._tracer is None:
            return None

        try:
            span = self._tracer.start_span(name)
            if attributes:
                for key, value in attributes.items():
                    if value is not None:
                        span.set_attribute(key, value)
            return span
        except Exception as e:
            logger.debug("Failed to start span: %s", e)
            return None

    def end_span(self, span) -> None:
        """End a span.

        Args:
            span: Span to end (can be None)
        """
        if span is None or not self._enabled:
            return

        try:
            span.end()
        except Exception as e:
            logger.debug("Failed to end span: %s", e)

    @contextmanager
    def span(self, name: str, *, attributes: dict[str, Any] | None = None):
        """Context manager for creating and ending a span.

        Args:
            name: Name of the span
            attributes: Optional attributes to add to the span

        Yields:
            Span object (may be None if telemetry is disabled)
        """
        s = self.start_span(name, attributes=attributes)
        try:
            yield s
        except Exception as e:
            self.record_exception(e, span=s)
            raise
        finally:
            self.end_span(s)

    def set_span_attribute(self, key: str, value: Any, *, span=None) -> None:
        """Set an attribute on a span.

        Args:
            key: Attribute key
            value: Attribute value
            span: Span to set attribute on. If None, uses the current active span.
        """
        if not self._enabled:
            return

        try:
            if span is None:
                from opentelemetry import trace  # type: ignore[import-not-found]

                span = trace.get_current_span()
            if span is not None and value is not None:
                span.set_attribute(key, value)
        except Exception as e:
            logger.debug("Failed to set span attribute: %s", e)

    def record_exception(self, exception: Exception, *, span=None) -> None:
        """Record an exception in a span.

        Args:
            exception: Exception to record
            span: Span to record exception in. If None, uses the current active span.
        """
        if not self._enabled:
            return

        try:
            if span is None:
                from opentelemetry import trace  # type: ignore[import-not-found]

                span = trace.get_current_span()
            if span is not None:
                span.record_exception(exception)
                span.set_status(trace.Status(trace.StatusCode.ERROR, str(exception)))
        except Exception as e:
            logger.debug("Failed to record exception: %s", e)

    def get_current_span(self):
        """Get the current active span.

        Returns:
            Current span if enabled, None otherwise
        """
        if not self._enabled:
            return None

        try:
            from opentelemetry import trace  # type: ignore[import-not-found]

            return trace.get_current_span()
        except Exception as e:
            logger.debug("Failed to get current span: %s", e)
            return None

    def get_trace_context(self) -> dict[str, str]:
        """Get the current trace context for log-trace correlation.

        Returns the trace_id and span_id of the currently active span.
        Inject these values into log records so individual log lines can be
        navigated directly to the corresponding trace in Grafana, Jaeger, etc.

        Returns:
            Dict with 'trace_id' (32-char hex) and 'span_id' (16-char hex).
            Both values are empty strings when telemetry is disabled or there
            is no active span.
        """
        empty: dict[str, str] = {"trace_id": "", "span_id": ""}

        if not self._enabled:
            return empty

        try:
            from opentelemetry import trace  # type: ignore[import-not-found]

            span = trace.get_current_span()
            ctx = span.get_span_context()
            if ctx is None or not ctx.is_valid:
                return empty

            return {
                "trace_id": format(ctx.trace_id, "032x"),
                "span_id": format(ctx.span_id, "016x"),
            }
        except Exception as e:
            logger.debug("Failed to get trace context: %s", e)
            return empty

    # ------------------------------------------------------------------
    # Metrics API
    # ------------------------------------------------------------------

    def record_http_request(
        self,
        *,
        method: str,
        path: str,
        status_code: int,
        duration_ms: float,
    ) -> None:
        """Record an HTTP request metric (counter + duration histogram).

        Args:
            method: HTTP method (GET, POST, etc.)
            path: Request path / route
            status_code: HTTP response status code
            duration_ms: Request duration in milliseconds
        """
        if not self._enabled or self._http_request_counter is None:
            return

        try:
            labels = {
                "http.method": method,
                "http.route": path,
                "http.status_code": str(status_code),
            }
            self._http_request_counter.add(1, labels)
            self._http_request_duration.record(duration_ms, labels)
        except Exception as e:
            logger.debug("Failed to record HTTP request metric: %s", e)

    def record_operator_execution(
        self,
        *,
        operator_name: str,
        category: str,
        duration_ms: float,
        success: bool,
    ) -> None:
        """Record an operator execution metric (counter + duration histogram).

        Args:
            operator_name: Short name of the operator
            category: Operator category (Extract, Ingest, Functional, Quality, VectorDB)
            duration_ms: Execution duration in milliseconds
            success: Whether the execution succeeded
        """
        if not self._enabled or self._operator_execution_counter is None:
            return

        try:
            labels = {
                "operator.name": operator_name,
                "operator.category": category,
                "success": str(success).lower(),
            }
            self._operator_execution_counter.add(1, labels)
            self._operator_execution_duration.record(duration_ms, labels)

            if not success and self._operator_error_counter is not None:
                self._operator_error_counter.add(
                    1,
                    {"operator.name": operator_name, "operator.category": category},
                )
        except Exception as e:
            logger.debug("Failed to record operator execution metric: %s", e)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def shutdown(self) -> None:
        """Shutdown telemetry service and flush pending spans and metrics."""
        if not self._enabled:
            return

        if self._tracer_provider is not None:
            try:
                logger.info("Shutting down telemetry tracing")
                self._tracer_provider.shutdown()
            except Exception as e:
                logger.error("Failed to shutdown tracing: %s", e)

        if self._meter_provider is not None:
            try:
                logger.info("Shutting down telemetry metrics")
                self._meter_provider.shutdown()
            except Exception as e:
                logger.error("Failed to shutdown metrics: %s", e)

    @property
    def is_enabled(self) -> bool:
        """Check if telemetry is enabled."""
        return self._enabled

    @property
    def metrics_enabled(self) -> bool:
        """Check if metrics collection is active."""
        return self._enabled and self._meter is not None


# Global singleton instance
_telemetry_service: TelemetryService | None = None


def get_telemetry_service() -> TelemetryService:
    """Get the global telemetry service instance.

    Returns:
        TelemetryService singleton instance
    """
    global _telemetry_service
    if _telemetry_service is None:
        _telemetry_service = TelemetryService()
    return _telemetry_service

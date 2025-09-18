"""
OpenTelemetry configuration and initialization for Observe MCP Server

Handles the setup of tracing, metrics, and instrumentation with automatic
detection of the OpenTelemetry collector endpoint and service metadata.
"""

import os
import sys
from typing import Optional
from src.logging import get_logger

logger = get_logger('TELEMETRY')

# Global telemetry state
_telemetry_initialized = False
_tracer = None
_meter = None

def is_telemetry_enabled() -> bool:
    """Check if telemetry is enabled via environment variables."""
    return os.getenv('OTEL_TELEMETRY_ENABLED', 'true').lower() in ('true', '1', 'yes', 'on')

def get_service_name() -> str:
    """Get the service name for telemetry."""
    return os.getenv('OTEL_SERVICE_NAME', 'observe-community-mcp')

def get_otel_endpoint() -> str:
    """Get the OTLP endpoint for telemetry export."""
    # Default to the collector we set up in docker-compose
    return os.getenv('OTEL_EXPORTER_OTLP_ENDPOINT', 'http://localhost:4317')

def get_deployment_environment() -> str:
    """Get the deployment environment."""
    return os.getenv('DEPLOYMENT_ENVIRONMENT', 'development')

def initialize_telemetry() -> bool:
    """
    Initialize OpenTelemetry tracing and metrics.

    Returns:
        True if initialization was successful, False otherwise
    """
    global _telemetry_initialized, _tracer, _meter

    if _telemetry_initialized:
        logger.debug("telemetry already initialized")
        return True

    if not is_telemetry_enabled():
        logger.info("telemetry disabled via configuration")
        return False

    try:
        from opentelemetry import trace, metrics
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.metrics import MeterProvider
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader

        # Auto-instrumentation imports
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
        from opentelemetry.instrumentation.asyncpg import AsyncPGInstrumentor
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        # Create resource with service information
        resource = Resource.create({
            "service.name": get_service_name(),
            "service.version": "1.0.0",
            "deployment.environment": get_deployment_environment(),
            "service.namespace": "observe-mcp",
            "telemetry.sdk.name": "opentelemetry",
            "telemetry.sdk.language": "python"
        })

        # Configure tracing
        otlp_endpoint = get_otel_endpoint()
        logger.info(f"initializing telemetry | endpoint:{otlp_endpoint} | service:{get_service_name()}")

        # Set up trace provider
        trace_provider = TracerProvider(resource=resource)
        trace.set_tracer_provider(trace_provider)

        # Configure OTLP span exporter
        span_exporter = OTLPSpanExporter(
            endpoint=otlp_endpoint,
            insecure=True  # For local development
        )
        span_processor = BatchSpanProcessor(span_exporter)
        trace_provider.add_span_processor(span_processor)

        # Set up metrics provider
        metric_reader = PeriodicExportingMetricReader(
            OTLPMetricExporter(
                endpoint=otlp_endpoint,
                insecure=True
            ),
            export_interval_millis=10000  # Export every 10 seconds
        )
        metrics_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])
        metrics.set_meter_provider(metrics_provider)

        # Initialize auto-instrumentation
        logger.debug("enabling automatic instrumentation")

        # Instrument HTTP client (httpx)
        HTTPXClientInstrumentor().instrument()

        # Instrument PostgreSQL (asyncpg)
        AsyncPGInstrumentor().instrument()

        # Note: FastAPI instrumentation will be done in observe_server.py
        # after the FastMCP app is created

        # Create tracer and meter instances
        _tracer = trace.get_tracer(__name__)
        _meter = metrics.get_meter(__name__)

        _telemetry_initialized = True
        logger.info("telemetry initialization complete")
        return True

    except ImportError as e:
        logger.warning(f"telemetry disabled | missing dependencies: {e}")
        return False
    except Exception as e:
        logger.error(f"telemetry initialization failed | error: {e}")
        import traceback
        traceback.print_exc(file=sys.stderr)
        return False

def get_tracer():
    """Get the OpenTelemetry tracer instance."""
    global _tracer
    if not _telemetry_initialized:
        logger.warning("telemetry not initialized | tracer unavailable")
        return None
    return _tracer

def get_meter():
    """Get the OpenTelemetry meter instance."""
    global _meter
    if not _telemetry_initialized:
        logger.warning("telemetry not initialized | meter unavailable")
        return None
    return _meter

def shutdown_telemetry():
    """Shutdown telemetry providers and flush any pending data."""
    global _telemetry_initialized

    if not _telemetry_initialized:
        return

    try:
        from opentelemetry import trace, metrics

        # Get providers and shut them down
        trace_provider = trace.get_tracer_provider()
        if hasattr(trace_provider, 'shutdown'):
            trace_provider.shutdown()

        meter_provider = metrics.get_meter_provider()
        if hasattr(meter_provider, 'shutdown'):
            meter_provider.shutdown()

        logger.info("telemetry shutdown complete")

    except Exception as e:
        logger.error(f"telemetry shutdown error | error: {e}")

    finally:
        _telemetry_initialized = False

def instrument_fastapi_app(app):
    """
    Instrument a FastAPI application with OpenTelemetry.

    Args:
        app: FastAPI application instance
    """
    if not _telemetry_initialized:
        logger.debug("telemetry not initialized | skipping FastAPI instrumentation")
        return

    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        # Instrument the FastAPI app
        FastAPIInstrumentor.instrument_app(app)
        logger.debug("FastAPI instrumentation enabled")

    except ImportError:
        logger.warning("FastAPI instrumentation not available")
    except Exception as e:
        logger.error(f"FastAPI instrumentation failed | error: {e}")

def get_telemetry_status() -> dict:
    """
    Get the current telemetry configuration status.

    Returns:
        Dictionary with telemetry status information
    """
    return {
        "enabled": is_telemetry_enabled(),
        "initialized": _telemetry_initialized,
        "service_name": get_service_name(),
        "endpoint": get_otel_endpoint(),
        "environment": get_deployment_environment(),
        "tracer_available": _tracer is not None,
        "meter_available": _meter is not None
    }
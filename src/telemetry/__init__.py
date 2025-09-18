"""
OpenTelemetry instrumentation package for Observe MCP Server

Provides centralized configuration and initialization for OpenTelemetry
tracing, metrics, and logging across the MCP server application.
"""

from .config import (
    initialize_telemetry,
    get_tracer,
    get_meter,
    shutdown_telemetry,
    is_telemetry_enabled
)

from .decorators import (
    trace_mcp_tool,
    trace_observe_api_call,
    trace_database_operation
)

from .utils import (
    add_span_attributes,
    set_span_status,
    record_exception,
    create_span_context
)

from .metrics import (
    initialize_metrics,
    record_tool_invocation,
    record_api_request,
    record_database_query,
    record_error,
    MetricsTimer,
    get_metrics_status
)

__all__ = [
    # Core configuration
    'initialize_telemetry',
    'get_tracer',
    'get_meter',
    'shutdown_telemetry',
    'is_telemetry_enabled',

    # Decorators
    'trace_mcp_tool',
    'trace_observe_api_call',
    'trace_database_operation',

    # Utilities
    'add_span_attributes',
    'set_span_status',
    'record_exception',
    'create_span_context',

    # Metrics
    'initialize_metrics',
    'record_tool_invocation',
    'record_api_request',
    'record_database_query',
    'record_error',
    'MetricsTimer',
    'get_metrics_status'
]
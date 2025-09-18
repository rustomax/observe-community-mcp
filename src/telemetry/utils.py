"""
OpenTelemetry utility functions for manual instrumentation

Provides helper functions for working with spans, attributes,
and telemetry data in the MCP server application.
"""

from typing import Dict, Any, Optional, Union
from src.logging import get_logger

logger = get_logger('TELEMETRY_UTILS')

def add_span_attributes(span, attributes: Dict[str, Any]):
    """
    Add multiple attributes to a span with type validation.

    Args:
        span: OpenTelemetry span
        attributes: Dictionary of attribute key-value pairs
    """
    if not span or not attributes:
        return

    for key, value in attributes.items():
        try:
            # Convert value to appropriate type for OpenTelemetry
            if isinstance(value, (str, int, float, bool)):
                span.set_attribute(key, value)
            elif value is None:
                span.set_attribute(key, "null")
            else:
                # Convert complex objects to strings
                value_str = str(value)
                if len(value_str) <= 1000:  # Limit attribute size
                    span.set_attribute(key, value_str)
                else:
                    span.set_attribute(f"{key}_size", len(value_str))
                    span.set_attribute(f"{key}_truncated", value_str[:200] + "...")
        except Exception as e:
            logger.debug(f"failed to set span attribute | key: {key} | error: {e}")

def set_span_status(span, success: bool, message: Optional[str] = None):
    """
    Set span status based on operation success.

    Args:
        span: OpenTelemetry span
        success: Whether the operation was successful
        message: Optional status message
    """
    if not span:
        return

    try:
        from opentelemetry import trace

        if success:
            span.set_status(trace.Status(trace.StatusCode.OK, message))
        else:
            span.set_status(trace.Status(trace.StatusCode.ERROR, message or "Operation failed"))
    except Exception as e:
        logger.debug(f"failed to set span status | error: {e}")

def record_exception(span, exception: Exception, escaped: bool = False):
    """
    Record an exception on a span with additional context.

    Args:
        span: OpenTelemetry span
        exception: Exception to record
        escaped: Whether the exception escaped the span (default: False)
    """
    if not span:
        return

    try:
        span.record_exception(exception, escaped=escaped)
        span.set_attribute("exception.type", type(exception).__name__)
        span.set_attribute("exception.message", str(exception))
        span.set_attribute("exception.escaped", escaped)
    except Exception as e:
        logger.debug(f"failed to record exception | error: {e}")

def create_span_context(operation: str, **attributes):
    """
    Create a new span context for manual instrumentation.

    Args:
        operation: Name of the operation
        **attributes: Additional span attributes

    Returns:
        Context manager for the span
    """
    from .config import get_tracer

    tracer = get_tracer()
    if not tracer:
        # Return a no-op context manager
        return _NoOpSpan()

    span = tracer.start_span(operation)
    add_span_attributes(span, attributes)
    return span

def add_mcp_context(span, ctx):
    """
    Add MCP-specific context to a span.

    Args:
        span: OpenTelemetry span
        ctx: MCP Context object
    """
    if not span or not ctx:
        return

    try:
        if hasattr(ctx, 'session_id'):
            span.set_attribute("mcp.session.id", ctx.session_id)

        # Add any additional MCP context attributes
        span.set_attribute("mcp.protocol", "model_context_protocol")
    except Exception as e:
        logger.debug(f"failed to add MCP context | error: {e}")

def add_observe_context(span, dataset_id: Optional[str] = None,
                       query_type: Optional[str] = None,
                       time_range: Optional[str] = None):
    """
    Add Observe-specific context to a span.

    Args:
        span: OpenTelemetry span
        dataset_id: Observe dataset ID
        query_type: Type of query being performed
        time_range: Time range for the query
    """
    if not span:
        return

    try:
        if dataset_id:
            span.set_attribute("observe.dataset.id", dataset_id)
        if query_type:
            span.set_attribute("observe.query.type", query_type)
        if time_range:
            span.set_attribute("observe.query.time_range", time_range)

        span.set_attribute("observe.platform", "observe_inc")
    except Exception as e:
        logger.debug(f"failed to add Observe context | error: {e}")

def add_database_context(span, table: Optional[str] = None,
                        operation: Optional[str] = None,
                        row_count: Optional[int] = None):
    """
    Add database-specific context to a span.

    Args:
        span: OpenTelemetry span
        table: Database table name
        operation: Database operation type
        row_count: Number of rows affected/returned
    """
    if not span:
        return

    try:
        span.set_attribute("db.system", "postgresql")
        if table:
            span.set_attribute("db.table.name", table)
        if operation:
            span.set_attribute("db.operation", operation)
        if row_count is not None:
            span.set_attribute("db.result.count", row_count)
    except Exception as e:
        logger.debug(f"failed to add database context | error: {e}")

def get_current_span_context():
    """
    Get the current span context for correlation.

    Returns:
        Current span context or None if no active span
    """
    try:
        from opentelemetry import trace
        span = trace.get_current_span()
        if span and span.is_recording():
            return span.get_span_context()
    except Exception as e:
        logger.debug(f"failed to get current span context | error: {e}")
    return None

def correlate_with_logging(extra_fields: Optional[Dict[str, Any]] = None):
    """
    Get correlation fields for logging from the current span.

    Args:
        extra_fields: Additional fields to include

    Returns:
        Dictionary of correlation fields for logging
    """
    fields = extra_fields or {}

    try:
        from opentelemetry import trace
        span = trace.get_current_span()
        if span and span.is_recording():
            span_context = span.get_span_context()
            fields['trace_id'] = format(span_context.trace_id, '032x')
            fields['span_id'] = format(span_context.span_id, '016x')
    except Exception as e:
        logger.debug(f"failed to get correlation fields | error: {e}")

    return fields

class _NoOpSpan:
    """No-op span context manager for when telemetry is disabled."""

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

    def set_attribute(self, key, value):
        pass

    def set_status(self, status):
        pass

    def record_exception(self, exception, escaped=False):
        pass
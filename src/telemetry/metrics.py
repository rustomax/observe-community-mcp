"""
OpenTelemetry metrics collection for MCP server operations

Provides business-specific metrics for monitoring MCP tool usage,
performance, and operational health.
"""

import time
from typing import Optional, Dict, Any
from src.logging import get_logger

logger = get_logger('TELEMETRY_METRICS')

# Global metrics state
_meter = None
_metrics_enabled = False

# Metric instruments
_tool_invocation_counter = None
_tool_duration_histogram = None
_api_request_counter = None
_api_duration_histogram = None
_database_query_counter = None
_database_duration_histogram = None
_error_counter = None

def initialize_metrics():
    """Initialize OpenTelemetry metrics instruments."""
    global _meter, _metrics_enabled
    global _tool_invocation_counter, _tool_duration_histogram
    global _api_request_counter, _api_duration_histogram
    global _database_query_counter, _database_duration_histogram
    global _error_counter

    try:
        from src.telemetry.config import get_meter
        _meter = get_meter()

        if not _meter:
            logger.debug("metrics not available | meter not initialized")
            return False

        # MCP Tool metrics
        _tool_invocation_counter = _meter.create_counter(
            name="mcp_tool_invocations_total",
            description="Total number of MCP tool invocations",
            unit="1"
        )

        _tool_duration_histogram = _meter.create_histogram(
            name="mcp_tool_duration_seconds",
            description="Duration of MCP tool executions",
            unit="s"
        )

        # Observe API metrics
        _api_request_counter = _meter.create_counter(
            name="observe_api_requests_total",
            description="Total number of Observe API requests",
            unit="1"
        )

        _api_duration_histogram = _meter.create_histogram(
            name="observe_api_duration_seconds",
            description="Duration of Observe API requests",
            unit="s"
        )

        # Database metrics
        _database_query_counter = _meter.create_counter(
            name="database_queries_total",
            description="Total number of database queries",
            unit="1"
        )

        _database_duration_histogram = _meter.create_histogram(
            name="database_query_duration_seconds",
            description="Duration of database queries",
            unit="s"
        )

        # Error metrics
        _error_counter = _meter.create_counter(
            name="mcp_errors_total",
            description="Total number of errors by type",
            unit="1"
        )

        _metrics_enabled = True
        logger.info("metrics initialization complete")
        return True

    except ImportError:
        logger.debug("metrics not available | opentelemetry not installed")
        return False
    except Exception as e:
        logger.error(f"metrics initialization failed | error: {e}")
        return False

def record_tool_invocation(tool_name: str, duration: float, success: bool, **attributes):
    """
    Record metrics for MCP tool invocations.

    Args:
        tool_name: Name of the MCP tool
        duration: Execution duration in seconds
        success: Whether the invocation was successful
        **attributes: Additional attributes to record
    """
    if not _metrics_enabled or not _tool_invocation_counter:
        return

    try:
        # Basic attributes
        metric_attributes = {
            "tool_name": tool_name,
            "status": "success" if success else "error"
        }

        # Add optional attributes
        if attributes:
            for key, value in attributes.items():
                if isinstance(value, (str, int, float, bool)):
                    metric_attributes[f"tool.{key}"] = str(value)

        # Record metrics
        _tool_invocation_counter.add(1, metric_attributes)
        _tool_duration_histogram.record(duration, metric_attributes)

        logger.debug(f"recorded tool metrics | tool:{tool_name} | duration:{duration:.3f}s | success:{success}")

    except Exception as e:
        logger.debug(f"failed to record tool metrics | error: {e}")

def record_api_request(endpoint: str, method: str, status_code: int, duration: float, **attributes):
    """
    Record metrics for Observe API requests.

    Args:
        endpoint: API endpoint
        method: HTTP method
        status_code: HTTP status code
        duration: Request duration in seconds
        **attributes: Additional attributes
    """
    if not _metrics_enabled or not _api_request_counter:
        return

    try:
        metric_attributes = {
            "endpoint": endpoint,
            "method": method,
            "status_code": str(status_code),
            "status": "success" if status_code < 400 else "error"
        }

        # Add optional attributes
        for key, value in attributes.items():
            if isinstance(value, (str, int, float, bool)):
                metric_attributes[f"api.{key}"] = str(value)

        _api_request_counter.add(1, metric_attributes)
        _api_duration_histogram.record(duration, metric_attributes)

        logger.debug(f"recorded API metrics | endpoint:{endpoint} | status:{status_code} | duration:{duration:.3f}s")

    except Exception as e:
        logger.debug(f"failed to record API metrics | error: {e}")

def record_database_query(operation: str, table: str, duration: float, success: bool, row_count: Optional[int] = None):
    """
    Record metrics for database queries.

    Args:
        operation: Database operation type
        table: Table name
        duration: Query duration in seconds
        success: Whether the query was successful
        row_count: Number of rows returned/affected
    """
    if not _metrics_enabled or not _database_query_counter:
        return

    try:
        metric_attributes = {
            "operation": operation,
            "table": table,
            "status": "success" if success else "error"
        }

        if row_count is not None:
            metric_attributes["rows"] = str(row_count)

        _database_query_counter.add(1, metric_attributes)
        _database_duration_histogram.record(duration, metric_attributes)

        logger.debug(f"recorded DB metrics | operation:{operation} | table:{table} | duration:{duration:.3f}s | rows:{row_count}")

    except Exception as e:
        logger.debug(f"failed to record DB metrics | error: {e}")

def record_error(error_type: str, operation: str, **attributes):
    """
    Record error occurrences.

    Args:
        error_type: Type/category of error
        operation: Operation where error occurred
        **attributes: Additional error context
    """
    if not _metrics_enabled or not _error_counter:
        return

    try:
        metric_attributes = {
            "error_type": error_type,
            "operation": operation
        }

        for key, value in attributes.items():
            if isinstance(value, (str, int, float, bool)):
                metric_attributes[f"error.{key}"] = str(value)

        _error_counter.add(1, metric_attributes)

        logger.debug(f"recorded error metric | type:{error_type} | operation:{operation}")

    except Exception as e:
        logger.debug(f"failed to record error metric | error: {e}")

class MetricsTimer:
    """Context manager for timing operations and recording metrics."""

    def __init__(self, metric_type: str, operation: str, **attributes):
        """
        Initialize metrics timer.

        Args:
            metric_type: Type of metric ("tool", "api", "database")
            operation: Operation being timed
            **attributes: Additional attributes to record
        """
        self.metric_type = metric_type
        self.operation = operation
        self.attributes = attributes
        self.start_time = None
        self.success = True

    def __enter__(self):
        """Start timing."""
        self.start_time = time.time()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Stop timing and record metrics."""
        if self.start_time is None:
            return

        duration = time.time() - self.start_time

        # Mark as failed if exception occurred
        if exc_type is not None:
            self.success = False

        # Record appropriate metric type
        try:
            if self.metric_type == "tool":
                record_tool_invocation(self.operation, duration, self.success, **self.attributes)
            elif self.metric_type == "api":
                endpoint = self.attributes.get("endpoint", self.operation)
                method = self.attributes.get("method", "GET")
                status_code = self.attributes.get("status_code", 500 if not self.success else 200)
                record_api_request(endpoint, method, status_code, duration, **self.attributes)
            elif self.metric_type == "database":
                table = self.attributes.get("table", "unknown")
                row_count = self.attributes.get("row_count")
                record_database_query(self.operation, table, duration, self.success, row_count)

            if not self.success and exc_type:
                record_error(exc_type.__name__, self.operation, **self.attributes)

        except Exception as e:
            logger.debug(f"failed to record metrics in timer | error: {e}")

    def set_attribute(self, key: str, value: Any):
        """Set an attribute to be recorded with metrics."""
        self.attributes[key] = value

    def mark_success(self, success: bool = True):
        """Manually mark operation as successful or failed."""
        self.success = success

def get_metrics_status() -> Dict[str, Any]:
    """
    Get the current metrics system status.

    Returns:
        Dictionary with metrics status information
    """
    return {
        "enabled": _metrics_enabled,
        "meter_available": _meter is not None,
        "instruments": {
            "tool_invocation_counter": _tool_invocation_counter is not None,
            "tool_duration_histogram": _tool_duration_histogram is not None,
            "api_request_counter": _api_request_counter is not None,
            "api_duration_histogram": _api_duration_histogram is not None,
            "database_query_counter": _database_query_counter is not None,
            "database_duration_histogram": _database_duration_histogram is not None,
            "error_counter": _error_counter is not None
        }
    }
"""
OpenTelemetry decorators for instrumenting MCP server operations

Provides convenient decorators for adding tracing to MCP tools,
Observe API calls, and database operations.
"""

import functools
import inspect
import time
from typing import Any, Callable, Optional, Dict
from src.logging import get_logger

logger = get_logger('TELEMETRY_DECORATORS')

def trace_mcp_tool(tool_name: Optional[str] = None,
                   record_args: bool = True,
                   record_result: bool = False):
    """
    Decorator to trace MCP tool execution.

    Args:
        tool_name: Custom name for the tool (defaults to function name)
        record_args: Whether to record function arguments as span attributes
        record_result: Whether to record the result as a span attribute
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            # Import here to avoid circular imports
            from .config import get_tracer, _telemetry_initialized

            start_time = time.time()
            success = True
            tool_func_name = func.__name__

            # Execute function with or without telemetry
            try:
                if not _telemetry_initialized:
                    # If telemetry is not initialized, just call the function
                    result = await func(*args, **kwargs)
                    # Still record basic metrics if available
                    duration = time.time() - start_time
                    try:
                        from .metrics import record_tool_invocation
                        record_tool_invocation(tool_func_name, duration, True)
                    except ImportError:
                        pass
                    return result

                tracer = get_tracer()
                if not tracer:
                    result = await func(*args, **kwargs)
                    duration = time.time() - start_time
                    try:
                        from .metrics import record_tool_invocation
                        record_tool_invocation(tool_func_name, duration, True)
                    except ImportError:
                        pass
                    return result

                # Determine span name
                span_name = tool_name or f"mcp_tool.{func.__name__}"

                with tracer.start_as_current_span(span_name) as span:
                    try:
                        # Add basic span attributes
                        span.set_attribute("mcp.tool.name", func.__name__)
                        span.set_attribute("mcp.operation.type", "tool_execution")

                        # Record arguments if requested
                        if record_args:
                            _record_function_args(span, func, args, kwargs)

                        # Execute the function
                        result = await func(*args, **kwargs)

                        # Record result if requested and it's a reasonable size
                        if record_result and result is not None:
                            result_str = str(result)
                            if len(result_str) <= 1000:  # Limit result size
                                span.set_attribute("mcp.tool.result", result_str)
                            else:
                                span.set_attribute("mcp.tool.result_size", len(result_str))

                        # Mark span as successful
                        from opentelemetry import trace
                        span.set_status(trace.Status(trace.StatusCode.OK))

                        return result

                    except Exception as e:
                        # Record the exception with enhanced error details
                        success = False
                        from opentelemetry import trace
                        span.set_status(trace.Status(trace.StatusCode.ERROR, str(e)))
                        span.record_exception(e)
                        span.set_attribute("mcp.tool.error", True)
                        span.set_attribute("mcp.tool.error_type", type(e).__name__)

                        # Capture error message details
                        error_message = str(e)
                        if len(error_message) <= 1000:
                            span.set_attribute("mcp.tool.error_message", error_message)
                        else:
                            span.set_attribute("mcp.tool.error_message_size", len(error_message))

                        # For OPAL query errors, try to extract more specific details
                        if func.__name__ == "execute_opal_query" and "query" in kwargs:
                            query = kwargs.get("query", "")
                            if len(str(query)) <= 500:
                                span.set_attribute("mcp.opal.failed_query", str(query))
                            else:
                                span.set_attribute("mcp.opal.failed_query_size", len(str(query)))

                        # Check if this is an Observe API error with structured details
                        if "Error from Observe API:" in error_message:
                            try:
                                # Extract status code from error message
                                if " 400 " in error_message:
                                    span.set_attribute("mcp.api.error_status", 400)
                                elif " 401 " in error_message:
                                    span.set_attribute("mcp.api.error_status", 401)
                                elif " 403 " in error_message:
                                    span.set_attribute("mcp.api.error_status", 403)
                                elif " 404 " in error_message:
                                    span.set_attribute("mcp.api.error_status", 404)
                                elif " 500 " in error_message:
                                    span.set_attribute("mcp.api.error_status", 500)

                                # Try to extract JSON error details
                                import json
                                import re
                                json_match = re.search(r'\{.*\}', error_message)
                                if json_match:
                                    try:
                                        error_json = json.loads(json_match.group())
                                        if isinstance(error_json, dict) and 'message' in error_json:
                                            api_error_msg = str(error_json['message'])[:500]
                                            span.set_attribute("mcp.api.error_detail", api_error_msg)
                                    except (json.JSONDecodeError, ValueError):
                                        pass
                            except Exception:
                                pass

                        raise

            except Exception as e:
                success = False
                raise
            finally:
                # Always record metrics
                duration = time.time() - start_time
                try:
                    from .metrics import record_tool_invocation

                    # Extract additional attributes from kwargs for metrics
                    attributes = {}
                    if 'dataset_id' in kwargs or 'primary_dataset_id' in kwargs:
                        dataset_id = kwargs.get('primary_dataset_id') or kwargs.get('dataset_id')
                        if dataset_id:
                            attributes['dataset_id'] = dataset_id
                    if 'query' in kwargs:
                        query = kwargs.get('query', '')
                        attributes['query_length'] = len(str(query))
                    if 'time_range' in kwargs:
                        attributes['time_range'] = kwargs.get('time_range')

                    record_tool_invocation(tool_func_name, duration, success, **attributes)
                except ImportError:
                    pass

        return wrapper
    return decorator

def trace_observe_api_call(operation: Optional[str] = None):
    """
    Decorator to trace Observe API calls.

    Args:
        operation: Description of the API operation
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            from .config import get_tracer, _telemetry_initialized

            if not _telemetry_initialized:
                return await func(*args, **kwargs)

            tracer = get_tracer()
            if not tracer:
                return await func(*args, **kwargs)

            span_name = f"observe_api.{operation or func.__name__}"

            with tracer.start_as_current_span(span_name) as span:
                try:
                    # Add API-specific attributes
                    span.set_attribute("observe.operation.type", "api_call")
                    span.set_attribute("observe.function.name", func.__name__)

                    if operation:
                        span.set_attribute("observe.operation.name", operation)

                    # Look for common API parameters in kwargs
                    if 'endpoint' in kwargs:
                        span.set_attribute("observe.api.endpoint", kwargs['endpoint'])
                    if 'method' in kwargs:
                        span.set_attribute("observe.api.method", kwargs['method'])
                    if 'timeout' in kwargs:
                        span.set_attribute("observe.api.timeout", kwargs['timeout'])

                    result = await func(*args, **kwargs)

                    # Record response metadata if available
                    if isinstance(result, dict):
                        if 'status_code' in result:
                            span.set_attribute("observe.api.status_code", result['status_code'])
                        if 'error' in result:
                            span.set_attribute("observe.api.has_error", result['error'])

                            # Create span event for API errors with detailed error information
                            if result['error'] and 'message' in result:
                                try:
                                    error_message = result['message']
                                    event_attributes = {
                                        "observe.error.status_code": result.get('status_code', 'unknown'),
                                        "observe.error.full_message": error_message[:1000],
                                    }

                                    # Try to extract structured error info from the message
                                    import re
                                    import json
                                    if "Error from Observe API:" in error_message:
                                        # Extract JSON part from message like "Error from Observe API: 400 {...}"
                                        json_match = re.search(r'\{.*\}', error_message)
                                        if json_match:
                                            try:
                                                error_json = json.loads(json_match.group())
                                                if isinstance(error_json, dict):
                                                    if 'message' in error_json:
                                                        event_attributes["observe.error.api_message"] = str(error_json['message'])[:500]
                                                    if 'ok' in error_json:
                                                        event_attributes["observe.error.ok"] = str(error_json['ok'])
                                                    if 'code' in error_json:
                                                        event_attributes["observe.error.code"] = str(error_json['code'])
                                            except (json.JSONDecodeError, ValueError):
                                                event_attributes["observe.error.parse_failed"] = "true"

                                    # Create the span event with error details
                                    span.add_event(
                                        name="observe_api_error_response",
                                        attributes=event_attributes
                                    )
                                    logger.debug(f"created API error span event | attributes:{len(event_attributes)}")

                                except Exception as event_error:
                                    logger.warning(f"failed to create error span event | error:{event_error}")
                                    span.add_event("observe_api_error_event_failed", {"error": str(event_error)[:200]})

                    from opentelemetry import trace
                    span.set_status(trace.Status(trace.StatusCode.OK))
                    return result

                except Exception as e:
                    from opentelemetry import trace
                    span.set_status(trace.Status(trace.StatusCode.ERROR, str(e)))
                    span.record_exception(e)
                    span.set_attribute("observe.api.error", True)
                    span.set_attribute("observe.api.error_type", type(e).__name__)
                    raise

        return wrapper
    return decorator

def trace_database_operation(operation: Optional[str] = None,
                            table: Optional[str] = None):
    """
    Decorator to trace database operations.

    Args:
        operation: Type of database operation (query, insert, update, etc.)
        table: Database table being accessed
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            from .config import get_tracer, _telemetry_initialized

            if not _telemetry_initialized:
                return await func(*args, **kwargs)

            tracer = get_tracer()
            if not tracer:
                return await func(*args, **kwargs)

            span_name = f"db.{operation or func.__name__}"

            with tracer.start_as_current_span(span_name) as span:
                try:
                    # Add database-specific attributes
                    span.set_attribute("db.system", "postgresql")
                    span.set_attribute("db.operation", operation or func.__name__)

                    if table:
                        span.set_attribute("db.table.name", table)

                    # Look for query parameters
                    if 'query' in kwargs:
                        query = kwargs['query']
                        if len(query) <= 500:  # Limit query size in spans
                            span.set_attribute("db.statement", query)
                        else:
                            span.set_attribute("db.statement.size", len(query))

                    result = await func(*args, **kwargs)

                    # Record result metadata
                    if isinstance(result, list):
                        span.set_attribute("db.result.count", len(result))
                    elif hasattr(result, '__len__'):
                        span.set_attribute("db.result.count", len(result))

                    from opentelemetry import trace
                    span.set_status(trace.Status(trace.StatusCode.OK))
                    return result

                except Exception as e:
                    from opentelemetry import trace
                    span.set_status(trace.Status(trace.StatusCode.ERROR, str(e)))
                    span.record_exception(e)
                    span.set_attribute("db.error", True)
                    span.set_attribute("db.error_type", type(e).__name__)
                    raise

        return wrapper
    return decorator

def _record_function_args(span, func: Callable, args: tuple, kwargs: dict):
    """
    Record function arguments as span attributes with sensitive data filtering.

    Args:
        span: OpenTelemetry span
        func: Function being traced
        args: Positional arguments
        kwargs: Keyword arguments
    """
    try:
        # Get function signature
        sig = inspect.signature(func)

        # Sensitive parameter names to exclude
        sensitive_params = {
            'token', 'password', 'secret', 'key', 'auth', 'authorization',
            'access_token', 'api_key', 'private_key', 'public_key_pem'
        }

        # Bind arguments to parameter names
        bound_args = sig.bind_partial(*args, **kwargs)
        bound_args.apply_defaults()

        # Record safe arguments
        for param_name, value in bound_args.arguments.items():
            if param_name.lower() in sensitive_params:
                span.set_attribute(f"mcp.args.{param_name}", "[REDACTED]")
            elif param_name == 'ctx':
                # Special handling for MCP Context
                if hasattr(value, 'session_id'):
                    span.set_attribute("mcp.session.id", value.session_id)
            else:
                # Convert value to string and limit size
                value_str = str(value)
                if len(value_str) <= 200:
                    span.set_attribute(f"mcp.args.{param_name}", value_str)
                else:
                    span.set_attribute(f"mcp.args.{param_name}_size", len(value_str))

    except Exception as e:
        logger.debug(f"failed to record function args | error: {e}")
        # Don't fail the main operation if argument recording fails
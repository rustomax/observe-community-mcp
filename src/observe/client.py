"""
Observe API HTTP client

Provides the base HTTP client functionality for making requests to the Observe API
with proper error handling, logging, and response processing.
"""

import sys
import json
from typing import Dict, Any, Optional
from src.logging import get_logger

logger = get_logger('HTTP')
import httpx

from .config import OBSERVE_BASE_URL, get_observe_headers

# Import telemetry decorators
try:
    from src.telemetry.decorators import trace_observe_api_call
    from src.telemetry.utils import add_observe_context
except ImportError:
    # Fallback decorators if telemetry is not available
    def trace_observe_api_call(operation=None):
        def decorator(func):
            return func
        return decorator

    def add_observe_context(span, **kwargs):
        pass


@trace_observe_api_call(operation="http_request")
async def make_observe_request(
    method: str,
    endpoint: str,
    params: Optional[Dict[str, Any]] = None,
    json_data: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
    timeout: float = 30.0
) -> Dict[str, Any]:
    """
    Make a request to the Observe API.
    
    Args:
        method: HTTP method (GET, POST, etc.)
        endpoint: API endpoint (without base URL)
        params: Query parameters
        json_data: JSON data for POST requests
        headers: Additional headers (will be merged with default headers)
        timeout: Request timeout in seconds
        
    Returns:
        Response from the Observe API
        
    Raises:
        ValueError: If Observe API is not configured
    """
    if not OBSERVE_BASE_URL:
        raise ValueError("Observe API not configured. Please set OBSERVE_CUSTOMER_ID, OBSERVE_TOKEN, and OBSERVE_DOMAIN environment variables.")
    
    url = f"{OBSERVE_BASE_URL}/{endpoint.lstrip('/')}"
    request_headers = get_observe_headers(headers)
    
    # Log request details
    logger.debug(f"{method} {url} | params:{params} | data_size:{len(json.dumps(json_data)) if json_data else 0}")

    # Add detailed telemetry context
    try:
        from opentelemetry import trace
        span = trace.get_current_span()
        if span and span.is_recording():
            add_observe_context(span,
                              query_type=endpoint.split('/')[-1] if endpoint else None,
                              time_range=params.get('interval') if params else None)
            span.set_attribute("http.method", method)
            span.set_attribute("http.url", url)
            span.set_attribute("observe.endpoint", endpoint)
            if params:
                span.set_attribute("observe.params.count", len(params))
            if json_data:
                span.set_attribute("observe.request.size", len(json.dumps(json_data)))
                if 'query' in json_data:
                    query_info = json_data['query']
                    if isinstance(query_info, dict) and 'stages' in query_info:
                        span.set_attribute("observe.query.stages", len(query_info['stages']))
    except Exception:
        pass  # Don't fail the request if telemetry fails

    async with httpx.AsyncClient() as client:
        try:
            response = await client.request(
                method=method,
                url=url,
                params=params,
                json=json_data,
                headers=request_headers,
                timeout=timeout
            )
            
            if response.status_code >= 400:
                logger.warning(f"response {response.status_code} | size:{len(response.text)}")
            else:
                logger.debug(f"response {response.status_code} | size:{len(response.text)}")

            # Add response telemetry
            try:
                from opentelemetry import trace
                span = trace.get_current_span()
                if span and span.is_recording():
                    span.set_attribute("http.status_code", response.status_code)
                    span.set_attribute("observe.response.size", len(response.text))
                    if response.headers.get("Content-Type"):
                        span.set_attribute("observe.response.content_type", response.headers.get("Content-Type"))

                    # Check for specific response patterns
                    if "csv" in response.headers.get("Content-Type", ""):
                        lines = response.text.count('\n')
                        span.set_attribute("observe.response.rows", lines)
                    elif "json" in response.headers.get("Content-Type", ""):
                        try:
                            json_data = response.json()
                            if isinstance(json_data, dict):
                                span.set_attribute("observe.response.fields", len(json_data))
                        except:
                            pass
            except Exception:
                pass  # Don't fail the request if telemetry fails

            return _process_response(response)
            
        except httpx.HTTPError as e:
            logger.error(f"HTTP error: {str(e)}")
            return {
                "error": True,
                "message": f"HTTP error: {str(e)}"
            }
        except Exception as e:
            logger.error(f"Unexpected error: {str(e)}")
            import traceback
            traceback.print_exc(file=sys.stderr)
            return {
                "error": True,
                "message": f"Error: {str(e)}"
            }


def _process_response(response: httpx.Response) -> Dict[str, Any]:
    """
    Process HTTP response and return appropriate data structure.
    
    Args:
        response: HTTP response object
        
    Returns:
        Processed response data
    """
    if response.status_code >= 400:
        logger.warning(f"API error {response.status_code}: {response.text[:200]}")
        return {
            "error": True,
            "status_code": response.status_code,
            "message": f"Error from Observe API: {response.status_code} {response.text}"
        }
        
    content_type = response.headers.get("Content-Type", "")
    
    if content_type.startswith("application/json"):
        try:
            return response.json()
        except json.JSONDecodeError as e:
            logger.error(f"JSON decode failed: {e}")
            return {
                "error": True,
                "message": f"Invalid JSON response: {str(e)}",
                "raw_content": response.text
            }
    else:
        # Handle non-JSON responses (CSV, NDJSON, etc.)
        return {
            "data": response.text,
            "content_type": content_type,
            "headers": dict(response.headers)
        }


def _sanitize_headers_for_logging(headers: Dict[str, str]) -> Dict[str, str]:
    """
    Sanitize headers for logging by redacting sensitive information.
    
    Args:
        headers: Original headers dictionary
        
    Returns:
        Sanitized headers safe for logging
    """
    sanitized = {}
    sensitive_keys = {"authorization", "cookie", "x-api-key", "x-auth-token"}
    
    for key, value in headers.items():
        if key.lower() in sensitive_keys:
            sanitized[key] = "[REDACTED]"
        else:
            sanitized[key] = value
    
    return sanitized


class ObserveAPIError(Exception):
    """Custom exception for Observe API errors."""
    
    def __init__(self, message: str, status_code: Optional[int] = None, response_data: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.status_code = status_code
        self.response_data = response_data


@trace_observe_api_call(operation="http_request_strict")
async def make_observe_request_strict(
    method: str,
    endpoint: str,
    params: Optional[Dict[str, Any]] = None,
    json_data: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
    timeout: float = 30.0
) -> Dict[str, Any]:
    """
    Make a request to the Observe API with strict error handling.
    
    Unlike make_observe_request, this function raises exceptions for errors
    instead of returning error dictionaries.
    
    Args:
        method: HTTP method (GET, POST, etc.)
        endpoint: API endpoint (without base URL)
        params: Query parameters
        json_data: JSON data for POST requests
        headers: Additional headers
        timeout: Request timeout in seconds
        
    Returns:
        Response from the Observe API
        
    Raises:
        ObserveAPIError: For API errors
        ValueError: If Observe API is not configured
    """
    response = await make_observe_request(
        method=method,
        endpoint=endpoint,
        params=params,
        json_data=json_data,
        headers=headers,
        timeout=timeout
    )
    
    if isinstance(response, dict) and response.get("error"):
        raise ObserveAPIError(
            message=response.get("message", "Unknown API error"),
            status_code=response.get("status_code"),
            response_data=response
        )
    
    return response
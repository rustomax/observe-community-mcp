"""
Observe API HTTP client

Provides the base HTTP client functionality for making requests to the Observe API
with proper error handling, logging, and response processing.
"""

import sys
import json
from typing import Dict, Any, Optional
import httpx

from .config import OBSERVE_BASE_URL, get_observe_headers


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
    print(f"DEBUG: Making {method} request to URL: {url}", file=sys.stderr)
    print(f"DEBUG: Headers: {_sanitize_headers_for_logging(request_headers)}", file=sys.stderr)
    if params:
        print(f"DEBUG: Params: {params}", file=sys.stderr)
    if json_data:
        print(f"DEBUG: JSON data: {json.dumps(json_data, indent=2)}", file=sys.stderr)
        
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
            
            print(f"DEBUG: Response status code: {response.status_code}", file=sys.stderr)
            print(f"DEBUG: Response headers: {dict(response.headers)}", file=sys.stderr)
            
            return _process_response(response)
            
        except httpx.HTTPError as e:
            print(f"DEBUG: HTTP error: {str(e)}", file=sys.stderr)
            return {
                "error": True,
                "message": f"HTTP error: {str(e)}"
            }
        except Exception as e:
            print(f"DEBUG: Unexpected error: {str(e)}", file=sys.stderr)
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
        print(f"DEBUG: Error response body: {response.text}", file=sys.stderr)
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
            print(f"DEBUG: Failed to decode JSON response: {e}", file=sys.stderr)
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
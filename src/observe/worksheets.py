"""
Observe worksheet operations

Provides functions for exporting data from Observe worksheets
with flexible time parameter support.
"""

import sys
from typing import Optional

from .client import make_observe_request
from .config import validate_observe_config


async def export_worksheet(
    worksheet_id: str, 
    time_range: Optional[str] = "15m", 
    start_time: Optional[str] = None, 
    end_time: Optional[str] = None
) -> str:
    """
    Export data from an Observe worksheet.
    
    Args:
        worksheet_id: The ID of the worksheet to export
        time_range: Time range for the export (e.g., "15m", "1h", "24h"). Used if start_time and end_time are not provided. Defaults to "15m".
        start_time: Optional start time in ISO format (e.g., "2025-07-21T00:00:00Z")
        end_time: Optional end time in ISO format (e.g., "2025-07-22T00:00:00Z")
        
    Returns:
        The exported worksheet data as a string
    """
    # Validate configuration
    config_error = validate_observe_config()
    if config_error:
        return config_error
    
    if not worksheet_id or not worksheet_id.strip():
        return "Error: Worksheet ID cannot be empty."
    
    try:
        # Build time parameters
        params = _build_worksheet_time_parameters(time_range, start_time, end_time)
        
        # Log the request details
        print(f"DEBUG: Exporting worksheet {worksheet_id}", file=sys.stderr)
        print(f"DEBUG: Time parameters: {params}", file=sys.stderr)
        
        # Execute the worksheet export
        response = await make_observe_request(
            method="POST",
            endpoint=f"v1/meta/export/worksheet/{worksheet_id}",
            params=params
        )
        
        return _process_worksheet_response(response)
        
    except Exception as e:
        import traceback
        traceback.print_exc(file=sys.stderr)
        return f"Error in export_worksheet function: {str(e)}"


def _build_worksheet_time_parameters(
    time_range: Optional[str],
    start_time: Optional[str],
    end_time: Optional[str]
) -> dict:
    """
    Build time parameters for worksheet export.
    
    Args:
        time_range: Time range string
        start_time: Start time string  
        end_time: End time string
        
    Returns:
        Dictionary of time parameters for the API request
    """
    params = {}
    
    # Handle time parameters according to API rules:
    # Either two of startTime, endTime, and interval or interval alone can be specified
    print(f"DEBUG: Time parameters received - start_time: {start_time}, end_time: {end_time}, time_range: {time_range}", file=sys.stderr)
    
    # Check if start_time or end_time are None or empty strings
    if start_time in [None, "", "null"]:
        start_time = None
    if end_time in [None, "", "null"]:
        end_time = None
        
    if start_time and end_time:
        # Use explicit start and end times
        params["startTime"] = start_time
        params["endTime"] = end_time
        print(f"DEBUG: Using explicit start ({start_time}) and end ({end_time}) times", file=sys.stderr)
    elif start_time and time_range:
        # Use start time and interval
        params["startTime"] = start_time
        params["interval"] = time_range
        print(f"DEBUG: Using start time ({start_time}) and interval ({time_range})", file=sys.stderr)
    elif end_time and time_range:
        # Use end time and interval
        params["endTime"] = end_time
        params["interval"] = time_range
        print(f"DEBUG: Using end time ({end_time}) and interval ({time_range})", file=sys.stderr)
    elif time_range:
        # Use just interval (relative to now)
        params["interval"] = time_range
        print(f"DEBUG: Using just interval ({time_range}) relative to now", file=sys.stderr)
    else:
        # Default fallback to 15m interval
        params["interval"] = "15m"
        print(f"DEBUG: Using default interval (15m) relative to now", file=sys.stderr)
    
    return params


def _process_worksheet_response(response: dict) -> str:
    """
    Process worksheet export response.
    
    Args:
        response: API response dictionary
        
    Returns:
        Formatted response string
    """
    # Log response metadata
    if isinstance(response, dict):
        print(f"DEBUG: Response status: {response.get('status_code')}", file=sys.stderr)
        if 'data' in response and isinstance(response['data'], str) and len(response['data']) > 0:
            data_preview = response['data'].split('\\n')[0:2]
            print(f"DEBUG: First rows of data: {data_preview}", file=sys.stderr)
    
    # Handle error responses
    if isinstance(response, dict) and response.get("error"):
        return f"Error exporting worksheet: {response.get('message')}"
    
    # Handle paginated response (202 Accepted)
    if isinstance(response, dict) and response.get("content_type") == "text/html":
        headers = response.get("headers", {})
        if isinstance(headers, dict) and "X-Observe-Cursor-Id" in headers:
            cursor_id = headers["X-Observe-Cursor-Id"]
            next_page = headers.get("X-Observe-Next-Page", "")
            return f"Worksheet export accepted for asynchronous processing. Use cursor ID '{cursor_id}' to fetch results. Next page: {next_page}"
    
    # For successful responses, return the data
    if isinstance(response, dict) and "data" in response:
        data = response["data"]
        # If the data is very large, provide a summary
        if len(data) > 10000:  # Arbitrary threshold
            lines = data.count('\\n')
            first_lines = '\\n'.join(data.split('\\n')[:50])
            return f"Worksheet exported successfully with {lines} rows of data. First 50 lines:\\n\\n{first_lines}\\n\\n... (truncated, showing first 50 of {lines} lines)"
        return data
    
    # Handle unexpected response format
    return f"Unexpected response format. Please check the worksheet ID and try again. Response: {response}"


class WorksheetExporter:
    """
    Helper class for building and executing worksheet exports with various parameters.
    """
    
    def __init__(self, worksheet_id: str):
        """
        Initialize worksheet exporter.
        
        Args:
            worksheet_id: The ID of the worksheet to export
        """
        self.worksheet_id = worksheet_id
        self.time_range = "15m"
        self.start_time = None
        self.end_time = None
    
    def with_time_range(self, time_range: str) -> 'WorksheetExporter':
        """
        Set the time range for the export.
        
        Args:
            time_range: Time range string (e.g., "15m", "1h", "24h")
            
        Returns:
            Self for method chaining
        """
        self.time_range = time_range
        return self
    
    def with_absolute_times(self, start_time: str, end_time: str) -> 'WorksheetExporter':
        """
        Set absolute start and end times for the export.
        
        Args:
            start_time: Start time in ISO format
            end_time: End time in ISO format
            
        Returns:
            Self for method chaining
        """
        self.start_time = start_time
        self.end_time = end_time
        return self
    
    def with_start_time_and_range(self, start_time: str, time_range: str) -> 'WorksheetExporter':
        """
        Set start time and time range for the export.
        
        Args:
            start_time: Start time in ISO format
            time_range: Time range string
            
        Returns:
            Self for method chaining
        """
        self.start_time = start_time
        self.time_range = time_range
        return self
    
    def with_end_time_and_range(self, end_time: str, time_range: str) -> 'WorksheetExporter':
        """
        Set end time and time range for the export.
        
        Args:
            end_time: End time in ISO format
            time_range: Time range string
            
        Returns:
            Self for method chaining
        """
        self.end_time = end_time
        self.time_range = time_range
        return self
    
    async def execute(self) -> str:
        """
        Execute the worksheet export with configured parameters.
        
        Returns:
            The exported worksheet data as a string
        """
        return await export_worksheet(
            worksheet_id=self.worksheet_id,
            time_range=self.time_range,
            start_time=self.start_time,
            end_time=self.end_time
        )
    
    def get_params_summary(self) -> dict:
        """
        Get a summary of the configured parameters.
        
        Returns:
            Dictionary with parameter summary
        """
        return {
            "worksheet_id": self.worksheet_id,
            "time_range": self.time_range,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "export_type": self._determine_export_type()
        }
    
    def _determine_export_type(self) -> str:
        """
        Determine the type of export based on configured parameters.
        
        Returns:
            String describing the export type
        """
        if self.start_time and self.end_time:
            return "absolute_range"
        elif self.start_time and self.time_range:
            return "start_time_plus_range"
        elif self.end_time and self.time_range:
            return "end_time_plus_range"
        elif self.time_range:
            return "relative_range"
        else:
            return "default_range"
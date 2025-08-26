"""
Observe query operations

Provides functions for executing OPAL queries on datasets
with flexible time parameter support.
"""

import sys
import json
from typing import Dict, Any, Optional, List

from .client import make_observe_request
from .config import validate_observe_config
from .dataset_aliases import (
    validate_multi_dataset_query,
    resolve_dataset_aliases, 
    build_dataset_context
)


async def execute_opal_query(
    query: str, 
    dataset_id: str = None,
    primary_dataset_id: str = None,
    secondary_dataset_ids: Optional[List[str]] = None,
    dataset_aliases: Optional[Dict[str, str]] = None,
    time_range: Optional[str] = "1h", 
    start_time: Optional[str] = None, 
    end_time: Optional[str] = None, 
    row_count: Optional[int] = 1000, 
    format: Optional[str] = "csv",
    timeout: Optional[float] = None
) -> str:
    """
    Execute an OPAL query on single or multiple datasets.
    
    Args:
        query: The OPAL query to execute
        dataset_id: DEPRECATED: Use primary_dataset_id instead. Kept for backward compatibility.
        primary_dataset_id: The ID of the primary dataset to query
        secondary_dataset_ids: Optional list of secondary dataset IDs for joins/unions
        dataset_aliases: Optional mapping of aliases to dataset IDs (e.g., {"volumes": "44508111"})
        time_range: Time range for the query (e.g., "1h", "1d", "7d"). Used if start_time and end_time are not provided.
        start_time: Optional start time in ISO format (e.g., "2023-04-20T16:20:00Z")
        end_time: Optional end time in ISO format (e.g., "2023-04-20T16:30:00Z")
        row_count: Maximum number of rows to return (default: 1000, max: 100000)
        format: Output format, either "csv" or "ndjson" (default: "csv")
        timeout: Request timeout in seconds (default: uses client default of 30s)
        
    Returns:
        Query results as a formatted string
        
    Examples:
        # Single dataset query (backward compatible)
        execute_opal_query("filter metric = 'CPUUtilization'", dataset_id="44508123")
        
        # Multi-dataset join query
        execute_opal_query(
            query="join on(instanceId=@volumes.instanceId), volume_size:@volumes.size",
            primary_dataset_id="44508123",  # EC2 Instance Metrics
            secondary_dataset_ids=["44508111"],  # EBS Volumes
            dataset_aliases={"volumes": "44508111"}
        )
    """
    # Validate configuration
    config_error = validate_observe_config()
    if config_error:
        return config_error
    
    try:
        # Handle backward compatibility
        if dataset_id is not None and primary_dataset_id is None:
            primary_dataset_id = dataset_id
        elif primary_dataset_id is None:
            return "Error: Either dataset_id or primary_dataset_id must be specified"
        
        # Validate multi-dataset query if secondary datasets are provided
        if secondary_dataset_ids and len(secondary_dataset_ids) > 0:
            is_valid, validation_errors = validate_multi_dataset_query(
                query=query,
                primary_dataset_id=primary_dataset_id,
                secondary_dataset_ids=secondary_dataset_ids,
                dataset_aliases=dataset_aliases
            )
            
            if not is_valid:
                return f"Multi-dataset query validation failed: {'; '.join(validation_errors)}"
        
        # Validate and prepare parameters
        validated_params = _validate_query_parameters(
            query=query,
            primary_dataset_id=primary_dataset_id,
            secondary_dataset_ids=secondary_dataset_ids,
            dataset_aliases=dataset_aliases,
            time_range=time_range,
            start_time=start_time,
            end_time=end_time,
            row_count=row_count,
            format=format
        )
        
        if isinstance(validated_params, str):  # Error message
            return validated_params
        
        payload, params, headers = validated_params
        
        # Log the request details
        print(f"DEBUG: Executing OPAL query on primary dataset {primary_dataset_id}", file=sys.stderr)
        if secondary_dataset_ids:
            print(f"DEBUG: Secondary datasets: {secondary_dataset_ids}", file=sys.stderr)
        if dataset_aliases:
            print(f"DEBUG: Dataset aliases: {dataset_aliases}", file=sys.stderr)
        print(f"DEBUG: Time parameters: {params}", file=sys.stderr)
        print(f"DEBUG: Format: {format}", file=sys.stderr)
        print(f"DEBUG: Query: {query}", file=sys.stderr)
        
        # Execute the query
        response = await make_observe_request(
            method="POST",
            endpoint="v1/meta/export/query",
            params=params,
            json_data=payload,
            headers=headers,
            timeout=timeout if timeout is not None else 30.0
        )
        
        return _process_query_response(response)
        
    except Exception as e:
        import traceback
        traceback.print_exc(file=sys.stderr)
        return f"Error in execute_opal_query function: {str(e)}"


def _validate_query_parameters(
    query: str,
    primary_dataset_id: str,
    secondary_dataset_ids: Optional[List[str]],
    dataset_aliases: Optional[Dict[str, str]],
    time_range: Optional[str],
    start_time: Optional[str],
    end_time: Optional[str],
    row_count: Optional[int],
    format: Optional[str]
) -> tuple:
    """
    Validate and prepare query parameters for single or multi-dataset queries.
    
    Returns:
        Tuple of (payload, params, headers) or error string
    """
    # Validate row count
    if row_count and row_count > 100000:
        row_count = 100000
        print(f"WARNING: Row count limited to maximum of 100000", file=sys.stderr)
    
    # Prepare input datasets for the query
    input_datasets = [
        {
            "inputName": "main",
            "datasetId": primary_dataset_id
        }
    ]
    
    # Add secondary datasets if provided
    if secondary_dataset_ids:
        for i, secondary_id in enumerate(secondary_dataset_ids):
            # Use alias if provided, otherwise generate a name
            input_name = None
            if dataset_aliases:
                # Find alias for this dataset ID
                for alias, dataset_id_val in dataset_aliases.items():
                    if dataset_id_val == secondary_id:
                        input_name = alias
                        break
            
            if not input_name:
                input_name = f"dataset_{i+1}"
            
            input_datasets.append({
                "inputName": input_name,
                "datasetId": secondary_id
            })
    
    # Prepare query payload according to the API specification
    payload = {
        "query": {
            "stages": [
                {
                    "input": input_datasets,
                    "stageID": "query_stage",
                    "pipeline": query
                }
            ]
        },
        "rowCount": str(row_count or 1000)
    }
    
    # Set up time parameters
    params = _build_time_parameters(time_range, start_time, end_time)
    
    # Set headers for response format
    headers = {}
    if format and format.lower() == "ndjson":
        headers["Accept"] = "application/x-ndjson"
    else:  # Default to CSV
        headers["Accept"] = "text/csv"
    
    return payload, params, headers


def _build_time_parameters(
    time_range: Optional[str],
    start_time: Optional[str],
    end_time: Optional[str]
) -> Dict[str, str]:
    """
    Build time parameters for the API request.
    
    Args:
        time_range: Time range string
        start_time: Start time string
        end_time: End time string
        
    Returns:
        Dictionary of time parameters
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
    
    return params


def _process_query_response(response: Dict[str, Any]) -> str:
    """
    Process the query response and format it appropriately.
    
    Args:
        response: API response dictionary
        
    Returns:
        Formatted response string
    """
    # Log response metadata
    if isinstance(response, dict):
        print(f"DEBUG: Response status: {response.get('status_code')}", file=sys.stderr)
        print(f"DEBUG: Response headers: {response.get('headers', {})}", file=sys.stderr)
        if 'data' in response and isinstance(response['data'], str) and len(response['data']) > 0:
            data_preview = response['data'].split('\\n')[0:2]
            print(f"DEBUG: First rows of data: {data_preview}", file=sys.stderr)
    
    # Handle error responses
    if isinstance(response, dict) and response.get("error"):
        return f"Error executing query: {response.get('message')}"
    
    # Handle paginated response (202 Accepted)
    if isinstance(response, dict) and response.get("content_type") == "text/html":
        headers = response.get("headers", {})
        if isinstance(headers, dict) and "X-Observe-Cursor-Id" in headers:
            cursor_id = headers["X-Observe-Cursor-Id"]
            next_page = headers.get("X-Observe-Next-Page", "")
            return f"Query accepted for asynchronous processing. Use cursor ID '{cursor_id}' to fetch results. Next page: {next_page}"
    
    # For successful responses, return the data
    if isinstance(response, dict) and "data" in response:
        data = response["data"]
        # If the data is very large, provide a summary
        if len(data) > 10000:  # Arbitrary threshold
            lines = data.count('\\n')
            first_lines = '\\n'.join(data.split('\\n')[:50])
            return f"Query returned {lines} rows of data. First 50 lines:\\n\\n{first_lines}"
        return data
    
    # Handle unexpected response format
    return f"Unexpected response format. Please check the query and try again. Response: {response}"


class QueryBuilder:
    """
    Helper class for building OPAL queries programmatically.
    """
    
    def __init__(self, primary_dataset_id: str, secondary_dataset_ids: Optional[List[str]] = None, dataset_aliases: Optional[Dict[str, str]] = None):
        self.primary_dataset_id = primary_dataset_id
        self.secondary_dataset_ids = secondary_dataset_ids or []
        self.dataset_aliases = dataset_aliases or {}
        self.pipeline_steps = []
    
    def filter(self, condition: str) -> 'QueryBuilder':
        """Add a filter step to the query."""
        self.pipeline_steps.append(f"filter {condition}")
        return self
    
    def timechart(self, interval: str, aggregation: str) -> 'QueryBuilder':
        """Add a timechart step to the query."""
        self.pipeline_steps.append(f"timechart {interval}, {aggregation}")
        return self
    
    def top(self, limit: int, field: str) -> 'QueryBuilder':
        """Add a top step to the query."""
        self.pipeline_steps.append(f"top {limit}, {field}")
        return self
    
    def build(self) -> str:
        """Build the complete OPAL query string."""
        return " | ".join(self.pipeline_steps)
    
    async def execute(
        self, 
        time_range: Optional[str] = "1h",
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        row_count: Optional[int] = 1000,
        format: Optional[str] = "csv"
    ) -> str:
        """Execute the built query."""
        query = self.build()
        return await execute_opal_query(
            query=query,
            primary_dataset_id=self.primary_dataset_id,
            secondary_dataset_ids=self.secondary_dataset_ids,
            dataset_aliases=self.dataset_aliases,
            time_range=time_range,
            start_time=start_time,
            end_time=end_time,
            row_count=row_count,
            format=format
        )
"""
Observe query operations

Provides functions for executing OPAL queries on datasets
with flexible time parameter support.
"""

import sys
import json
from typing import Dict, Any, Optional, List
from src.logging import get_logger, opal_logger

logger = get_logger('QUERY')

from .client import make_observe_request
from .config import validate_observe_config
from .dataset_aliases import (
    validate_multi_dataset_query,
    resolve_dataset_aliases,
    build_dataset_context
)
from .error_enhancement import enhance_api_error

# Import OPAL query validation
from .opal_validation import validate_opal_query_structure


async def execute_opal_query(
    query: str, 
    dataset_id: str = None,
    primary_dataset_id: str = None,
    secondary_dataset_ids: Optional[List[str]] = None,
    dataset_aliases: Optional[Dict[str, str]] = None,
    time_range: Optional[str] = "1h",
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
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

    # Validate OPAL query structure and apply auto-fix transformations (H-INPUT-1)
    validation_result = validate_opal_query_structure(query, time_range=time_range)
    logger.info(f"Query validation result: is_valid={validation_result.is_valid}, "
                f"transformations={len(validation_result.transformations)}, "
                f"time_range={time_range}, "
                f"error_preview={str(validation_result.error_message)[:50] if validation_result.error_message else 'None'}")

    if not validation_result.is_valid:
        return f"OPAL Query Validation Error: {validation_result.error_message}"

    # Use transformed query if auto-fixes were applied
    if validation_result.transformed_query:
        logger.info(f"Using auto-fixed query (applied {len(validation_result.transformations)} transformations)")
        query = validation_result.transformed_query

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
            format=format
        )
        
        if isinstance(validated_params, str):  # Error message
            return validated_params
        
        payload, params, headers = validated_params
        
        # Log the request details
        logger.info(f"executing OPAL query | dataset:{primary_dataset_id}")
        if secondary_dataset_ids:
            logger.debug(f"secondary datasets | ids:{secondary_dataset_ids}")
        if dataset_aliases:
            logger.debug(f"dataset aliases | mapping:{dataset_aliases}")
        logger.debug(f"time parameters | params:{params}")
        logger.debug(f"output format | format:{format}")
        logger.debug(f"executing query | query:{query}")
        
        # Execute the query
        response = await make_observe_request(
            method="POST",
            endpoint="v1/meta/export/query",
            params=params,
            json_data=payload,
            headers=headers,
            timeout=timeout if timeout is not None else 30.0
        )

        result = _process_query_response(response, query, primary_dataset_id)

        # Append transformation feedback if auto-fixes were applied
        if validation_result.transformations:
            transformation_notes = "\n\n" + "="*60 + "\n"
            transformation_notes += "AUTO-FIX APPLIED - Query Transformations\n"
            transformation_notes += "="*60 + "\n\n"
            for i, transformation in enumerate(validation_result.transformations, 1):
                transformation_notes += f"{transformation}\n\n"
            transformation_notes += "The query above was automatically corrected and executed successfully.\n"
            transformation_notes += "Please use the corrected syntax in future queries.\n"
            transformation_notes += "="*60
            result = result + transformation_notes

        return result
        
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
    format: Optional[str]
) -> tuple:
    """
    Validate and prepare query parameters for single or multi-dataset queries.
    
    Returns:
        Tuple of (payload, params, headers) or error string
    """
    # Use default row count of 1000 (was previously parameterized)
    row_count = 1000
    
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
    logger.debug(f"time params | start:{start_time} | end:{end_time} | range:{time_range}")
    
    # Check if start_time or end_time are None or empty strings
    if start_time in [None, "", "null"]:
        start_time = None
    if end_time in [None, "", "null"]:
        end_time = None
        
    if start_time and end_time:
        # Use explicit start and end times
        params["startTime"] = start_time
        params["endTime"] = end_time
        logger.debug(f"using explicit time range | start:{start_time} | end:{end_time}")
    elif start_time and time_range:
        # Use start time and interval
        params["startTime"] = start_time
        params["interval"] = time_range
        logger.debug(f"using start time + interval | start:{start_time} | interval:{time_range}")
    elif end_time and time_range:
        # Use end time and interval
        params["endTime"] = end_time
        params["interval"] = time_range
        logger.debug(f"using end time + interval | end:{end_time} | interval:{time_range}")
    elif time_range:
        # Use just interval (relative to now)
        params["interval"] = time_range
        logger.debug(f"using relative interval | interval:{time_range}")
    
    return params


def _process_query_response(response: Dict[str, Any], query: str, dataset_id: str) -> str:
    """
    Process the query response and format it appropriately.

    Args:
        response: API response dictionary
        query: The OPAL query that was executed
        dataset_id: The dataset ID used in the query

    Returns:
        Formatted response string
    """
    # Log response metadata
    if isinstance(response, dict):
        logger.debug(f"response status | code:{response.get('status_code')}")
        logger.debug(f"response headers | headers:{response.get('headers', {})}")
        if 'data' in response and isinstance(response['data'], str) and len(response['data']) > 0:
            data_preview = response['data'].split('\\n')[0:2]
            logger.debug(f"response data preview | first_rows:{data_preview}")
    
    # Handle error responses
    if isinstance(response, dict) and response.get("error"):
        error_msg = response.get('message', 'Unknown error')
        logger.info(f"Original error message: {error_msg[:200]}")
        enhanced_msg = enhance_api_error(error_msg, query, dataset_id)
        logger.info(f"Enhanced error message: {enhanced_msg[:200]}")
        return f"Error executing query: {enhanced_msg}"
    
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
        # Log successful query execution with result metrics
        lines = data.count('\n') if data else 0
        data_size = len(data) if data else 0
        opal_logger.info(f"query successful | rows:{lines} | data_size:{data_size} bytes")

        # If the data is very large, provide a summary
        if len(data) > 10000:  # Arbitrary threshold
            first_lines = '\n'.join(data.split('\n')[:50])
            return f"Query returned {lines} rows of data. First 50 lines:\n\n{first_lines}"
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
            format=format
        )
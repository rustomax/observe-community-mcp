"""
Observe monitor operations

Provides functions for creating, listing, and managing MonitorV2 instances
in the Observe platform.
"""

import sys
import json
import re
from typing import Dict, Any, Optional, List, Union

from .client import make_observe_request
from .config import validate_observe_config


class MonitorResponse(dict):
    """Type for monitor response data."""
    pass


class ErrorResponse(dict):
    """Type for error response data."""
    pass


async def create_monitor(
    name: str, 
    description: str, 
    query: str, 
    dataset_id: str,
    threshold: float, 
    window: str, 
    frequency: str = "5m",
    threshold_column: str = "value",
    actions: Optional[List[str]] = None
) -> Union[MonitorResponse, ErrorResponse]:
    """
    Create a new MonitorV2 and bind to actions.
    
    IMPORTANT: The OPAL query must output a numeric value that can be compared against the threshold.
    
    NOTE: Due to a backend validation bug, the threshold_column must refer to a column that exists 
    in the INPUT dataset schema, not the query output schema. Common columns include:
    - "value" (numeric field in most datasets) - DEFAULT
    - "time" (timestamp field)
    - Other dataset-specific fields
    
    If you need to threshold on query output columns like "count", you must use the "value" column
    and structure your query to put the desired value in the "value" field.
    
    Examples:
    
    1. Error rate monitor (alerts when error count > 3 in 5 minutes):
       create_monitor(
           name="Cart Errors Monitor", 
           description="Shopping cart errors are high", 
           query="filter container = \\"cartservice\\" | filter body ~ \\"error\\" | timechart 5m, count()", 
           dataset_id="42428942", 
           threshold=3.0, 
           window="5m"
       )
       
    2. Latency monitor (alerts when p95 latency > 500ms):
       create_monitor(
           name="Cart Latency Monitor", 
           description="Shopping cart latency is high", 
           query="filter service_name = \\"cartservice\\" | align 1m, frame(back: 5m), latency:tdigest_quantile(tdigest_combine(m_tdigest(\\"span_duration_5m\\")), 0.95) | timechart 5m, latency", 
           dataset_id="42160988", 
           threshold=500000000, 
           window="5m"
       )
       
    3. Metric-based error count monitor (alerts when error count > 5 in 10 minutes):
       create_monitor(
           name="CartService Error Rate Alert", 
           description="Alert when CartService error rate exceeds threshold by monitoring error counts", 
           query="filter service_name = \\"cartservice\\" and metric = \\"span_error_count_5m\\" and value > 0 | timechart 5m, count()", 
           dataset_id="42160988", 
           threshold=5.0, 
           window="10m",
           frequency="5m"
       )
    
    Args:
        name: Name of the monitor
        description: Description of the monitor
        query: OPAL query to execute (must output a numeric value to compare against threshold)
        dataset_id: Dataset ID to query
        threshold: Threshold value for alerting
        window: Time window for evaluation (e.g., "5m", "1h")
        frequency: How often to run the monitor (e.g., "5m", "1h")
        threshold_column: Column name to compare against threshold (default: "value")
        actions: List of action IDs to trigger when monitor fires
        
    Returns:
        The created MonitorV2 object or error response
    """
    # Validate inputs
    validation_error = _validate_monitor_inputs(name, query, dataset_id)
    if validation_error:
        return {"error": True, "message": validation_error}
    
    # Validate configuration
    config_error = validate_observe_config()
    if config_error:
        return {"error": True, "message": config_error}
    
    try:
        # Prepare monitor data
        monitor_data = _build_monitor_data(
            name=name,
            description=description,
            query=query,
            dataset_id=dataset_id,
            threshold=threshold,
            window=window,
            frequency=frequency,
            threshold_column=threshold_column,
            actions=actions
        )
        
        # Make API request to create monitor
        print(f"DEBUG: Sending monitor data: {json.dumps(monitor_data, indent=2)}", file=sys.stderr)
        response = await make_observe_request(
            method="POST",
            endpoint="/v1/monitors",
            json_data=monitor_data
        )
        
        return _process_monitor_response(response, "create")
    
    except Exception as e:
        return _handle_monitor_exception(e, "creating")


async def list_monitors(
    name_exact: Optional[str] = None, 
    name_substring: Optional[str] = None
) -> Union[List[Dict[str, Any]], ErrorResponse]:
    """
    List MonitorV2 instances with optional filters.
    
    Args:
        name_exact: Limit to an exact string match
        name_substring: Limit to a substring match
        
    Returns:
        An array of monitor objects or error response
    """
    # Validate configuration
    config_error = validate_observe_config()
    if config_error:
        return {"error": True, "message": config_error}
    
    # Prepare query parameters
    params = {}
    if name_exact is not None:
        params["nameExact"] = name_exact
    if name_substring is not None:
        params["nameSubstring"] = name_substring
    
    try:
        # Make API request to list monitors
        print(f"DEBUG: Listing monitors with params: {params}", file=sys.stderr)
        response = await make_observe_request(
            method="GET",
            endpoint="/v1/monitors",
            params=params
        )
        
        return _process_list_monitors_response(response)
    
    except Exception as e:
        print(f"ERROR: Exception listing monitors: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        return {"error": True, "message": f"Exception listing monitors: {str(e)}"}


async def get_monitor(monitor_id: str) -> Union[Dict[str, Any], ErrorResponse]:
    """
    Get a specific MonitorV2 by ID.
    
    Args:
        monitor_id: The ID of the monitor to retrieve
        
    Returns:
        The monitor object with its complete structure or error response
    """
    if not monitor_id or not monitor_id.strip():
        return {"error": True, "message": "Monitor ID cannot be empty"}
    
    # Validate configuration
    config_error = validate_observe_config()
    if config_error:
        return {"error": True, "message": config_error}
    
    try:
        # Make API request to get the monitor
        print(f"DEBUG: Getting monitor with ID: {monitor_id}", file=sys.stderr)
        response = await make_observe_request(
            method="GET",
            endpoint=f"/v1/monitors/{monitor_id}"
        )
        
        return _process_monitor_response(response, "get")
    
    except Exception as e:
        print(f"ERROR: Exception getting monitor: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        return {"error": True, "message": f"Exception getting monitor: {str(e)}"}


def _validate_monitor_inputs(name: str, query: str, dataset_id: str) -> Optional[str]:
    """
    Validate monitor creation inputs.
    
    Args:
        name: Monitor name
        query: OPAL query
        dataset_id: Dataset ID
        
    Returns:
        Error message if validation fails, None if valid
    """
    if not name or not name.strip():
        return "Monitor name cannot be empty"
    
    if not query or not query.strip():
        return "Query cannot be empty"
    
    if not dataset_id or not dataset_id.strip():
        return "Dataset ID cannot be empty"
    
    return None


def _build_monitor_data(
    name: str,
    description: str,
    query: str,
    dataset_id: str,
    threshold: float,
    window: str,
    frequency: str,
    threshold_column: str,
    actions: Optional[List[str]]
) -> Dict[str, Any]:
    """
    Build the monitor data structure for API submission.
    
    Returns:
        Complete monitor data dictionary
    """
    # Format window and frequency with proper suffix if not present
    if window and not any(window.endswith(suffix) for suffix in ['s', 'm', 'h', 'd']):
        window = f"{window}s"  # Default to seconds
    
    if frequency and not any(frequency.endswith(suffix) for suffix in ['s', 'm', 'h', 'd']):
        frequency = f"{frequency}s"  # Default to seconds
    
    # Convert window and frequency to nanoseconds for API
    window_ns = convert_to_nanoseconds(window)
    frequency_ns = convert_to_nanoseconds(frequency)
    
    # Add description as a comment in the query if it's not already there
    if not query.strip().startswith("//"):
        query_with_comment = f"// {description}\\n{query}"
    else:
        query_with_comment = query
    
    monitor_data = {
        "name": name,
        "ruleKind": "Threshold",
        "description": description,
        "definition": {
            "inputQuery": {
                "outputStage": "output",
                "stages": [
                    {
                        "id": "output",
                        "input": {
                            "inputName": "dataset",
                            "datasetId": dataset_id
                        },
                        "pipeline": query_with_comment
                    }
                ]
            },
            "rules": [
                {
                    "level": "Error",
                    "threshold": {
                        "compareValues": [
                            {
                                "compareFn": "Greater",
                                "compareValue": {
                                    "float64": threshold
                                }
                            }
                        ],
                        "valueColumnName": threshold_column,
                        "aggregation": "AllOf"
                    }
                }
            ],
            "lookbackTime": str(window_ns),
            "dataStabilizationDelay": "0",
            "maxAlertsPerHour": "10",
            "groupings": [],
            "scheduling": {
                "transform": {
                    "freshnessGoal": str(frequency_ns)
                }
            }
        }
    }
    
    # Only add actions if provided and not empty
    if actions:
        action_rules = []
        for action_id in actions:
            action_rules.append({
                "actionId": action_id,
                "sendEndNotifications": False
            })
        monitor_data["actionRules"] = action_rules
    
    return monitor_data


def _process_monitor_response(response: Dict[str, Any], operation: str) -> Union[Dict[str, Any], ErrorResponse]:
    """
    Process monitor API response.
    
    Args:
        response: API response
        operation: Operation type for logging
        
    Returns:
        Processed response or error
    """
    # Check if response is a tuple (response, status_code)
    if isinstance(response, tuple) and len(response) == 2:
        result, status_code = response
        if status_code >= 400:
            error_msg = f"Failed to {operation} monitor: {result}"
            print(f"ERROR: {error_msg}", file=sys.stderr)
            return {"error": True, "message": error_msg}
        print(f"DEBUG: {operation.capitalize()}d monitor: {result}", file=sys.stderr)
        return result
    else:
        # If response is not a tuple, assume it's the direct response
        if isinstance(response, dict) and response.get("error"):
            return response
        print(f"DEBUG: {operation.capitalize()}d monitor: {response}", file=sys.stderr)
        return response


def _process_list_monitors_response(response: Dict[str, Any]) -> Union[List[Dict[str, Any]], ErrorResponse]:
    """
    Process list monitors API response and convert to terse format.
    
    Args:
        response: API response
        
    Returns:
        List of terse monitor objects or error response
    """
    # Handle error responses
    if isinstance(response, dict) and response.get("error"):
        return response
    
    # Check if response is a tuple (response, status_code)
    if isinstance(response, tuple) and len(response) == 2:
        result, status_code = response
        if status_code >= 400:
            error_msg = f"Failed to list monitors: {result}"
            print(f"ERROR: {error_msg}", file=sys.stderr)
            return {"error": True, "message": error_msg}
        monitors = _extract_monitors_from_response(result)
    else:
        monitors = _extract_monitors_from_response(response)
    
    # Convert to terse format for better readability
    return _convert_monitors_to_terse_format(monitors)


def _extract_monitors_from_response(response: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Extract monitors list from API response.
    
    Args:
        response: API response
        
    Returns:
        List of monitor dictionaries
    """
    if isinstance(response, list):
        return response
    elif isinstance(response, dict):
        if "monitors" in response:
            return response["monitors"]
        elif "data" in response:
            return response["data"]
        elif "items" in response:
            return response["items"]
    
    return []


def _convert_monitors_to_terse_format(monitors: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Convert monitors to terse format for better readability.
    
    Args:
        monitors: List of full monitor objects
        
    Returns:
        List of terse monitor objects
    """
    terse_monitors = []
    
    for monitor in monitors:
        terse_monitor = {
            "id": monitor.get("id", "unknown"),
            "name": monitor.get("name", "unknown"),
            "ruleKind": monitor.get("ruleKind", "unknown"),
            "description": monitor.get("description", "")
        }
        
        # Add additional useful info if available
        if "definition" in monitor:
            definition = monitor["definition"]
            
            # Extract query from inputQuery if available
            if "inputQuery" in definition and "stages" in definition["inputQuery"]:
                stages = definition["inputQuery"]["stages"]
                if stages and "pipeline" in stages[0]:
                    terse_monitor["query"] = stages[0]["pipeline"]
                if stages and "input" in stages[0] and "datasetId" in stages[0]["input"]:
                    terse_monitor["datasetId"] = stages[0]["input"]["datasetId"]
            
            # Extract threshold info if available
            if "rules" in definition and definition["rules"]:
                rule = definition["rules"][0]  # Take the first rule
                if "threshold" in rule:
                    threshold = rule["threshold"]
                    terse_monitor["thresholdType"] = "threshold"
                    if "compareValues" in threshold and isinstance(threshold["compareValues"], list) and threshold["compareValues"]:
                        compare_value = threshold["compareValues"][0]
                        if isinstance(compare_value, dict):
                            if "compareValue" in compare_value and "float64" in compare_value["compareValue"]:
                                terse_monitor["thresholdValue"] = compare_value["compareValue"]["float64"]
                            if "compareFn" in compare_value:
                                terse_monitor["thresholdOperator"] = compare_value["compareFn"]
                    terse_monitor["thresholdColumn"] = threshold.get("valueColumnName", "")
            
            # Extract time settings
            if "lookbackTime" in definition:
                terse_monitor["lookbackTime"] = definition["lookbackTime"]
            if "scheduling" in definition and definition["scheduling"] and "transform" in definition["scheduling"]:
                terse_monitor["freshnessGoal"] = definition["scheduling"]["transform"].get("freshnessGoal", "")
        
        terse_monitors.append(terse_monitor)
    
    return terse_monitors


def _handle_monitor_exception(e: Exception, operation: str) -> ErrorResponse:
    """
    Handle monitor operation exceptions.
    
    Args:
        e: Exception that occurred
        operation: Operation being performed
        
    Returns:
        Error response dictionary
    """
    error_msg = str(e)
    print(f"ERROR: Exception {operation} monitor: {e}", file=sys.stderr)
    import traceback
    traceback.print_exc(file=sys.stderr)
    
    # If there's a syntax error or other issue that suggests the LLM's query is invalid,
    # provide helpful guidance
    if "syntax error" in error_msg.lower() or "invalid" in error_msg.lower():
        return {
            "error": True, 
            "message": f"Exception {operation} monitor: {error_msg}",
            "suggestion": f"The monitor {operation} failed. Check your OPAL query syntax and ensure it outputs a numeric value that can be compared against the threshold. Review the examples in the create_monitor documentation."
        }
    
    return {"error": True, "message": f"Exception {operation} monitor: {error_msg}"}


def convert_to_nanoseconds(duration: str) -> int:
    """
    Convert a duration string (e.g., '5m', '1h') to nanoseconds.
    
    Args:
        duration: Duration string with suffix (s, m, h, d)
        
    Returns:
        Duration in nanoseconds
        
    Raises:
        ValueError: If duration format is invalid
    """
    # Extract the number and unit
    match = re.match(r'(\d+)([smhd])', duration)
    if not match:
        raise ValueError(f"Invalid duration format: {duration}. Expected format like '5m', '1h', etc.")
    
    value, unit = match.groups()
    value = int(value)
    
    # Convert to nanoseconds
    if unit == 's':
        return value * 1_000_000_000  # seconds to nanoseconds
    elif unit == 'm':
        return value * 60 * 1_000_000_000  # minutes to nanoseconds
    elif unit == 'h':
        return value * 60 * 60 * 1_000_000_000  # hours to nanoseconds
    elif unit == 'd':
        return value * 24 * 60 * 60 * 1_000_000_000  # days to nanoseconds
    else:
        raise ValueError(f"Unknown time unit: {unit}")
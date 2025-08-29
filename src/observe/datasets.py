"""
Observe dataset operations

Provides functions for listing datasets and retrieving dataset information
from the Observe platform.
"""

import sys
from typing import List, Dict, Any, Optional
from src.logging import get_logger

from .client import make_observe_request
from .config import validate_observe_config

logger = get_logger('DATASETS')


async def list_datasets(
    match: Optional[str] = None, 
    workspace_id: Optional[str] = None, 
    type: Optional[str] = None, 
    interface: Optional[str] = None
) -> str:
    """
    List available datasets in Observe.
    
    Args:
        match: Optional substring to match dataset names
        workspace_id: Optional workspace ID to filter by
        type: Optional dataset type to filter by (e.g., 'Event')
        interface: Optional interface to filter by (e.g., 'metric', 'log')
        
    Returns:
        Formatted string with dataset information
    """
    # Validate configuration
    config_error = validate_observe_config()
    if config_error:
        return config_error
    
    # Set up query parameters
    params = {}
    if match:
        params["match"] = match
    if workspace_id:
        params["workspaceId"] = workspace_id
    if type:
        params["type"] = type
    if interface:
        # The API requires this parameter to be passed as a list
        params["interface"] = [interface]
    
    try:
        # Log the request we're about to make
        logger.debug(f"requesting datasets | params:{params}")
        
        # Make the API call to fetch datasets
        response = await make_observe_request(
            method="GET",
            endpoint="v1/dataset",
            params=params
        )
        
        # Handle error responses
        if isinstance(response, dict) and response.get("error"):
            return f"Error listing datasets: {response.get('message')}"
        
        # Process successful response according to the OpenAPI spec
        if not isinstance(response, dict):
            return f"Unexpected response format: {type(response)}. Expected a dictionary."
        
        # Extract datasets from the response
        datasets = []
        if response.get("ok") and "data" in response and isinstance(response["data"], list):
            datasets = response["data"]
        else:
            return f"Unexpected response structure: {list(response.keys())}. Expected 'ok' and 'data' fields."
        
        if not datasets:
            return "No datasets found."
        
        # Format the response in a user-friendly way
        return _format_datasets_response(datasets)
        
    except Exception as e:
        import traceback
        traceback.print_exc(file=sys.stderr)
        return f"Error in list_datasets function: {str(e)}"


async def get_dataset_info(dataset_id: str) -> str:
    """
    Get detailed information about a specific dataset.
    
    Args:
        dataset_id: The ID of the dataset
        
    Returns:
        Formatted string with detailed dataset information
    """
    # Validate configuration
    config_error = validate_observe_config()
    if config_error:
        return config_error
    
    try:
        # Log the request we're about to make
        logger.debug(f"requesting dataset info | id:{dataset_id}")
        
        # Make the API call to fetch dataset information
        response = await make_observe_request(
            method="GET",
            endpoint=f"v1/dataset/{dataset_id}"
        )
        
        # Handle error responses
        if isinstance(response, dict) and response.get("error"):
            return f"Error getting dataset info: {response.get('message')}"
        
        # Process successful response according to the OpenAPI spec
        if not isinstance(response, dict):
            return f"Unexpected response format: {type(response)}. Expected a dictionary."
        
        # Extract dataset from the response
        if not response.get("ok") or "data" not in response:
            return f"Unexpected response structure: {list(response.keys())}. Expected 'ok' and 'data' fields."
        
        dataset = response["data"]
        if not dataset:
            return f"Dataset with ID {dataset_id} not found."
        
        # Log the raw dataset for debugging
        logger.debug(f"processing dataset | data:{dataset}")
        
        return _format_dataset_info(dataset, dataset_id)
        
    except Exception as e:
        import traceback
        traceback.print_exc(file=sys.stderr)
        return f"Error in get_dataset_info function: {str(e)}"


def _format_datasets_response(datasets: List[Dict[str, Any]]) -> str:
    """
    Format the list of datasets into a user-friendly string.
    
    Args:
        datasets: List of dataset dictionaries
        
    Returns:
        Formatted string representation
    """
    result = "Available Datasets:\\n\\n"
    
    for i, dataset in enumerate(datasets):
        try:
            # Log the raw dataset for debugging
            logger.debug(f"processing dataset {i+1} | data:{dataset}")
            
            # Extract dataset information with robust error handling
            dataset_id = _extract_dataset_field(dataset, "id", ["id", "meta.id"])
            name = _extract_dataset_field(dataset, "name", ["name", "config.name"])
            kind = _extract_dataset_field(dataset, "type", ["type", "kind", "state.kind", "state.type"])
            workspace_id = _extract_dataset_field(dataset, "workspaceId", ["workspaceId", "meta.workspaceId"])
            
            # Handle interfaces with robust error handling
            interface_str = _format_dataset_interfaces(dataset)
            
            # Add dataset information to the result
            result += f"Dataset {i+1}:\\n"
            result += f"ID: {dataset_id}\\n"
            result += f"Name: {name}\\n"
            result += f"Type: {kind}\\n"
            result += f"Workspace ID: {workspace_id}\\n"
            result += f"Interfaces: {interface_str}\\n"
            result += "-" * 40 + "\\n"
            
            # Limit to 10 datasets to avoid overwhelming output
            if i >= 9:
                result += "\\n(Showing first 10 datasets only. Use 'match' parameter to filter results.)\\n"
                break
                
        except Exception as e:
            logger.error(f"error processing dataset {i+1} | error:{e}")
            result += f"Error processing dataset {i+1}: {str(e)}\\n"
            result += "-" * 40 + "\\n"
    
    return result


def _format_dataset_info(dataset: Dict[str, Any], dataset_id: str) -> str:
    """
    Format detailed dataset information into a user-friendly string.
    
    Args:
        dataset: Dataset dictionary
        dataset_id: Dataset ID
        
    Returns:
        Formatted string representation
    """
    # Extract dataset information
    meta = dataset.get("meta", {})
    config = dataset.get("config", {})
    state = dataset.get("state", {})
    
    # Format the response in a user-friendly way
    result = f"Dataset Information for ID: {dataset_id}\\n\\n"
    
    # Basic information
    name = config.get("name", "Unnamed dataset")
    kind = state.get("kind", "Unknown type")
    workspace_id = meta.get("workspaceId", "Unknown")
    customer_id = meta.get("customerId", "Unknown")
    
    result += f"Name: {name}\\n"
    result += f"Type: {kind}\\n"
    result += f"Workspace ID: {workspace_id}\\n"
    result += f"Customer ID: {customer_id}\\n"
    
    # Creation and update information
    created_by = state.get("createdBy")
    created_date = state.get("createdDate")
    updated_by = state.get("updatedBy")
    updated_date = state.get("updatedDate")
    
    if created_by and created_date:
        result += f"Created: {created_date} (by {created_by})\\n"
    if updated_by and updated_date:
        result += f"Updated: {updated_date} (by {updated_by})\\n"
    
    # URL path
    url_path = state.get("urlPath")
    if url_path:
        result += f"URL Path: {url_path}\\n"
    
    # Interface information
    interfaces = state.get("interfaces")
    if interfaces:
        result += "\\nInterfaces:\\n"
        result += _format_detailed_interfaces(interfaces)
    
    # Schema information
    columns = state.get("columns")
    if columns and isinstance(columns, list):
        result += "\\nSchema:\\n"
        for column in columns:
            if isinstance(column, dict):
                col_name = column.get("name", "Unknown")
                col_type = column.get("type", "Unknown")
                result += f"  - {col_name} ({col_type})\\n"
    
    # Additional configuration
    label_field = config.get("labelField")
    if label_field:
        result += f"\\nLabel Field: {label_field}\\n"
    
    primary_key = config.get("primaryKey")
    if primary_key and isinstance(primary_key, list):
        result += f"Primary Key: {', '.join(primary_key)}\\n"
    
    return result


def _extract_dataset_field(dataset: Dict[str, Any], field_name: str, paths: List[str]) -> str:
    """
    Extract a field value from a dataset using multiple possible paths.
    
    Args:
        dataset: Dataset dictionary
        field_name: Field name for default value
        paths: List of dotted paths to try
        
    Returns:
        Extracted value or default
    """
    for path in paths:
        try:
            value = dataset
            for part in path.split('.'):
                if isinstance(value, dict) and part in value:
                    value = value[part]
                else:
                    break
            else:
                # Path succeeded
                return str(value) if value is not None else f"Unknown {field_name}"
        except (KeyError, TypeError, AttributeError):
            continue
    
    return f"Unknown {field_name}"


def _format_dataset_interfaces(dataset: Dict[str, Any]) -> str:
    """
    Format dataset interfaces for display.
    
    Args:
        dataset: Dataset dictionary
        
    Returns:
        Formatted interfaces string
    """
    # Try different possible locations for interfaces
    interfaces = None
    if "interfaces" in dataset and dataset["interfaces"] is not None:
        interfaces = dataset["interfaces"]
    elif "state" in dataset and isinstance(dataset["state"], dict) and "interfaces" in dataset["state"] and dataset["state"]["interfaces"] is not None:
        interfaces = dataset["state"]["interfaces"]
    
    if interfaces is None:
        return "None"
    
    if isinstance(interfaces, list):
        # Handle list of interfaces
        interface_strings = []
        for interface in interfaces:
            if isinstance(interface, dict):
                # Extract meaningful value from interface dict
                if 'name' in interface:
                    interface_strings.append(str(interface['name']))
                elif 'type' in interface:
                    interface_strings.append(str(interface['type']))
                elif 'path' in interface:
                    interface_strings.append(str(interface['path']))
                else:
                    interface_strings.append(str(interface))
            elif interface is not None:
                interface_strings.append(str(interface))
        return ", ".join(interface_strings) if interface_strings else "None"
    elif isinstance(interfaces, dict):
        return str(interfaces)
    else:
        return str(interfaces)


def _format_detailed_interfaces(interfaces) -> str:
    """
    Format detailed interface information.
    
    Args:
        interfaces: Interface data structure
        
    Returns:
        Formatted interfaces string
    """
    result = ""
    
    if isinstance(interfaces, list):
        for i, interface in enumerate(interfaces):
            if isinstance(interface, dict):
                # If interface is a complex object with path and mapping
                path = interface.get("path", "Unknown")
                result += f"  {i+1}. {path}\\n"
                
                # Show mapping if available
                mapping = interface.get("mapping")
                if mapping and isinstance(mapping, list):
                    result += "     Mapping:\\n"
                    for map_item in mapping:
                        if isinstance(map_item, dict):
                            interface_field = map_item.get("interfaceField", "Unknown")
                            field = map_item.get("field", "Unknown")
                            result += f"       - {interface_field} → {field}\\n"
            else:
                # If interface is a simple string
                result += f"  {i+1}. {interface}\\n"
    else:
        # Handle case where interfaces is not a list
        result += f"  {interfaces}\\n"
    
    return result
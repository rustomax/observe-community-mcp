"""
Observe API client package

Provides organized modules for interacting with the Observe platform API,
including datasets, queries, monitors, and worksheet operations.
"""

from .client import make_observe_request, make_observe_request_strict, ObserveAPIError
from .config import (
    get_observe_config, 
    validate_observe_config,
    get_observe_headers,
    is_observe_configured,
    OBSERVE_HEADERS, 
    OBSERVE_BASE_URL
)
from .datasets import list_datasets, get_dataset_info
from .queries import execute_opal_query, QueryBuilder
from .monitors import create_monitor, list_monitors, get_monitor, convert_to_nanoseconds
from .worksheets import export_worksheet, WorksheetExporter

__all__ = [
    # Client functions
    'make_observe_request',
    'make_observe_request_strict',
    'ObserveAPIError',
    
    # Configuration
    'get_observe_config',
    'validate_observe_config', 
    'get_observe_headers',
    'is_observe_configured',
    'OBSERVE_HEADERS', 
    'OBSERVE_BASE_URL',
    
    # Dataset operations
    'list_datasets',
    'get_dataset_info',
    
    # Query operations
    'execute_opal_query',
    'QueryBuilder',
    
    # Monitor operations
    'create_monitor',
    'list_monitors', 
    'get_monitor',
    'convert_to_nanoseconds',
    
    # Worksheet operations
    'export_worksheet',
    'WorksheetExporter'
]
"""
Observe API client package

Provides organized modules for interacting with the Observe platform API,
including datasets and queries operations.
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
    'QueryBuilder'
]
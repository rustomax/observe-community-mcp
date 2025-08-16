"""
Observe API configuration

Handles environment variables, authentication headers, and base URL configuration
for the Observe platform API.
"""

import os
from typing import Dict, Tuple, Optional


def get_observe_config() -> Tuple[str, str, str, bool]:
    """
    Get Observe API configuration from environment variables.
    
    Returns:
        Tuple of (customer_id, token, domain, is_configured)
        is_configured is False if any required variables are missing
    """
    customer_id = os.getenv("OBSERVE_CUSTOMER_ID", "")
    token = os.getenv("OBSERVE_TOKEN", "")
    domain = os.getenv("OBSERVE_DOMAIN", "")
    
    is_configured = bool(customer_id and token and domain)
    
    return customer_id, token, domain, is_configured


def validate_observe_config() -> Optional[str]:
    """
    Validate Observe API configuration.
    
    Returns:
        Error message if configuration is invalid, None if valid
    """
    customer_id, token, domain, is_configured = get_observe_config()
    
    if not is_configured:
        missing = []
        if not customer_id:
            missing.append("OBSERVE_CUSTOMER_ID")
        if not token:
            missing.append("OBSERVE_TOKEN")
        if not domain:
            missing.append("OBSERVE_DOMAIN")
        
        return f"Error: Observe API credentials not configured. Please set {', '.join(missing)} environment variables."
    
    return None


# Get configuration
OBSERVE_CUSTOMER_ID, OBSERVE_TOKEN, OBSERVE_DOMAIN, _IS_CONFIGURED = get_observe_config()

# Base URL for Observe API
OBSERVE_BASE_URL = f"https://{OBSERVE_CUSTOMER_ID}.{OBSERVE_DOMAIN}" if _IS_CONFIGURED else ""

# Headers for Observe API requests
OBSERVE_HEADERS = {
    "Authorization": f"Bearer {OBSERVE_CUSTOMER_ID} {OBSERVE_TOKEN}",
    "Content-Type": "application/json"
} if _IS_CONFIGURED else {}


def get_observe_headers(additional_headers: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """
    Get Observe API headers with optional additional headers.
    
    Args:
        additional_headers: Optional additional headers to merge
        
    Returns:
        Complete headers dictionary for API requests
    """
    headers = OBSERVE_HEADERS.copy()
    
    if additional_headers:
        headers.update(additional_headers)
    
    return headers


def is_observe_configured() -> bool:
    """
    Check if Observe API is properly configured.
    
    Returns:
        True if all required environment variables are set
    """
    return _IS_CONFIGURED
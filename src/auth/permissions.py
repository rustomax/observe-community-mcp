"""
Permission utilities for analyzing and managing user permissions.

Provides functions for determining user capabilities, filtering sensitive data,
and generating permission reports.
"""

import os
import sys
from typing import Dict, Any, List, Optional
from datetime import datetime
from fastmcp.server.dependencies import get_access_token, AccessToken

from .jwt_utils import decode_jwt_payload, extract_claims_from_token
from .scopes import get_user_scopes, get_effective_scopes


def get_user_permissions(scopes: Optional[List[str]] = None) -> Dict[str, bool]:
    """
    Generate a permissions dictionary based on user scopes.
    
    Args:
        scopes: User scopes (if None, will fetch from current token)
        
    Returns:
        Dictionary mapping permission names to boolean values
    """
    if scopes is None:
        scopes = get_user_scopes()
    
    effective_scopes = get_effective_scopes(scopes)
    
    return {
        "admin_access": "admin" in effective_scopes,
        "read_access": "read" in effective_scopes,
        "write_access": "write" in effective_scopes,
        "smart_tools_access": "smart_tools" in effective_scopes,
        "monitor_create": "admin" in effective_scopes or "write" in effective_scopes,
        "monitor_read": any(s in effective_scopes for s in ["admin", "write", "read"]),
        "system_info": "admin" in effective_scopes,
        "query_execute": any(s in effective_scopes for s in ["admin", "write", "read"]),
        "dataset_access": any(s in effective_scopes for s in ["admin", "read"]),
        "worksheet_export": any(s in effective_scopes for s in ["admin", "write", "read"])
    }


def get_auth_token_info() -> Dict[str, Any]:
    """
    Get comprehensive authentication and authorization information.
    
    Returns:
        Dictionary with authentication status, scopes, permissions, and claims
    """
    try:
        # Get the access token from the request
        access_token: AccessToken = get_access_token()
        
        # Initialize the result dictionary with basic info
        result = {
            "authenticated": True,
            "client_id": access_token.client_id,
            "token_type": "Bearer"
        }
        
        # Add expiration if available
        if hasattr(access_token, 'expires_at'):
            result["expires_at"] = access_token.expires_at
        
        # Get scopes - first try AccessToken.scopes
        scopes = []
        if access_token.scopes:
            scopes = access_token.scopes
            result["scopes"] = scopes
        
        # If no scopes found, try to extract from JWT payload
        if not scopes and hasattr(access_token, 'token'):
            payload = decode_jwt_payload(access_token.token)
            if payload:
                # Extract scopes
                if 'scopes' in payload:
                    scopes = payload['scopes']
                    result["scopes"] = scopes
                
                # Add other useful claims
                standard_claims = ['iss', 'aud', 'exp', 'iat', 'sub']
                claims = extract_claims_from_token(access_token.token, standard_claims)
                result.update(claims)
        
        # Add permissions information based on scopes
        result["permissions"] = get_user_permissions(scopes)
        
        # Add effective scopes (including inherited ones)
        result["effective_scopes"] = get_effective_scopes(scopes)
        
        # Minimal logging for server-side debugging
        print(f"Auth info requested by {access_token.client_id}, scopes: {scopes}", file=sys.stderr)
        
        return result
    except Exception as e:
        print(f"Error getting auth token info: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        
        # Return error information
        return {
            "error": f"Exception getting auth token info: {str(e)}",
            "authenticated": False,
            "note": "This may indicate that no valid token was provided or that token validation failed"
        }


def filter_sensitive_environment() -> Dict[str, str]:
    """
    Filter environment variables to exclude sensitive information.
    
    Returns:
        Dictionary with filtered environment variables
    """
    # Define sensitive environment variable patterns to filter out
    sensitive_patterns = [
        'key', 'secret', 'password', 'token', 'credential', 'auth', 
        'api_', 'cert', 'private', 'salt', 'hash'
    ]
    
    # Filter environment variables to exclude sensitive information
    filtered_env = {}
    for key, value in os.environ.items():
        # Skip any env var with sensitive patterns in key
        if any(pattern in key.lower() for pattern in sensitive_patterns):
            filtered_env[key] = "[REDACTED]"
        else:
            filtered_env[key] = value
    
    return filtered_env


def get_admin_system_info() -> Dict[str, Any]:
    """
    Get comprehensive system information for admin users.
    
    Returns:
        Dictionary with system information
    """
    try:
        system_info = {
            "python_version": sys.version,
            "python_path": sys.path,
            "environment": filter_sensitive_environment(),
            "server_time": datetime.now().isoformat(),
            "server_pid": os.getpid(),
        }
        
        return {
            "success": True,
            "message": "Admin access granted",
            "system_info": system_info
        }
    except Exception as e:
        return {
            "error": True,
            "message": f"Error getting system info: {str(e)}"
        }


def get_public_server_info() -> Dict[str, Any]:
    """
    Get basic public server information available to all users.
    
    Returns:
        Dictionary with public server information
    """
    try:
        server_info = {
            "server_name": "observe-epic",
            "server_version": "1.0.0",
            "server_time": datetime.now().isoformat(),
            "python_version": sys.version.split()[0]  # Just the version number
        }
        
        return {
            "success": True,
            "server_info": server_info
        }
    except Exception as e:
        return {
            "error": True,
            "message": f"Error getting public server info: {str(e)}"
        }


class PermissionChecker:
    """
    Class-based permission checking for complex scenarios.
    """
    
    def __init__(self, user_scopes: Optional[List[str]] = None):
        """
        Initialize permission checker.
        
        Args:
            user_scopes: User scopes (if None, will fetch from current token)
        """
        self.user_scopes = user_scopes or get_user_scopes()
        self.effective_scopes = get_effective_scopes(self.user_scopes)
        self.permissions = get_user_permissions(self.user_scopes)
    
    def can_access_admin_tools(self) -> bool:
        """Check if user can access admin-only tools."""
        return self.permissions["admin_access"]
    
    def can_create_monitors(self) -> bool:
        """Check if user can create monitors."""
        return self.permissions["monitor_create"]
    
    def can_read_data(self) -> bool:
        """Check if user can read data (datasets, queries, etc.)."""
        return self.permissions["read_access"]
    
    def can_write_data(self) -> bool:
        """Check if user can write/modify data."""
        return self.permissions["write_access"]
    
    def can_execute_queries(self) -> bool:
        """Check if user can execute OPAL queries."""
        return self.permissions["query_execute"]
    
    def can_export_worksheets(self) -> bool:
        """Check if user can export worksheets."""
        return self.permissions["worksheet_export"]
    
    def can_use_smart_tools(self) -> bool:
        """Check if user can use LLM-powered smart tools."""
        return self.permissions["smart_tools_access"]
    
    def get_permission_summary(self) -> Dict[str, Any]:
        """
        Get a comprehensive permission summary.
        
        Returns:
            Dictionary with permission details
        """
        return {
            "user_scopes": self.user_scopes,
            "effective_scopes": self.effective_scopes,
            "permissions": self.permissions,
            "access_level": self._determine_access_level()
        }
    
    def _determine_access_level(self) -> str:
        """Determine overall access level for the user."""
        if self.permissions["admin_access"]:
            return "admin"
        elif self.permissions["write_access"]:
            return "write"
        elif self.permissions["read_access"]:
            return "read"
        else:
            return "none"


def check_tool_access(tool_name: str, user_scopes: Optional[List[str]] = None) -> Dict[str, Any]:
    """
    Check if user has access to a specific tool.
    
    Args:
        tool_name: Name of the tool to check
        user_scopes: User scopes (if None, will fetch from current token)
        
    Returns:
        Dictionary with access information
    """
    checker = PermissionChecker(user_scopes)
    
    # Tool access mapping
    tool_requirements = {
        "admin_system_info": checker.can_access_admin_tools,
        "create_monitor": checker.can_create_monitors,
        "list_monitors": checker.can_read_data,
        "get_monitor": checker.can_read_data,
        "execute_opal_query": checker.can_execute_queries,
        "list_datasets": checker.can_read_data,
        "get_dataset_info": checker.can_read_data,
        "export_worksheet": checker.can_export_worksheets,
        "get_relevant_docs": checker.can_read_data,
        "recommend_runbook": checker.can_read_data,
        "execute_nlp_query": checker.can_use_smart_tools
    }
    
    has_access = True
    if tool_name in tool_requirements:
        has_access = tool_requirements[tool_name]()
    
    return {
        "tool": tool_name,
        "has_access": has_access,
        "access_level": checker._determine_access_level(),
        "user_scopes": checker.user_scopes
    }
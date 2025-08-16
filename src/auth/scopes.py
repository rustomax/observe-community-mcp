"""
Scope-based authorization middleware for MCP tools.

Provides decorators and utilities for protecting MCP tools based on JWT token scopes.
"""

import sys
from functools import wraps
from typing import List, Dict, Any, Optional
from fastmcp import Context
from fastmcp.server.dependencies import get_access_token, AccessToken

from .jwt_utils import extract_scopes_from_token


def requires_scopes(required_scopes: List[str]):
    """
    Middleware decorator that protects tools based on JWT token scopes.
    
    Args:
        required_scopes: List of scopes required to access the tool.
        
    Returns:
        Decorator function that wraps the tool function.
        
    Example:
        @requires_scopes(['admin', 'write'])
        async def protected_tool(ctx: Context, data: str) -> str:
            return f"Protected operation on {data}"
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(ctx: Context, *args, **kwargs):
            # Get JWT token scopes
            jwt_scopes = []
            try:
                # Get the access token
                access_token = get_access_token()
                
                # Try to get scopes from AccessToken object first
                if access_token.scopes:
                    jwt_scopes = access_token.scopes
                # If not available, try to extract from raw token
                elif hasattr(access_token, 'token'):
                    jwt_scopes = extract_scopes_from_token(access_token.token)
                        
                # Check if user has required scopes
                has_required_scopes = any(scope in jwt_scopes for scope in required_scopes)
                if not has_required_scopes:
                    print(f"Access denied: Required scopes {required_scopes}, but user has {jwt_scopes}", file=sys.stderr)
                    return {
                        "error": True,
                        "message": f"Access denied: You don't have the required permissions. Required: {required_scopes}"
                    }
                    
                # User has required scopes, proceed with the function
                return await func(ctx, *args, **kwargs)
            except Exception as e:
                print(f"Error in requires_scopes middleware: {e}", file=sys.stderr)
                return {
                    "error": True,
                    "message": f"Authentication error: {str(e)}"
                }
        return wrapper
    return decorator


def get_user_scopes() -> List[str]:
    """
    Get the current user's scopes from the JWT token.
    
    Returns:
        List of scopes for the current user
    """
    try:
        access_token = get_access_token()
        
        # Try to get scopes from AccessToken object first
        if access_token.scopes:
            return access_token.scopes
        
        # If not available, try to extract from raw token
        if hasattr(access_token, 'token'):
            return extract_scopes_from_token(access_token.token)
        
        return []
    except Exception as e:
        print(f"Error getting user scopes: {e}", file=sys.stderr)
        return []


def check_scope_access(required_scopes: List[str], user_scopes: Optional[List[str]] = None) -> bool:
    """
    Check if user has access based on required scopes.
    
    Args:
        required_scopes: List of required scopes
        user_scopes: User's scopes (if None, will fetch from current token)
        
    Returns:
        True if user has required access, False otherwise
    """
    if user_scopes is None:
        user_scopes = get_user_scopes()
    
    return any(scope in user_scopes for scope in required_scopes)


def require_admin_scope():
    """
    Decorator that requires admin scope.
    Convenience wrapper for requires_scopes(['admin']).
    """
    return requires_scopes(['admin'])


def require_write_access():
    """
    Decorator that requires write access (admin or write scope).
    """
    return requires_scopes(['admin', 'write'])


def require_read_access():
    """
    Decorator that requires read access (admin, write, or read scope).
    """
    return requires_scopes(['admin', 'write', 'read'])


class ScopeValidator:
    """
    Class-based scope validation for more complex scenarios.
    """
    
    def __init__(self, required_scopes: List[str]):
        """
        Initialize scope validator.
        
        Args:
            required_scopes: List of required scopes
        """
        self.required_scopes = required_scopes
    
    def validate(self, user_scopes: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Validate user scopes against requirements.
        
        Args:
            user_scopes: User's scopes (if None, will fetch from current token)
            
        Returns:
            Dictionary with validation results
        """
        if user_scopes is None:
            user_scopes = get_user_scopes()
        
        has_access = check_scope_access(self.required_scopes, user_scopes)
        
        return {
            "has_access": has_access,
            "required_scopes": self.required_scopes,
            "user_scopes": user_scopes,
            "missing_scopes": [scope for scope in self.required_scopes if scope not in user_scopes]
        }
    
    def get_access_error(self) -> Dict[str, Any]:
        """
        Get standardized access denied error response.
        
        Returns:
            Error response dictionary
        """
        return {
            "error": True,
            "message": f"Access denied: You don't have the required permissions. Required: {self.required_scopes}"
        }


# Scope hierarchy definitions
SCOPE_HIERARCHY = {
    'admin': ['admin', 'smart_tools', 'write', 'read'],  # Admin can do everything
    'smart_tools': ['smart_tools', 'read'],              # Smart tools includes read
    'write': ['write', 'read'],                          # Write includes read
    'read': ['read']                                     # Read only
}


def get_effective_scopes(user_scopes: List[str]) -> List[str]:
    """
    Get all effective scopes based on scope hierarchy.
    
    Args:
        user_scopes: User's assigned scopes
        
    Returns:
        List of all effective scopes including inherited ones
    """
    effective_scopes = set()
    
    for scope in user_scopes:
        if scope in SCOPE_HIERARCHY:
            effective_scopes.update(SCOPE_HIERARCHY[scope])
        else:
            effective_scopes.add(scope)
    
    return list(effective_scopes)


def check_hierarchical_access(required_scopes: List[str], user_scopes: Optional[List[str]] = None) -> bool:
    """
    Check access using scope hierarchy rules.
    
    Args:
        required_scopes: List of required scopes
        user_scopes: User's scopes (if None, will fetch from current token)
        
    Returns:
        True if user has required access through hierarchy, False otherwise
    """
    if user_scopes is None:
        user_scopes = get_user_scopes()
    
    effective_scopes = get_effective_scopes(user_scopes)
    return any(scope in effective_scopes for scope in required_scopes)
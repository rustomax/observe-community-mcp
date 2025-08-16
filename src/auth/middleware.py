"""
FastMCP authentication integration and middleware.

Provides functions for setting up and configuring FastMCP authentication
with proper error handling and logging.
"""

import os
import sys
from typing import Optional
from fastmcp import FastMCP
from fastmcp.server.auth.providers.jwt import JWTVerifier


def setup_auth_provider(public_key_pem: Optional[str] = None) -> JWTVerifier:
    """
    Set up and configure the JWTVerifier for FastMCP.
    
    Args:
        public_key_pem: PEM-encoded public key. If None, will read from environment.
        
    Returns:
        Configured JWTVerifier instance
    """
    # Get public key from parameter or environment variable
    if public_key_pem is None:
        public_key_pem = os.getenv("PUBLIC_KEY_PEM", "")
    
    # Log warning if public key is not set
    if not public_key_pem:
        print("WARNING: PUBLIC_KEY_PEM not found in environment variables. Authentication may fail.", file=sys.stderr)
        print("Please set PUBLIC_KEY_PEM in your .env file with the correct public key.", file=sys.stderr)
    
    # Configure JWTVerifier with the public key
    return JWTVerifier(public_key=public_key_pem)


def create_authenticated_mcp(server_name: str = "observe-epic", public_key_pem: Optional[str] = None) -> FastMCP:
    """
    Create a FastMCP instance with authentication configured.
    
    Args:
        server_name: Name for the MCP server
        public_key_pem: PEM-encoded public key. If None, will read from environment.
        
    Returns:
        Configured FastMCP instance with authentication
    """
    auth_provider = setup_auth_provider(public_key_pem)
    return FastMCP(name=server_name, auth=auth_provider)


def validate_auth_configuration() -> dict:
    """
    Validate authentication configuration and return status.
    
    Returns:
        Dictionary with configuration status and recommendations
    """
    public_key_pem = os.getenv("PUBLIC_KEY_PEM", "")
    
    status = {
        "configured": bool(public_key_pem),
        "public_key_length": len(public_key_pem) if public_key_pem else 0,
        "warnings": [],
        "recommendations": []
    }
    
    if not public_key_pem:
        status["warnings"].append("PUBLIC_KEY_PEM not found in environment variables")
        status["recommendations"].append("Set PUBLIC_KEY_PEM in your .env file with the correct public key")
    elif len(public_key_pem) < 100:  # Basic sanity check
        status["warnings"].append("PUBLIC_KEY_PEM appears to be too short for a valid PEM key")
        status["recommendations"].append("Verify that PUBLIC_KEY_PEM contains a complete PEM-encoded public key")
    elif not public_key_pem.startswith("-----BEGIN"):
        status["warnings"].append("PUBLIC_KEY_PEM does not appear to be in PEM format")
        status["recommendations"].append("Ensure PUBLIC_KEY_PEM is a properly formatted PEM-encoded public key")
    
    return status


class AuthMiddleware:
    """
    Authentication middleware wrapper for additional functionality.
    """
    
    def __init__(self, auth_provider: JWTVerifier):
        """
        Initialize auth middleware.
        
        Args:
            auth_provider: Configured JWTVerifier instance
        """
        self.auth_provider = auth_provider
        self._stats = {
            "successful_authentications": 0,
            "failed_authentications": 0,
            "unauthorized_attempts": 0
        }
    
    def get_stats(self) -> dict:
        """
        Get authentication statistics.
        
        Returns:
            Dictionary with authentication statistics
        """
        return self._stats.copy()
    
    def reset_stats(self) -> None:
        """Reset authentication statistics."""
        self._stats = {
            "successful_authentications": 0,
            "failed_authentications": 0,
            "unauthorized_attempts": 0
        }
    
    def log_successful_auth(self, client_id: str) -> None:
        """
        Log a successful authentication.
        
        Args:
            client_id: Client identifier
        """
        self._stats["successful_authentications"] += 1
        print(f"Successful authentication for client: {client_id}", file=sys.stderr)
    
    def log_failed_auth(self, reason: str) -> None:
        """
        Log a failed authentication attempt.
        
        Args:
            reason: Reason for authentication failure
        """
        self._stats["failed_authentications"] += 1
        print(f"Authentication failed: {reason}", file=sys.stderr)
    
    def log_unauthorized_attempt(self, required_scopes: list, user_scopes: list) -> None:
        """
        Log an unauthorized access attempt.
        
        Args:
            required_scopes: Scopes required for access
            user_scopes: User's actual scopes
        """
        self._stats["unauthorized_attempts"] += 1
        print(f"Unauthorized attempt: required {required_scopes}, user has {user_scopes}", file=sys.stderr)


# Global auth middleware instance
_auth_middleware: Optional[AuthMiddleware] = None


def get_auth_middleware() -> Optional[AuthMiddleware]:
    """
    Get the global auth middleware instance.
    
    Returns:
        AuthMiddleware instance or None if not initialized
    """
    return _auth_middleware


def initialize_auth_middleware(auth_provider: JWTVerifier) -> AuthMiddleware:
    """
    Initialize the global auth middleware instance.
    
    Args:
        auth_provider: Configured JWTVerifier instance
        
    Returns:
        Initialized AuthMiddleware instance
    """
    global _auth_middleware
    _auth_middleware = AuthMiddleware(auth_provider)
    return _auth_middleware


def check_auth_health() -> dict:
    """
    Check authentication system health.
    
    Returns:
        Dictionary with health status
    """
    config_status = validate_auth_configuration()
    middleware = get_auth_middleware()
    
    health = {
        "status": "healthy" if config_status["configured"] else "unhealthy",
        "configuration": config_status,
        "middleware_initialized": middleware is not None,
        "statistics": middleware.get_stats() if middleware else None
    }
    
    return health
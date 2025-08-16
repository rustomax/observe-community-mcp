"""
Authentication and authorization package for Observe MCP server.

Provides JWT utilities, scope-based authorization, permission management,
and FastMCP authentication integration.
"""

# JWT utilities
from .jwt_utils import (
    decode_jwt_payload,
    decode_jwt_header,
    decode_jwt_full,
    extract_scopes_from_token,
    extract_claims_from_token,
    validate_token_format,
    get_token_expiry,
    is_token_expired
)

# Scope-based authorization
from .scopes import (
    requires_scopes,
    get_user_scopes,
    check_scope_access,
    require_admin_scope,
    require_write_access,
    require_read_access,
    ScopeValidator,
    SCOPE_HIERARCHY,
    get_effective_scopes,
    check_hierarchical_access
)

# Permission utilities
from .permissions import (
    get_user_permissions,
    get_auth_token_info,
    filter_sensitive_environment,
    get_admin_system_info,
    get_public_server_info,
    PermissionChecker,
    check_tool_access
)

# FastMCP integration
from .middleware import (
    setup_auth_provider,
    create_authenticated_mcp,
    validate_auth_configuration,
    AuthMiddleware,
    get_auth_middleware,
    initialize_auth_middleware,
    check_auth_health
)

__all__ = [
    # JWT utilities
    'decode_jwt_payload',
    'decode_jwt_header', 
    'decode_jwt_full',
    'extract_scopes_from_token',
    'extract_claims_from_token',
    'validate_token_format',
    'get_token_expiry',
    'is_token_expired',
    
    # Scope-based authorization
    'requires_scopes',
    'get_user_scopes',
    'check_scope_access',
    'require_admin_scope',
    'require_write_access',
    'require_read_access',
    'ScopeValidator',
    'SCOPE_HIERARCHY',
    'get_effective_scopes',
    'check_hierarchical_access',
    
    # Permission utilities
    'get_user_permissions',
    'get_auth_token_info',
    'filter_sensitive_environment',
    'get_admin_system_info',
    'get_public_server_info',
    'PermissionChecker',
    'check_tool_access',
    
    # FastMCP integration
    'setup_auth_provider',
    'create_authenticated_mcp',
    'validate_auth_configuration',
    'AuthMiddleware',
    'get_auth_middleware',
    'initialize_auth_middleware',
    'check_auth_health'
]
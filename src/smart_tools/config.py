"""
Configuration management for smart tools.

Handles LLM provider settings and validation.
"""

import os
import sys
from typing import Dict, Any, Optional


def get_smart_tools_config() -> Dict[str, Any]:
    """
    Get smart tools configuration from environment variables.
    
    Returns:
        Dictionary with configuration values
    """
    return {
        "provider": os.getenv("SMART_TOOLS_LLM_PROVIDER", "anthropic"),
        "api_key": os.getenv("SMART_TOOLS_API_KEY", ""),
        "model": os.getenv("SMART_TOOLS_MODEL", ""),
        "base_url": os.getenv("SMART_TOOLS_BASE_URL", ""),  # For local models
        "max_tokens": int(os.getenv("SMART_TOOLS_MAX_TOKENS", "4000")),
        "timeout": int(os.getenv("SMART_TOOLS_TIMEOUT", "30"))  # seconds
    }


def validate_smart_tools_config() -> Optional[str]:
    """
    Validate smart tools configuration.
    
    Returns:
        Error message if validation fails, None if successful
    """
    config = get_smart_tools_config()
    
    # Check if smart tools are enabled
    if not config.get("api_key"):
        return "Smart tools not configured: SMART_TOOLS_API_KEY environment variable is required"
    
    provider = config.get("provider", "").lower()
    if provider not in ["anthropic", "openai"]:
        return f"Invalid LLM provider: {provider}. Supported providers: anthropic, openai"
    
    # Provider-specific validation
    if provider == "anthropic":
        if not config.get("api_key").startswith("sk-ant-"):
            print("WARNING: Anthropic API key should start with 'sk-ant-'", file=sys.stderr)
    elif provider == "openai":
        if not config.get("api_key").startswith("sk-"):
            print("WARNING: OpenAI API key should start with 'sk-'", file=sys.stderr)
    
    return None


def is_smart_tools_enabled() -> bool:
    """
    Check if smart tools are properly configured and enabled.
    
    Returns:
        True if smart tools are enabled, False otherwise
    """
    return validate_smart_tools_config() is None


def get_default_model(provider: str) -> str:
    """
    Get the default model for a provider.
    
    Args:
        provider: LLM provider name
        
    Returns:
        Default model name
    """
    defaults = {
        "anthropic": "claude-3-5-sonnet-20241022",
        "openai": "gpt-4o"
    }
    return defaults.get(provider.lower(), "")


def print_smart_tools_status():
    """Print smart tools configuration status for debugging."""
    config = get_smart_tools_config()
    validation_error = validate_smart_tools_config()
    
    print("=== Smart Tools Configuration ===", file=sys.stderr)
    print(f"Provider: {config.get('provider')}", file=sys.stderr)
    print(f"Model: {config.get('model') or get_default_model(config.get('provider', ''))}", file=sys.stderr)
    print(f"API Key: {'Set' if config.get('api_key') else 'Not set'}", file=sys.stderr)
    print(f"Status: {'Enabled' if not validation_error else 'Disabled'}", file=sys.stderr)
    
    if validation_error:
        print(f"Error: {validation_error}", file=sys.stderr)
    
    print("================================", file=sys.stderr)
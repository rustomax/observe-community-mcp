"""
JWT utilities for token decoding, validation, and payload extraction.

Provides functions for handling JWT tokens in the Observe MCP server,
including debugging utilities and scope extraction.
"""

import json
import base64
import sys
from typing import Dict, Any, List, Optional, Tuple
from src.logging import get_logger

logger = get_logger('AUTH')


def decode_jwt_payload(token: str) -> Optional[Dict[str, Any]]:
    """
    Decode JWT payload without signature verification.
    
    Args:
        token: JWT token string
        
    Returns:
        Decoded payload dictionary or None if decoding fails
    """
    try:
        parts = token.split('.')
        if len(parts) != 3:
            return None
        
        # Decode payload with proper padding
        payload_part = parts[1]
        padded = payload_part + '=' * (4 - len(payload_part) % 4) if len(payload_part) % 4 else payload_part
        decoded = base64.urlsafe_b64decode(padded)
        return json.loads(decoded)
    except Exception as e:
        logger.error(f"JWT payload decode error: {e}")
        return None


def decode_jwt_header(token: str) -> Optional[Dict[str, Any]]:
    """
    Decode JWT header without signature verification.
    
    Args:
        token: JWT token string
        
    Returns:
        Decoded header dictionary or None if decoding fails
    """
    try:
        parts = token.split('.')
        if len(parts) != 3:
            return None
        
        # Decode header with proper padding
        header_part = parts[0]
        padded = header_part + '=' * (4 - len(header_part) % 4) if len(header_part) % 4 else header_part
        decoded = base64.urlsafe_b64decode(padded)
        return json.loads(decoded)
    except Exception as e:
        logger.error(f"JWT header decode error: {e}")
        return None


def decode_jwt_full(token: str, debug: bool = False) -> Dict[str, Any]:
    """
    Fully decode a JWT token and return its components.
    
    Args:
        token: JWT token string
        debug: Whether to print debug information to stderr
        
    Returns:
        Dictionary containing header, payload, and signature info
    """
    try:
        parts = token.split('.')
        if len(parts) != 3:
            return {"error": "Invalid JWT token format"}
        
        # Decode header
        header = decode_jwt_header(token)
        if header is None:
            return {"error": "Failed to decode JWT header"}
        
        # Decode payload
        payload = decode_jwt_payload(token)
        if payload is None:
            return {"error": "Failed to decode JWT payload"}
        
        # Print debug info if requested
        if debug:
            logger.debug(f"JWT header | data:{json.dumps(header, indent=2)}")
            logger.debug(f"JWT payload | data:{json.dumps(payload, indent=2)}")
            logger.debug("jwt token analysis complete")
        
        return {
            "header": header,
            "payload": payload,
            "signature_present": len(parts[2]) > 0
        }
    except Exception as e:
        logger.error(f"JWT decode error: {e}")
        return {"error": f"Exception decoding JWT token: {str(e)}"}


def extract_scopes_from_token(token: str) -> List[str]:
    """
    Extract scopes from a JWT token.
    
    Args:
        token: JWT token string
        
    Returns:
        List of scopes found in the token
    """
    payload = decode_jwt_payload(token)
    if payload and 'scopes' in payload:
        scopes = payload['scopes']
        if isinstance(scopes, list):
            return scopes
    return []


def extract_claims_from_token(token: str, claims: List[str]) -> Dict[str, Any]:
    """
    Extract specific claims from a JWT token.
    
    Args:
        token: JWT token string
        claims: List of claim names to extract
        
    Returns:
        Dictionary with extracted claims
    """
    payload = decode_jwt_payload(token)
    if not payload:
        return {}
    
    result = {}
    for claim in claims:
        if claim in payload:
            result[claim] = payload[claim]
    return result


def validate_token_format(token: str) -> Tuple[bool, Optional[str]]:
    """
    Validate basic JWT token format.
    
    Args:
        token: JWT token string
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    if not token:
        return False, "Token is empty"
    
    parts = token.split('.')
    if len(parts) != 3:
        return False, f"Invalid JWT format: expected 3 parts, got {len(parts)}"
    
    # Check if parts are not empty
    if not all(parts):
        return False, "JWT contains empty parts"
    
    # Try to decode header and payload
    header = decode_jwt_header(token)
    if header is None:
        return False, "Invalid JWT header"
    
    payload = decode_jwt_payload(token)
    if payload is None:
        return False, "Invalid JWT payload"
    
    return True, None


def get_token_expiry(token: str) -> Optional[int]:
    """
    Get token expiration timestamp from JWT.
    
    Args:
        token: JWT token string
        
    Returns:
        Expiration timestamp (Unix epoch) or None if not found
    """
    payload = decode_jwt_payload(token)
    if payload and 'exp' in payload:
        return payload['exp']
    return None


def is_token_expired(token: str) -> bool:
    """
    Check if a JWT token is expired.
    
    Args:
        token: JWT token string
        
    Returns:
        True if token is expired, False otherwise
    """
    import time
    
    exp = get_token_expiry(token)
    if exp is None:
        # If no expiry, assume not expired
        return False
    
    return time.time() > exp
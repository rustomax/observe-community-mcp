"""
Standardized logging setup for the Observe MCP server.
Uses Python's built-in logging with structured session correlation.
"""

import logging
import sys
import os
from typing import Optional, Dict, Any

# Get log level from environment variable, default to INFO
log_level = os.getenv('LOG_LEVEL', 'INFO').upper()
log_level_value = getattr(logging, log_level, logging.INFO)

# Configure root logger with basic format
logging.basicConfig(
    level=log_level_value,
    format='%(levelname)s %(name)s %(message)s',
    stream=sys.stderr
)

# Silence noisy third-party loggers
logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('httpcore').setLevel(logging.WARNING)
logging.getLogger('urllib3').setLevel(logging.WARNING)


class SessionContextFilter(logging.Filter):
    """Add session context to log records."""
    
    def __init__(self):
        super().__init__()
        self.session_id = None
        self.user_id = None
    
    def set_context(self, session_id: Optional[str] = None, user_id: Optional[str] = None):
        """Set session context for current request."""
        self.session_id = session_id
        self.user_id = user_id
    
    def filter(self, record):
        if self.session_id:
            record.session = f"session:{self.session_id[:8]}..."
        else:
            record.session = ""
        
        if self.user_id:
            record.user = f"user:{self.user_id}"
        else:
            record.user = ""
        
        return True


class SessionHandler(logging.StreamHandler):
    """Custom handler that only applies session formatting to our loggers."""
    
    def __init__(self):
        super().__init__(sys.stderr)


# Global session context filter
session_filter = SessionContextFilter()


def get_logger(name: str) -> logging.Logger:
    """Get a logger with session context."""
    logger = logging.getLogger(name)
    if session_filter not in logger.filters:
        logger.addFilter(session_filter)
        # Create a custom handler with session-aware formatting
        if not any(isinstance(h, SessionHandler) for h in logger.handlers):
            handler = SessionHandler()
            handler.setFormatter(logging.Formatter(
                '%(levelname)s %(name)s %(session)s %(user)s %(message)s'
            ))
            logger.addHandler(handler)
            logger.propagate = False  # Don't send to root logger
    return logger


def set_session_context(session_id: Optional[str] = None, user_id: Optional[str] = None):
    """Set session context for all loggers."""
    session_filter.set_context(session_id, user_id)


def log_extra(**kwargs) -> Dict[str, Any]:
    """Format extra logging context."""
    return {k: str(v)[:100] for k, v in kwargs.items() if v is not None}


# Component-specific loggers
session_logger = get_logger('SESSION')
auth_logger = get_logger('AUTH')
query_logger = get_logger('QUERY') 
semantic_logger = get_logger('SEMANTIC')
opal_logger = get_logger('OPAL')
pinecone_logger = get_logger('PINECONE')
dataset_logger = get_logger('DATASET')
http_logger = get_logger('HTTP')


def log_session_context(user_id: str, session_id: str, scopes: list, action: str = "auth"):
    """Helper to log session correlation info."""
    set_session_context(session_id, user_id)
    session_logger.info(f"{action} successful | scopes:{scopes}")


def log_tool_call(tool_name: str, session_id: str, user_id: str, **params):
    """Helper to log tool execution."""
    set_session_context(session_id, user_id)
    extra_str = " | ".join(f"{k}:{str(v)[:50]}" for k, v in params.items() if v is not None)
    query_logger.info(f"executing {tool_name} | {extra_str}" if extra_str else f"executing {tool_name}")
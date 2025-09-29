"""
Standardized logging setup for the Observe MCP server.
Uses Python's built-in logging with structured session correlation.
"""

import logging
import sys
import os
from typing import Optional, Dict, Any


class ColoredFormatter(logging.Formatter):
    """Colored logging formatter with timestamps."""
    
    # ANSI color codes
    COLORS = {
        'DEBUG': '\033[36m',    # Cyan
        'INFO': '\033[32m',     # Green
        'WARNING': '\033[33m',  # Yellow
        'ERROR': '\033[31m',    # Red
        'CRITICAL': '\033[35m', # Magenta
        'RESET': '\033[0m'      # Reset
    }
    
    def __init__(self, use_colors=True):
        # Format similar to dataset intelligence tool: timestamp - component - level - message
        super().__init__(
            fmt='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        self.use_colors = use_colors and sys.stderr.isatty()  # Only use colors if terminal supports it
    
    def format(self, record):
        if self.use_colors:
            # Apply color to level name
            level_color = self.COLORS.get(record.levelname, '')
            reset_color = self.COLORS['RESET']
            
            # Temporarily modify the record to add colors
            original_levelname = record.levelname
            record.levelname = f"{level_color}{record.levelname}{reset_color}"
            
            # Format the message
            formatted = super().format(record)
            
            # Restore original levelname
            record.levelname = original_levelname
            
            return formatted
        else:
            return super().format(record)


class SessionColoredFormatter(ColoredFormatter):
    """Colored formatter with session context for our custom loggers."""
    
    def __init__(self, use_colors=True):
        # Enhanced format with session context
        super().__init__(use_colors)
        # Override format to include session context after component name
        self.fmt = '%(asctime)s - %(name)s%(session_part)s%(user_part)s - %(levelname)s - %(message)s'
        self._fmt = logging.Formatter(self.fmt, datefmt='%Y-%m-%d %H:%M:%S')
    
    def format(self, record):
        # Add session and user parts to record
        session_part = f" {record.session}" if hasattr(record, 'session') and record.session else ""
        user_part = f" {record.user}" if hasattr(record, 'user') and record.user else ""
        
        record.session_part = session_part
        record.user_part = user_part
        
        if self.use_colors:
            # Apply color to level name
            level_color = self.COLORS.get(record.levelname, '')
            reset_color = self.COLORS['RESET']
            
            # Temporarily modify the record to add colors
            original_levelname = record.levelname
            record.levelname = f"{level_color}{record.levelname}{reset_color}"
            
            # Format the message
            formatted = self._fmt.format(record)
            
            # Restore original levelname
            record.levelname = original_levelname
            
            return formatted
        else:
            return self._fmt.format(record)


# Get log level from environment variable, default to INFO
log_level = os.getenv('LOG_LEVEL', 'INFO').upper()
log_level_value = getattr(logging, log_level, logging.INFO)

# Check if colors should be disabled
use_colors = os.getenv('LOG_COLORS', 'true').lower() in ('true', '1', 'yes', 'on')

# Don't modify the root logger - this affects third-party libraries
# Instead, we'll configure individual loggers as needed

# Set up a basic root logger that doesn't interfere with third-party loggers
# but ensures our application logs have proper formatting
if not logging.getLogger().handlers:
    # Only add a handler if none exists (don't override existing setup)
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter('%(levelname)s:%(name)s:%(message)s'))
    logging.getLogger().addHandler(handler)
    logging.getLogger().setLevel(logging.WARNING)  # Only show warnings and errors from third-party


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
    """Custom handler that applies session formatting and colors to our loggers."""
    
    def __init__(self, use_colors=True):
        super().__init__(sys.stderr)
        self.setFormatter(SessionColoredFormatter(use_colors=use_colors))


# Global session context filter
session_filter = SessionContextFilter()


def get_logger(name: str) -> logging.Logger:
    """Get a logger with session context and colored formatting."""
    logger = logging.getLogger(name)
    if session_filter not in logger.filters:
        logger.addFilter(session_filter)
        # Create a custom handler with session-aware colored formatting
        if not any(isinstance(h, SessionHandler) for h in logger.handlers):
            handler = SessionHandler(use_colors=use_colors)
            logger.addHandler(handler)
            logger.propagate = False  # Don't send to root logger
            logger.setLevel(log_level_value)  # Set the level for our application loggers
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
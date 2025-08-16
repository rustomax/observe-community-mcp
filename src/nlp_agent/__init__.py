"""
LangGraph-based NLP query agent for OPAL query generation.

This module provides a robust, conversation-aware agent that can:
- Convert natural language requests to OPAL queries
- Handle errors and retry with proper context
- Maintain conversation memory across tool calls
- Prevent hallucination through structured state management
"""

from .agent import create_opal_agent, execute_nlp_query

__all__ = ["create_opal_agent", "execute_nlp_query"]
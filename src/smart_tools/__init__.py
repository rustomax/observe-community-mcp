"""
Smart tools package for LLM-powered functionality.

Provides intelligent tools that use modern LLMs (Claude, GPT) to perform
complex reasoning and orchestration tasks.
"""

from .llm_client import LLMClient, create_llm_client, llm_completion
from .config import validate_smart_tools_config, get_smart_tools_config, is_smart_tools_enabled, print_smart_tools_status
from .prompts import OPAL_EXPERT_PROMPT

__all__ = [
    'LLMClient',
    'create_llm_client',
    'llm_completion',
    'validate_smart_tools_config', 
    'get_smart_tools_config',
    'is_smart_tools_enabled',
    'print_smart_tools_status',
    'OPAL_EXPERT_PROMPT'
]
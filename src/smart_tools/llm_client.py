"""
LLM client wrapper for smart tools.

Provides a simple abstraction over different LLM providers (Anthropic, OpenAI)
with function calling support for tool orchestration.
"""

import sys
import json
from typing import Dict, Any, List, Optional, Union
from abc import ABC, abstractmethod

# Load environment variables
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # dotenv is optional

from .config import get_smart_tools_config


class LLMClient(ABC):
    """Abstract base class for LLM clients."""
    
    @abstractmethod
    async def chat_completion(
        self,
        system_prompt: str,
        user_message: str,
        tools: Optional[List[Dict[str, Any]]] = None,
        max_iterations: int = 5
    ) -> str:
        """
        Generate a chat completion with optional tool usage.
        
        Args:
            system_prompt: System prompt to set LLM behavior
            user_message: User's message/request
            tools: Available tools for function calling
            max_iterations: Maximum number of tool iterations
            
        Returns:
            Final response from the LLM
        """
        pass


class AnthropicClient(LLMClient):
    """Anthropic Claude client implementation."""
    
    def __init__(self, api_key: str, model: str = "claude-3-5-sonnet-20241022"):
        self.api_key = api_key
        self.model = model
        
        # Import anthropic here to avoid import errors if not installed
        try:
            import anthropic
            self.client = anthropic.Anthropic(api_key=api_key)
        except ImportError:
            raise ImportError("anthropic package is required for Anthropic LLM support. Install with: pip install anthropic")
    
    async def chat_completion(
        self,
        system_prompt: str,
        user_message: str,
        tools: Optional[List[Dict[str, Any]]] = None,
        max_iterations: int = 5
    ) -> str:
        """Generate chat completion using Anthropic Claude."""
        try:
            messages = [{"role": "user", "content": user_message}]
            
            # If tools are provided, enable function calling
            if tools:
                # Convert tools to Anthropic format if needed
                anthropic_tools = self._convert_tools_format(tools)
                
                response = self.client.messages.create(
                    model=self.model,
                    max_tokens=4000,
                    system=system_prompt,
                    messages=messages,
                    tools=anthropic_tools
                )
            else:
                response = self.client.messages.create(
                    model=self.model,
                    max_tokens=4000,
                    system=system_prompt,
                    messages=messages
                )
            
            # Extract the response content
            if response.content and len(response.content) > 0:
                return response.content[0].text
            else:
                return "No response generated"
                
        except Exception as e:
            print(f"Error in Anthropic LLM call: {e}", file=sys.stderr)
            return f"Error calling LLM: {str(e)}"
    
    def _convert_tools_format(self, tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Convert generic tool format to Anthropic-specific format."""
        # For now, return tools as-is assuming they're already in correct format
        # This can be enhanced later to handle format conversion
        return tools


class OpenAIClient(LLMClient):
    """OpenAI GPT client implementation."""
    
    def __init__(self, api_key: str, model: str = "gpt-4o"):
        self.api_key = api_key
        self.model = model
        
        # Import openai here to avoid import errors if not installed
        try:
            import openai
            self.client = openai.OpenAI(api_key=api_key)
        except ImportError:
            raise ImportError("openai package is required for OpenAI LLM support. Install with: pip install openai")
    
    async def chat_completion(
        self,
        system_prompt: str,
        user_message: str,
        tools: Optional[List[Dict[str, Any]]] = None,
        max_iterations: int = 5
    ) -> str:
        """Generate chat completion using OpenAI GPT."""
        try:
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message}
            ]
            
            # If tools are provided, enable function calling
            if tools:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    tools=tools,
                    max_tokens=4000
                )
            else:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    max_tokens=4000
                )
            
            # Extract the response content
            if response.choices and len(response.choices) > 0:
                return response.choices[0].message.content
            else:
                return "No response generated"
                
        except Exception as e:
            print(f"Error in OpenAI LLM call: {e}", file=sys.stderr)
            return f"Error calling LLM: {str(e)}"


def create_llm_client() -> LLMClient:
    """
    Create an LLM client based on configuration.
    
    Returns:
        Configured LLM client instance
    """
    config = get_smart_tools_config()
    
    provider = config.get("provider", "").lower()
    api_key = config.get("api_key", "")
    model = config.get("model", "")
    
    if not api_key:
        raise ValueError("LLM API key is required for smart tools")
    
    if provider == "anthropic":
        return AnthropicClient(api_key, model or "claude-3-5-sonnet-20241022")
    elif provider == "openai":
        return OpenAIClient(api_key, model or "gpt-4o")
    else:
        raise ValueError(f"Unsupported LLM provider: {provider}. Supported: anthropic, openai")


# Simplified interface for basic usage
async def llm_completion(
    system_prompt: str,
    user_message: str,
    tools: Optional[List[Dict[str, Any]]] = None
) -> str:
    """
    Simple interface for LLM completion.
    
    Args:
        system_prompt: System prompt
        user_message: User message
        tools: Optional tools for function calling
        
    Returns:
        LLM response
    """
    client = create_llm_client()
    return await client.chat_completion(system_prompt, user_message, tools)
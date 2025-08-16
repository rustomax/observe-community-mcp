"""
Tool execution engine for LLM function calling.

Handles the execution of tools called by the LLM and feeding results back.
"""

import json
import sys
import re
from typing import Dict, Any, List, Optional, Callable


class ToolExecutor:
    """Executes tools called by LLMs and manages the conversation flow."""
    
    def __init__(self, tools: Dict[str, Callable]):
        """
        Initialize tool executor.
        
        Args:
            tools: Dictionary mapping tool names to callable functions
        """
        self.tools = tools
        
    def parse_tool_calls(self, response: str) -> List[Dict[str, Any]]:
        """
        Parse tool calls from LLM response.
        
        Args:
            response: LLM response containing tool calls
            
        Returns:
            List of parsed tool calls
        """
        tool_calls = []
        
        # Find all tool_use blocks
        pattern = r'<tool_use>\s*<tool_name>(.*?)</tool_name>\s*<tool_parameters>(.*?)</tool_parameters>\s*</tool_use>'
        matches = re.findall(pattern, response, re.DOTALL)
        
        for tool_name, params_xml in matches:
            tool_name = tool_name.strip()
            
            # Parse parameters from XML
            try:
                # Simple XML parsing for parameters
                params = {}
                param_pattern = r'<(\w+)>(.*?)</\1>'
                param_matches = re.findall(param_pattern, params_xml, re.DOTALL)
                
                for param_name, param_value in param_matches:
                    params[param_name] = param_value.strip()
                
                tool_calls.append({
                    'tool_name': tool_name,
                    'parameters': params
                })
                
            except Exception as e:
                print(f"[TOOL_EXECUTOR] Error parsing parameters for {tool_name}: {e}", file=sys.stderr)
                continue
                
        return tool_calls
    
    async def execute_tool_call(self, tool_call: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute a single tool call.
        
        Args:
            tool_call: Tool call with name and parameters
            
        Returns:
            Tool execution result
        """
        tool_name = tool_call['tool_name']
        parameters = tool_call['parameters']
        
        print(f"[TOOL_EXECUTOR] Executing tool: {tool_name} with params: {parameters}", file=sys.stderr)
        
        if tool_name not in self.tools:
            return {
                'success': False,
                'error': f"Unknown tool: {tool_name}",
                'result': None
            }
        
        try:
            # Execute the tool
            tool_func = self.tools[tool_name]
            result = await tool_func(**parameters)
            
            return {
                'success': True,
                'error': None,
                'result': result
            }
            
        except Exception as e:
            print(f"[TOOL_EXECUTOR] Error executing {tool_name}: {e}", file=sys.stderr)
            return {
                'success': False,
                'error': str(e),
                'result': None
            }
    
    def format_tool_result(self, tool_call: Dict[str, Any], execution_result: Dict[str, Any]) -> str:
        """
        Format tool execution result for feeding back to LLM.
        
        Args:
            tool_call: Original tool call
            execution_result: Result of tool execution
            
        Returns:
            Formatted tool result for LLM
        """
        tool_name = tool_call['tool_name']
        
        if execution_result['success']:
            result_content = execution_result['result']
            
            # If result is a string, use it directly
            if isinstance(result_content, str):
                content = result_content
            else:
                # Convert to JSON for structured data
                content = json.dumps(result_content, indent=2)
            
            return f"""<tool_result>
{content}
</tool_result>"""
        else:
            error_msg = execution_result['error']
            return f"""<tool_result>
Error executing {tool_name}: {error_msg}
</tool_result>"""
    
    async def process_response_with_tools(self, response: str) -> tuple[str, bool]:
        """
        Process LLM response and execute any tool calls.
        
        Args:
            response: LLM response potentially containing tool calls
            
        Returns:
            Tuple of (processed_response, has_tool_calls)
        """
        tool_calls = self.parse_tool_calls(response)
        
        if not tool_calls:
            return response, False
        
        print(f"[TOOL_EXECUTOR] Found {len(tool_calls)} tool calls", file=sys.stderr)
        
        # Execute all tool calls and build response
        processed_response = response
        
        for tool_call in tool_calls:
            execution_result = await self.execute_tool_call(tool_call)
            tool_result = self.format_tool_result(tool_call, execution_result)
            
            # Replace the tool_use block with tool_use + tool_result
            tool_use_pattern = f'<tool_use>\\s*<tool_name>{re.escape(tool_call["tool_name"])}</tool_name>.*?</tool_use>'
            replacement = f'<tool_use>\n<tool_name>{tool_call["tool_name"]}</tool_name>\n<tool_parameters>\n'
            
            for param_name, param_value in tool_call['parameters'].items():
                replacement += f'<{param_name}>{param_value}</{param_name}>\n'
            
            replacement += f'</tool_parameters>\n</tool_use>\n{tool_result}'
            
            processed_response = re.sub(tool_use_pattern, replacement, processed_response, flags=re.DOTALL)
        
        return processed_response, True
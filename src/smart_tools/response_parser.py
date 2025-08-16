"""
Response parser for smart tools.

Extracts final data results from LLM responses while preserving the full
reasoning chain for logging.
"""

import re
import json
import sys
from typing import Optional, Dict, Any


def extract_final_data(llm_response: str) -> str:
    """
    Extract the final data result from an LLM response.
    
    PRIORITY: Extract actual OPAL query results from function executions.
    Users need the raw data from successful queries, not explanatory text.
    
    Args:
        llm_response: Full LLM response with reasoning chain
        
    Returns:
        Extracted final data or the original response if no pattern matches
    """
    # Log the extraction attempt
    print(f"[SMART_TOOLS] Extracting final data from {len(llm_response)} character response", file=sys.stderr)
    
    # Pattern 1: HIGHEST PRIORITY - Extract actual OPAL query results from function_result tags
    # Look for the last successful execute_opal_query result
    function_result_pattern = r'<function_result[^>]*>\s*(.*?)\s*</function_result>'
    function_results = re.findall(function_result_pattern, llm_response, re.DOTALL)
    
    if function_results:
        # Get the last function result (most recent execution)
        last_result = function_results[-1].strip()
        
        # Check if this looks like actual query data (CSV, JSON, or substantial tabular data)
        if (len(last_result) > 50 and 
            (last_result.startswith('{') or  # JSON data
             last_result.startswith('[') or  # JSON array
             ',' in last_result or           # CSV data
             '|' in last_result or           # Table format
             '\n' in last_result)):          # Multi-line data
            
            print(f"[SMART_TOOLS] Extracted actual OPAL query results from function_result", file=sys.stderr)
            return last_result
    
    # Pattern 2: SECOND PRIORITY - Look for structured JSON response (new format)
    # Look for JSON blocks that contain both query_results and analysis
    structured_json_pattern = r'```json\s*(\{[\s\S]*?"query_results"[\s\S]*?"analysis"[\s\S]*?\})\s*```'
    json_matches = re.findall(structured_json_pattern, llm_response, re.DOTALL)
    if json_matches:
        try:
            json_data = json.loads(json_matches[-1])
            if "query_results" in json_data and "analysis" in json_data:
                print(f"[SMART_TOOLS] Extracted structured JSON response with data + analysis", file=sys.stderr)
                return json.dumps(json_data, indent=2)
        except json.JSONDecodeError as e:
            print(f"[SMART_TOOLS] JSON parsing error: {e}", file=sys.stderr)
    
    # Pattern 3: Look for JSON at the end of response (without code blocks)
    final_json_pattern = r'\{[\s\S]*?"query_results"[\s\S]*?"analysis"[\s\S]*?\}(?:\s*$)'
    json_matches = re.findall(final_json_pattern, llm_response, re.DOTALL)
    if json_matches:
        try:
            json_data = json.loads(json_matches[-1])
            if "query_results" in json_data and "analysis" in json_data:
                print(f"[SMART_TOOLS] Extracted final JSON response with data + analysis", file=sys.stderr)
                return json.dumps(json_data, indent=2)
        except json.JSONDecodeError as e:
            print(f"[SMART_TOOLS] Final JSON parsing error: {e}", file=sys.stderr)
    
    # Pattern 4: LOWER PRIORITY - Look for any CSV or tabular data in the response
    # Look for data that looks like CSV or structured results
    csv_pattern = r'([a-zA-Z_][a-zA-Z0-9_]*,[a-zA-Z0-9_,\s\n]+)'
    csv_matches = re.findall(csv_pattern, llm_response, re.DOTALL)
    if csv_matches:
        for match in csv_matches:
            if len(match) > 200 and match.count('\n') > 2:  # Multiple rows of data
                print(f"[SMART_TOOLS] Extracted CSV-like data from response", file=sys.stderr)
                return match.strip()
    
    # Pattern 5: LAST RESORT - Look for any JSON-like data structures
    json_pattern = r'(\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}|\[[^\[\]]*(?:\[[^\[\]]*\][^\[\]]*)*\])'
    json_matches = re.findall(json_pattern, llm_response, re.DOTALL)
    if json_matches:
        for match in json_matches:
            if len(match) > 100:
                try:
                    # Try to parse and validate the JSON
                    json_data = json.loads(match)
                    if isinstance(json_data, (dict, list)):
                        print(f"[SMART_TOOLS] Extracted JSON data structure from response", file=sys.stderr)
                        return json.dumps(json_data, indent=2)
                except json.JSONDecodeError:
                    continue
    
    # Last resort: Return the original response with a note
    print(f"[SMART_TOOLS] No specific pattern matched, returning original response", file=sys.stderr)
    return llm_response


def format_error_response(error_message: str, original_request: str) -> str:
    """
    Format an error response for the user.
    
    Args:
        error_message: Error message from the LLM or system
        original_request: User's original request
        
    Returns:
        Formatted error response
    """
    return f"""Sorry, I encountered an error while processing your request: "{original_request}"

Error: {error_message}

Please try rephrasing your request or check that the dataset ID is correct."""


def extract_key_insights(llm_response: str) -> Optional[str]:
    """
    Extract key insights or observations from the LLM response.
    
    Args:
        llm_response: Full LLM response
        
    Returns:
        Key insights string or None if not found
    """
    insight_patterns = [
        r'### Key Insights?:?\s*\n(.+?)(?=\n###|\n##|\n\n\*\*|$)',
        r'### Key Observations?:?\s*\n(.+?)(?=\n###|\n##|\n\n\*\*|$)',
        r'\*\*Key (.+?)\*\*\s*\n(.+?)(?=\n\n\*\*|\n\n##|$)',
    ]
    
    for pattern in insight_patterns:
        matches = re.findall(pattern, llm_response, re.DOTALL)
        if matches:
            if isinstance(matches[0], tuple):
                return matches[0][1].strip()
            else:
                return matches[0].strip()
    
    return None
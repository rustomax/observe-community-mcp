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
    
    This function looks for patterns that indicate the LLM has provided
    final results after completing its reasoning process.
    
    Args:
        llm_response: Full LLM response with reasoning chain
        
    Returns:
        Extracted final data or the original response if no pattern matches
    """
    # Log the extraction attempt
    print(f"[SMART_TOOLS] Extracting final data from {len(llm_response)} character response", file=sys.stderr)
    
    # Pattern 1: PRIORITY - Look for structured JSON response first (new format)
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
    
    # Pattern 2: Look for JSON at the end of response (without code blocks)
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
    
    # Pattern 3: Look for comprehensive content after the last completed function result (fallback)
    # This captures everything after the last </function_result> tag, excluding incomplete function calls
    last_function_result_pattern = r'</function_result>\s*\n+(.+?)(?:\n\n<function_calls>|$)'
    matches = re.findall(last_function_result_pattern, llm_response, re.DOTALL)
    if matches:
        final_text = matches[-1].strip()  # Get the content after the last function result
        if final_text and len(final_text) > 200:  # Ensure substantial content
            print(f"[SMART_TOOLS] Extracted final data using comprehensive function_result pattern", file=sys.stderr)
            return final_text
    
    # Pattern 4: Look for summary or analysis sections specifically (fallback)
    summary_patterns = [
        r'## Summary[:\s]*(.+?)(?=\n##|<function_calls>|$)',
        r'## (.+Summary.+)\n\n(.+?)(?=\n##|<function_calls>|$)',
        r'## (.+Analysis.+)\n\n(.+?)(?=\n##|<function_calls>|$)',
        r'## (.+Results?.+)\n\n(.+?)(?=\n##|<function_calls>|$)',
        r'### Key Insights(.+?)(?=\n##|<function_calls>|$)',
    ]
    
    for pattern in summary_patterns:
        matches = re.findall(pattern, llm_response, re.DOTALL)
        if matches:
            for match in matches:
                if isinstance(match, tuple):
                    # Pattern with title and content
                    title, content = match[0], match[1] if len(match) > 1 else ""
                    if len(content.strip()) > 100:
                        print(f"[SMART_TOOLS] Extracted final data from summary section: {title[:50]}...", file=sys.stderr)
                        return f"## {title}\n\n{content.strip()}"
                else:
                    # Pattern with just content
                    if len(match.strip()) > 200:
                        print(f"[SMART_TOOLS] Extracted final data from analysis section", file=sys.stderr)
                        return match.strip()
    
    # Pattern 5: Look for structured data tables and lists (fallback)
    structured_patterns = [
        r'(\|.+?\|[\s\S]*?\|.+?\|)',  # Markdown tables
        r'(### .+?\n\n[\s\S]*?(?=\n##|\n###|<function_calls>|$))',  # Subsections with content
        r'(\*\*[^*]+\*\*:[\s\S]*?(?=\n\n\*\*|\n##|<function_calls>|$))',  # Bold headers with content
    ]
    
    for pattern in structured_patterns:
        matches = re.findall(pattern, llm_response, re.DOTALL)
        if matches:
            # Combine all structured content found
            combined_content = "\n\n".join([match.strip() for match in matches if len(match.strip()) > 50])
            if len(combined_content) > 200:
                print(f"[SMART_TOOLS] Extracted final data from structured content", file=sys.stderr)
                return combined_content
    
    # Pattern 6: Legacy JSON pattern for backward compatibility
    legacy_json_pattern = r'\{[^}]*"(results?|data)"[^}]*\}|\[[^\]]*\{[^\}]*\}[^\]]*\]'
    json_matches = re.findall(legacy_json_pattern, llm_response, re.DOTALL)
    if json_matches:
        try:
            # Try to parse and format the JSON
            json_data = json.loads(json_matches[-1])
            if isinstance(json_data, (dict, list)) and len(str(json_data)) > 100:
                print(f"[SMART_TOOLS] Extracted legacy JSON data", file=sys.stderr)
                return f"Query Results:\n\n```json\n{json.dumps(json_data, indent=2)}\n```"
        except json.JSONDecodeError:
            pass
    
    # Fallback: Look for the largest substantial text block
    text_blocks = [block.strip() for block in re.split(r'\n\n+', llm_response) if len(block.strip()) > 100]
    if text_blocks:
        # Filter out function calls and results
        content_blocks = [
            block for block in text_blocks 
            if not any(marker in block for marker in ['<function_calls>', '<function_result>', '</function_calls>', '</function_result>'])
        ]
        if content_blocks:
            longest_block = max(content_blocks, key=len)
            print(f"[SMART_TOOLS] Extracted final data using longest content block", file=sys.stderr)
            return longest_block
    
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
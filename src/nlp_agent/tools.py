"""
Tool definitions for the OPAL query agent.
"""

from typing import Optional
from langchain_core.tools import tool
from src.observe import (
    get_dataset_info as observe_get_dataset_info,
    execute_opal_query as observe_execute_opal_query
)

# Import the MCP get_relevant_docs function
# We'll need to pass the context object when calling it
_get_relevant_docs_func = None
_mock_context = None

def set_mcp_context(get_relevant_docs_func, mock_context):
    """Set the MCP context and function for use in tools."""
    global _get_relevant_docs_func, _mock_context
    _get_relevant_docs_func = get_relevant_docs_func
    _mock_context = mock_context


@tool
async def get_dataset_info(dataset_id: str) -> str:
    """Get schema and field information for a dataset."""
    return await observe_get_dataset_info(dataset_id=dataset_id)


@tool  
async def execute_opal_query(
    query: str, 
    dataset_id: str, 
    time_range: Optional[str] = "1h",
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    row_count: Optional[int] = 1000,
    format: Optional[str] = "csv"
) -> str:
    """Execute an OPAL query on a dataset."""
    return await observe_execute_opal_query(
        query=query,
        dataset_id=dataset_id,
        time_range=time_range,
        start_time=start_time,
        end_time=end_time,
        row_count=row_count,
        format=format
    )


@tool
async def get_relevant_docs(query: str, n_results: int = 5) -> str:
    """Get relevant OPAL documentation for syntax help."""
    if _get_relevant_docs_func is None or _mock_context is None:
        return "Documentation search not available - MCP context not set"
    
    try:
        return await _get_relevant_docs_func(_mock_context, query, n_results)
    except Exception as e:
        return f"Error accessing documentation: {str(e)}"


# List of all tools for the agent
OPAL_TOOLS = [get_dataset_info, execute_opal_query, get_relevant_docs]
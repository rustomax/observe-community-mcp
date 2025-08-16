"""
Workflow nodes for the OPAL query agent.
"""

from typing import Any, Dict
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from .state import OPALAgentState


def should_get_schema(state: OPALAgentState) -> str:
    """Decide if we need to get schema information."""
    if state.get("has_schema_info", False):
        return "generate_query"
    return "get_schema"


def should_retry_query(state: OPALAgentState) -> str:
    """Decide if we should retry query generation or finish."""
    if state.get("has_successful_query", False):
        return "analyze_results"
    
    if state.get("query_attempts", 0) >= state.get("max_retries", 3):
        return "report_failure"
    
    return "generate_query"


async def understand_request_node(state: OPALAgentState) -> Dict[str, Any]:
    """Initial node to understand the user request."""
    
    system_prompt = f"""You are an expert OPAL query analyst. You will help convert a natural language request into a proper OPAL query.

Your task is to understand this request:
- Dataset ID: {state['dataset_id']}
- User Request: {state['user_request']}
- Time Range: {state.get('time_range', '1h')}

You have access to these tools:
1. get_dataset_info(dataset_id) - Get schema and field information
2. execute_opal_query(query, dataset_id, ...) - Execute OPAL queries
3. get_relevant_docs(query) - Get OPAL syntax documentation

CRITICAL: You MUST ONLY use data that comes from tool results. Never fabricate or hallucinate data.

Start by acknowledging the request and explaining your approach."""

    # Add system message if not already present
    messages = state.get("messages", [])
    if not messages or not isinstance(messages[0], SystemMessage):
        messages = [SystemMessage(content=system_prompt)] + messages
    
    # Add user request as human message
    messages.append(HumanMessage(content=f"Please help me with this data request: {state['user_request']}"))
    
    return {"messages": messages}


async def get_schema_node(state: OPALAgentState) -> Dict[str, Any]:
    """Get dataset schema information."""
    
    prompt = f"""Please call get_dataset_info to understand the schema and available fields for dataset {state['dataset_id']}. 

This is essential before generating any OPAL query so we know what fields are available."""
    
    messages = state["messages"] + [HumanMessage(content=prompt)]
    
    return {
        "messages": messages,
        "has_schema_info": True  # Will be set after tool execution
    }


async def generate_query_node(state: OPALAgentState) -> Dict[str, Any]:
    """Generate and execute OPAL query."""
    
    attempt = state.get("query_attempts", 0) + 1
    
    if attempt == 1:
        prompt = f"""Now that you have the schema information, please generate and execute an OPAL query for: "{state['user_request']}"

Use execute_opal_query with:
- The OPAL query based on the schema you retrieved
- dataset_id: {state['dataset_id']}
- time_range: {state.get('time_range', '1h')}

Remember to use only the field names that exist in the schema."""
    else:
        prompt = f"""Your previous OPAL query failed. Please analyze the error and generate a corrected query.

This is attempt {attempt} of {state.get('max_retries', 3)}.

If you need OPAL syntax help, use get_relevant_docs first, then generate a corrected query."""
    
    messages = state["messages"] + [HumanMessage(content=prompt)]
    
    return {
        "messages": messages,
        "query_attempts": attempt
    }


async def analyze_results_node(state: OPALAgentState) -> Dict[str, Any]:
    """Analyze successful query results."""
    
    prompt = f"""Excellent! Your OPAL query was successful. Please analyze the results and provide insights for the user's request: "{state['user_request']}"

CRITICAL: Only discuss the actual data shown in the tool results. Do not make up or fabricate any additional data.

Provide:
1. A summary of what was found
2. Key insights from the actual data
3. Any patterns or anomalies in the results
4. Answer to the user's original question based on the real data"""
    
    messages = state["messages"] + [HumanMessage(content=prompt)]
    
    return {
        "messages": messages,
        "has_successful_query": True
    }


async def report_failure_node(state: OPALAgentState) -> Dict[str, Any]:
    """Report failure after max retries."""
    
    prompt = f"""After {state.get('max_retries', 3)} attempts, I was unable to generate a successful OPAL query.

Please provide a helpful error analysis:
1. What OPAL syntax issues were encountered
2. What the dataset schema shows is available
3. Suggestions for the user on how to modify their request
4. Any documentation that might help

Be constructive and educational."""
    
    messages = state["messages"] + [HumanMessage(content=prompt)]
    
    return {
        "messages": messages
    }
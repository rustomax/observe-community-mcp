"""
State schema for the OPAL query agent.
"""

from typing import Annotated, List, Optional, Dict, Any
from typing_extensions import TypedDict
from langgraph.graph.message import add_messages
from langchain_core.messages import BaseMessage


class OPALAgentState(TypedDict):
    """State for the OPAL query generation agent."""
    
    # Core conversation state (managed by LangGraph)
    messages: Annotated[List[BaseMessage], add_messages]
    
    # Request parameters
    dataset_id: str
    user_request: str
    time_range: Optional[str]
    start_time: Optional[str] 
    end_time: Optional[str]
    
    # Workflow state
    query_attempts: int
    max_retries: int
    has_schema_info: bool
    has_successful_query: bool
    
    # Tool results (for reference)
    schema_info: Optional[str]
    last_query: Optional[str]
    last_query_result: Optional[str]
    
    # Final result
    final_result: Optional[str]
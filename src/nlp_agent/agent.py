"""
Main LangGraph agent for OPAL query generation.
"""

import os
import sys
from typing import Optional, Dict, Any
from langchain_core.messages import BaseMessage, SystemMessage, HumanMessage
from langchain_anthropic import ChatAnthropic
from langgraph.graph import StateGraph, END, START
from langgraph.prebuilt import ToolNode
from langgraph.checkpoint.memory import MemorySaver

from .state import OPALAgentState
from .tools import OPAL_TOOLS, set_mcp_context


def create_opal_agent():
    """Create and compile the OPAL query agent.
    
    NOTE: This is kept for compatibility but the simplified approach
    in execute_nlp_query is now preferred to avoid rate limiting.
    """
    
    # Initialize the language model
    model = ChatAnthropic(
        model=os.getenv("SMART_TOOLS_MODEL", "claude-3-5-sonnet-20241022"),
        temperature=0,
        api_key=os.getenv("SMART_TOOLS_API_KEY") or os.getenv("ANTHROPIC_API_KEY")
    )
    
    # Bind tools to the model
    model_with_tools = model.bind_tools(OPAL_TOOLS)
    
    # Create the state graph
    workflow = StateGraph(OPALAgentState)
    
    # Add the tool node for executing tools
    workflow.add_node("tools", ToolNode(OPAL_TOOLS))
    
    # Add a simplified chatbot node that uses the model with tools
    def chatbot_node(state: OPALAgentState):
        """Node that invokes the LLM with tools."""
        messages = state["messages"]
        response = model_with_tools.invoke(messages)
        return {"messages": [response]}
    
    workflow.add_node("chatbot", chatbot_node)
    
    # Simplified workflow: START -> chatbot -> (tools if needed) -> chatbot -> END
    workflow.add_edge(START, "chatbot")
    
    # Route from chatbot: either to tools or END
    def should_continue(state: OPALAgentState) -> str:
        """Decide whether to continue with tools or end."""
        messages = state["messages"]
        last_message = messages[-1]
        
        # If the last message has tool calls, execute them
        if hasattr(last_message, 'tool_calls') and last_message.tool_calls:
            return "tools"
        
        # Otherwise end the conversation
        return END
    
    workflow.add_conditional_edges(
        "chatbot",
        should_continue,
        {
            "tools": "tools",
            END: END,
        },
    )
    
    # After executing tools, go back to chatbot
    workflow.add_edge("tools", "chatbot")
    
    # Add memory for conversation persistence
    memory = MemorySaver()
    
    # Compile the graph
    app = workflow.compile(checkpointer=memory)
    
    return app


async def execute_nlp_query(
    dataset_id: str,
    request: str, 
    time_range: Optional[str] = "1h",
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    get_relevant_docs_func=None,
    mock_context=None
) -> str:
    """
    Execute a natural language query using a simplified, efficient approach.
    
    This implementation minimizes LLM API calls and focuses on tool execution.
    """
    
    # Set up MCP context for tools
    if get_relevant_docs_func and mock_context:
        set_mcp_context(get_relevant_docs_func, mock_context)
    
    print(f"[SIMPLIFIED] Processing: {request[:100]}...", file=sys.stderr)
    
    try:
        # Import the actual MCP functions directly
        from src.observe import get_dataset_info as observe_get_dataset_info
        from src.observe import execute_opal_query as observe_execute_opal_query
        
        print(f"[SIMPLIFIED] Step 1: Getting dataset schema", file=sys.stderr)
        schema_info = await observe_get_dataset_info(dataset_id=dataset_id)
        
        # Step 2: Get OPAL documentation for the request
        print(f"[SIMPLIFIED] Step 2: Getting OPAL documentation", file=sys.stderr)
        # Use simpler, more basic search terms to get fundamental OPAL syntax
        # Include options syntax to prevent incorrect usage
        docs_query = "OPAL basic syntax examples filter statsby timechart options"
        
        # Use the vector search functions directly
        try:
            from src.pinecone.search import search_docs
            import os
            from collections import defaultdict
            
            print(f"[SIMPLIFIED] Searching for docs: {docs_query}", file=sys.stderr)
            chunk_results = search_docs(docs_query, n_results=15)
            
            if chunk_results and len(chunk_results) > 0:
                # Group chunks by source document
                docs_by_source = defaultdict(list)
                for result in chunk_results:
                    source = result.get("source", "")
                    if source and source != "error":
                        docs_by_source[source].append(result)
                
                # Calculate average score for each document
                doc_scores = {}
                for source, chunks in docs_by_source.items():
                    avg_score = sum(chunk.get("score", 0.0) for chunk in chunks) / len(chunks)
                    doc_scores[source] = avg_score
                
                # Sort documents by average score and limit to top 3
                sorted_docs = sorted(doc_scores.items(), key=lambda x: x[1], reverse=True)[:3]
                
                print(f"[SIMPLIFIED] Found {len(sorted_docs)} relevant docs: {[os.path.basename(source) for source, _ in sorted_docs]}", file=sys.stderr)
                
                opal_docs = f"Found {len(sorted_docs)} relevant documents for OPAL syntax:\\n\\n"
                
                # Read and format each full document
                for i, (source, score) in enumerate(sorted_docs, 1):
                    try:
                        with open(source, 'r', encoding='utf-8') as f:
                            document_content = f.read()
                        
                        title = os.path.basename(source).replace(".md", "").replace("_", " ").title()
                        opal_docs += f"### Document {i}: {title}\\n"
                        opal_docs += f"{document_content[:1000]}{'...' if len(document_content) > 1000 else ''}\\n\\n"
                        print(f"[SIMPLIFIED] Added doc {i}: {title} ({len(document_content)} chars)", file=sys.stderr)
                    except Exception as e:
                        print(f"[SIMPLIFIED] Error reading doc {source}: {e}", file=sys.stderr)
                        continue
                
                print(f"[SIMPLIFIED] Total documentation length: {len(opal_docs)} chars", file=sys.stderr)
            else:
                opal_docs = "No relevant OPAL documentation found"
                
        except Exception as e:
            print(f"[SIMPLIFIED] Error searching docs: {e}", file=sys.stderr)
            opal_docs = "Error accessing documentation - using basic OPAL guidance:\\n\\nBasic OPAL syntax: filter, distinct, statsby, timechart, sort, limit"
        
        # Step 3: Create a single, focused LLM prompt
        model = ChatAnthropic(
            model=os.getenv("SMART_TOOLS_MODEL", "claude-3-5-sonnet-20241022"),
            temperature=0,
            api_key=os.getenv("SMART_TOOLS_API_KEY") or os.getenv("ANTHROPIC_API_KEY")
        )
        
        prompt = f"""You are an OPAL query expert. Generate ONE working OPAL query based on the information below.

USER REQUEST: {request}
DATASET: {dataset_id}
TIME RANGE: {time_range}

DATASET SCHEMA:
{schema_info}

OPAL DOCUMENTATION:
{opal_docs}

CRITICAL: The documentation above contains EXACT OPAL verb syntax. You MUST use the verbs shown in the documentation.

For distinct values, use: distinct(field_name) 
For aggregations, use: statsby aggregation_function(field), group_by(field)
For time series, use: timechart duration, aggregation_function(field)
For filtering, use: filter field_name = "value"

CRITICAL SYNTAX RULES:
- NEVER use "filter options()" - options go with timechart/statsby, not filter
- NEVER use "dataset()" function - the dataset is already specified
- DO NOT use made-up verbs like: make_set, find, pick, etc.
- ONLY use verbs that appear in the documentation above

TASK: Generate a single, working OPAL query using ONLY the verbs from the documentation.

OPAL Query:"""
        
        print(f"[SIMPLIFIED] Step 3: Generating OPAL query", file=sys.stderr)
        print(f"[SIMPLIFIED] Prompt length: {len(prompt)} chars", file=sys.stderr)
        print(f"[SIMPLIFIED] Prompt preview: {prompt[:500]}...", file=sys.stderr)
        
        response = model.invoke([HumanMessage(content=prompt)])
        opal_query = response.content.strip()
        
        # Clean up the query (remove markdown, extra text, SQL keywords)
        if "```" in opal_query:
            opal_query = opal_query.split("```")[1]
            if opal_query.startswith("opal"):
                opal_query = opal_query[4:]
        
        # Remove common SQL keywords that might leak in
        lines = opal_query.split('\n')
        cleaned_lines = []
        for line in lines:
            line = line.strip()
            # Skip SQL keywords and dataset references
            if line.lower() in ['sql', 'select', 'from'] or not line:
                continue
            # Remove dataset references if they appear at start
            if line == dataset_id:
                continue
            cleaned_lines.append(line)
        
        opal_query = '\n'.join(cleaned_lines).strip()
        # If it starts with |, remove the leading |
        if opal_query.startswith('|'):
            opal_query = opal_query[1:].strip()
        print(f"[SIMPLIFIED] Generated query: {opal_query}", file=sys.stderr)
        
        # Step 4: Execute the query
        print(f"[SIMPLIFIED] Step 4: Executing query", file=sys.stderr)
        query_result = await observe_execute_opal_query(
            query=opal_query,
            dataset_id=dataset_id, 
            time_range=time_range,
            start_time=start_time,
            end_time=end_time,
            row_count=50  # Limit for efficiency
        )
        
        # Step 5: If query failed, try to fix it  
        # Check for actual OPAL errors, not CSV data containing the word "error"
        is_error = (
            query_result.startswith("Error") or 
            "unknown verb" in query_result.lower() or
            "syntax error" in query_result.lower() or
            "400" in query_result or
            "500" in query_result or
            ("error" in query_result.lower() and not query_result.startswith('"'))
        )
        
        if is_error:
            print(f"[SIMPLIFIED] Query failed, trying to fix...", file=sys.stderr)
            
            # Get more specific documentation for error fix
            try:
                from src.pinecone.search import search_docs
                error_query = f"OPAL error fix: {query_result[:200]}"
                print(f"[SIMPLIFIED] Searching for error fix docs: {error_query}", file=sys.stderr)
                
                fix_chunk_results = search_docs(error_query, n_results=5)
                
                if fix_chunk_results and len(fix_chunk_results) > 0:
                    fix_docs = "Error fix documentation:\\n\\n"
                    for i, result in enumerate(fix_chunk_results[:3], 1):
                        text = result.get("text", "")
                        fix_docs += f"{i}. {text[:300]}{'...' if len(text) > 300 else ''}\\n\\n"
                else:
                    fix_docs = "No specific error fix documentation found"
            except Exception as e:
                print(f"[SIMPLIFIED] Error getting fix docs: {e}", file=sys.stderr)
                fix_docs = "Error fix documentation not available"
            
            fix_prompt = f"""The OPAL query failed. Generate a corrected version.

FAILED QUERY: {opal_query}
ERROR: {query_result}

FIX DOCUMENTATION:
{fix_docs}

Generate a corrected OPAL query (query only, no explanation):"""
            
            fix_response = model.invoke([HumanMessage(content=fix_prompt)])
            fixed_query = fix_response.content.strip()
            
            if "```" in fixed_query:
                fixed_query = fixed_query.split("```")[1]
                if fixed_query.startswith("opal"):
                    fixed_query = fixed_query[4:]
            fixed_query = fixed_query.strip()
            
            print(f"[SIMPLIFIED] Trying fixed query: {fixed_query}", file=sys.stderr)
            query_result = await observe_execute_opal_query(
                query=fixed_query,
                dataset_id=dataset_id,
                time_range=time_range, 
                start_time=start_time,
                end_time=end_time,
                row_count=50
            )
            opal_query = fixed_query
        
        # Step 6: Analyze results and return
        # Use same error detection logic as above
        final_is_error = (
            query_result.startswith("Error") or 
            "unknown verb" in query_result.lower() or
            "syntax error" in query_result.lower() or
            "400" in query_result or
            "500" in query_result or
            ("error" in query_result.lower() and not query_result.startswith('"'))
        )
        
        if final_is_error:
            return f"**Query Failed**\n\nOPAL Query: `{opal_query}`\n\nError: {query_result}\n\nSuggestion: Try using the direct OPAL tools (get_dataset_info, execute_opal_query) for more control."
        
        # Parse and format successful results
        lines = query_result.split('\n')
        if len(lines) > 1:
            header = lines[0] if lines[0] else "Results"
            data_lines = [line for line in lines[1:] if line.strip()]
            
            result = f"**Analysis for: {request}**\n\n"
            result += f"**Dataset:** {dataset_id}\n"
            result += f"**Time Range:** {time_range}\n"
            result += f"**OPAL Query:** `{opal_query}`\n\n"
            result += f"**Results:**\n```\n{query_result[:1000]}{'...' if len(query_result) > 1000 else ''}\n```\n\n"
            
            # Add basic analysis
            result += f"**Summary:** Found {len(data_lines)} records matching your request."
            
            return result
        else:
            return f"**No data found**\n\nQuery: `{opal_query}`\nResult: {query_result}"
            
    except Exception as e:
        print(f"[SIMPLIFIED] Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return f"Error in simplified NLP query: {str(e)}"
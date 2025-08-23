"""
Main LangGraph agent for OPAL query generation.
"""

from multiprocessing.resource_sharer import stop
import os
import sys
from typing import Optional, Dict, Any
from langchain_core.messages import BaseMessage, SystemMessage, HumanMessage
from langchain_anthropic import ChatAnthropic
from langchain_openai import ChatOpenAI
import anthropic
import openai
from langgraph.graph import StateGraph, END, START
from langgraph.prebuilt import ToolNode
from langgraph.checkpoint.memory import MemorySaver

from .state import OPALAgentState
from .tools import OPAL_TOOLS, set_mcp_context
import asyncio
import time
import re


def create_opal_agent():
    """Create and compile the OPAL query agent.
    
    NOTE: This is kept for compatibility but the simplified approach
    in execute_nlp_query is now preferred to avoid rate limiting.
    """
    
    # Initialize the language models with fallback
    primary_model, fallback_model = create_model_with_fallback()
    
    # For the agent, we'll use a wrapper that handles fallbacks
    def safe_invoke(messages):
        return invoke_with_fallback(primary_model, fallback_model, messages, "agent invocation")
    
    model = primary_model  # Keep the interface the same for now
    
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
        try:
            # Try primary model first
            response = model_with_tools.invoke(messages)
            return {"messages": [response]}
        except Exception as e:
            # Check for OpenAI-specific rate limit or overload errors  
            error_type = type(e).__name__
            if "RateLimitError" in error_type or (hasattr(e, 'status_code') and e.status_code in [429, 503, 529]):
                print(f"[AGENT_FALLBACK] OpenAI overloaded/rate-limited ({error_type}), using Anthropic fallback: {e}", file=sys.stderr)
            else:
                print(f"[AGENT_FALLBACK] OpenAI failed ({error_type}), using Anthropic fallback: {e}", file=sys.stderr)
            
            # Fallback to Anthropic with tools
            fallback_with_tools = fallback_model.bind_tools(OPAL_TOOLS)
            response = fallback_with_tools.invoke(messages)
            return {"messages": [response]}
        except Exception as e:
            print(f"[AGENT_FALLBACK] Primary model failed, using OpenAI fallback: {e}", file=sys.stderr)
            # Fallback to OpenAI with tools
            fallback_with_tools = fallback_model.bind_tools(OPAL_TOOLS)
            response = fallback_with_tools.invoke(messages)
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


def create_model_with_fallback():
    """
    Create an LLM instance with fallback from OpenAI to Anthropic.
    Returns tuple of (primary_model, fallback_model).
    """
    # Primary: OpenAI model (using GPT-5 - the most advanced model available!)
    primary_model = ChatOpenAI(
        model=os.getenv("SMART_TOOLS_MODEL", "gpt-5"),
        temperature=0,
        api_key=os.getenv("SMART_TOOLS_API_KEY") or os.getenv("OPENAI_API_KEY"),
        timeout=45  # GPT-5 should be faster than o1 models
    )
    
    # Fallback: Anthropic model
    fallback_model = ChatAnthropic(
        model="claude-sonnet-4-20250514",
        temperature=0,
        api_key=os.getenv("SMART_TOOLS_API_KEY") or os.getenv("ANTHROPIC_API_KEY"),
        timeout=30,
        stop=None
    )
    
    return primary_model, fallback_model


def invoke_with_fallback(primary_model, fallback_model, messages, context="query generation"):
    """
    Invoke LLM with automatic fallback from OpenAI to Anthropic on overload errors.
    Returns the response from whichever model succeeds.
    """
    print(f"[NLPQ_FALLBACK] Attempting {context} with OpenAI model...", file=sys.stderr)
    
    try:
        # Try OpenAI first
        response = primary_model.invoke(messages)
        print(f"[NLPQ_FALLBACK] OpenAI model succeeded for {context}", file=sys.stderr)
        return response
        
    except Exception as e:
        # Check for OpenAI-specific rate limit or overload errors
        error_type = type(e).__name__
        if "RateLimitError" in error_type or (hasattr(e, 'status_code') and e.status_code in [429, 503, 529]):
            print(f"[NLPQ_FALLBACK] OpenAI API overloaded/rate-limited ({error_type}): {e}, falling back to Anthropic...", file=sys.stderr)
        else:
            print(f"[NLPQ_FALLBACK] OpenAI model failed ({error_type}): {e}, falling back to Anthropic...", file=sys.stderr)
        
        try:
            response = fallback_model.invoke(messages)
            print(f"[NLPQ_FALLBACK] Anthropic fallback succeeded for {context}", file=sys.stderr)
            return response
            
        except Exception as fallback_error:
            print(f"[NLPQ_FALLBACK] Anthropic fallback failed: {fallback_error}", file=sys.stderr)
            raise Exception(f"Both models failed. OpenAI error: {e}, Anthropic error: {fallback_error}")


async def execute_nlp_query(
    request: str, 
    time_range: Optional[str] = "1h",
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    get_relevant_docs_func=None,
    mock_context=None
) -> str:
    """
    Execute a natural language query using a simplified, efficient approach.
    
    This implementation automatically discovers relevant datasets using semantic search
    and minimizes LLM API calls while focusing on tool execution.
    """
    
    # Set up MCP context for tools
    if get_relevant_docs_func and mock_context:
        set_mcp_context(get_relevant_docs_func, mock_context)
    
    print(f"[NLPQ_INFO] Processing: {request[:100]}...", file=sys.stderr)
    
    try:
        # Import the actual MCP functions directly
        from src.observe import get_dataset_info as observe_get_dataset_info
        from src.observe import execute_opal_query as observe_execute_opal_query
        from src.observe import list_datasets as observe_list_datasets
        
        # Step 1: Discover relevant datasets using semantic search
        print(f"[NLPQ_DISCOVERY] Finding relevant datasets for query", file=sys.stderr)
        
        # Try DIRECT dataset selection first (field-based approach)
        try:
            from src.dataset_intelligence.direct_selection import find_datasets_direct
            
            print(f"[NLPQ_DISCOVERY] Trying direct field-based dataset selection...", file=sys.stderr)
            relevant_datasets = await find_datasets_direct(request, limit=3)
            
            if relevant_datasets:
                # Use the best matching dataset
                best_dataset = relevant_datasets[0]
                dataset_id = best_dataset["dataset_id"]
                score = best_dataset.get("selection_score", 0)
                print(f"[NLPQ_DISCOVERY] Selected dataset via direct selection: {best_dataset['name']} (ID: {dataset_id}, Score: {score})", file=sys.stderr)
            else:
                print(f"[NLPQ_DISCOVERY] Direct selection found no datasets, trying semantic fallback...", file=sys.stderr)
                
                # Fallback to semantic search
                from src.dataset_intelligence.search import find_relevant_datasets, find_datasets_by_keywords
                
                relevant_datasets = await find_relevant_datasets(request, limit=3, similarity_threshold=0.5)
                
                if not relevant_datasets:
                    print(f"[NLPQ_DISCOVERY] Semantic search found no results, trying keyword search...", file=sys.stderr)
                    relevant_datasets = await find_datasets_by_keywords(request, limit=3)
                
                if relevant_datasets:
                    best_dataset = relevant_datasets[0]
                    dataset_id = best_dataset["dataset_id"]
                    print(f"[NLPQ_DISCOVERY] Selected dataset via semantic fallback: {best_dataset['name']} (ID: {dataset_id})", file=sys.stderr)
                else:
                    # Final fallback: use a known good dataset
                    dataset_id = "42160987"  # ServiceExplorer/Service Edge
                    print(f"[NLPQ_DISCOVERY] No datasets found via any method, using hardcoded fallback: {dataset_id}", file=sys.stderr)
                
        except Exception as e:
            print(f"[NLPQ_DISCOVERY] Error in dataset discovery: {e}", file=sys.stderr)
            dataset_id = "42160987"  # ServiceExplorer/Service Edge
            print(f"[NLPQ_DISCOVERY] Using fallback dataset due to error: {dataset_id}", file=sys.stderr)
        
        # Check memory system for existing successful patterns with discovered dataset
        print(f"[NLPQ_MEMORY] Checking memory for existing patterns", file=sys.stderr)
        try:
            from src.opal_memory.queries import find_matching_queries, store_successful_query
            
            matching_queries = await find_matching_queries(dataset_id, request, time_range, max_matches=1)
            
            if matching_queries:
                best_match = matching_queries[0]
                print(f"[NLPQ_MEMORY] Found {best_match.match_type} match with {best_match.similarity_score:.2f} similarity, confidence: {best_match.confidence:.2f}", file=sys.stderr)
                
                # Execute the cached OPAL query
                cached_query = best_match.query.opal_query
                print(f"[NLPQ_MEMORY] Executing cached query: {cached_query[:100]}...", file=sys.stderr)
                
                try:
                    cached_result = await observe_execute_opal_query(
                        query=cached_query,
                        dataset_id=dataset_id, 
                        time_range=time_range,
                        start_time=start_time,
                        end_time=end_time,
                        row_count=50
                    )
                    
                    # Check if cached query was successful
                    error_type, is_error = classify_error(cached_result)
                    if not is_error:
                        # Success! Return the cached result
                        print(f"[NLPQ_MEMORY] Cached query executed successfully", file=sys.stderr)
                        
                        # Parse and format the results
                        lines = cached_result.split('\n')
                        if len(lines) > 1:
                            data_lines = [line for line in lines[1:] if line.strip()]
                            
                            result = f"**Analysis for: {request}** (from memory)\n\n"
                            result += f"**Dataset:** {dataset_id}\n"
                            result += f"**Time Range:** {time_range}\n"
                            result += f"**OPAL Query:** `{cached_query}` (cached {best_match.match_type} match)\n\n"
                            result += f"**Results:**\n```\n{cached_result[:1000]}{'...' if len(cached_result) > 1000 else ''}\n```\n\n"
                            result += f"**Summary:** Found {len(data_lines)} records from cached pattern (similarity: {best_match.similarity_score:.1%})."
                            
                            return result
                        else:
                            result = f"**Cached query executed** (from memory)\n\nQuery: `{cached_query}`\nResult: {cached_result}\nSimilarity: {best_match.similarity_score:.1%}"
                            return result
                            
                    else:
                        print(f"[NLPQ_MEMORY] Cached query failed ({error_type}), falling back to LLM generation", file=sys.stderr)
                        
                except Exception as cached_error:
                    print(f"[NLPQ_MEMORY] Error executing cached query: {cached_error}, falling back to LLM generation", file=sys.stderr)
            else:
                print(f"[NLPQ_MEMORY] No matching patterns found in memory", file=sys.stderr)
                
        except ImportError:
            print(f"[NLPQ_MEMORY] Memory system not available (missing dependencies)", file=sys.stderr)
        except Exception as memory_error:
            print(f"[NLPQ_MEMORY] Memory system error: {memory_error}, continuing with LLM generation", file=sys.stderr)
        
        # Continue with normal LLM-based query generation if no cached result
        print(f"[NLPQ_INFO] Step 1: Getting dataset schema", file=sys.stderr)
        schema_info = await observe_get_dataset_info(dataset_id=dataset_id)
        
        # Step 2: Get OPAL documentation for the request
        print(f"[NLPQ_INFO] Step 2: Getting OPAL documentation", file=sys.stderr)
        # Use simpler, more basic search terms to get fundamental OPAL syntax
        # Include options syntax to prevent incorrect usage
        docs_query = "OPAL basic syntax examples filter statsby timechart options"
        
        # Use the vector search functions directly
        try:
            from src.pinecone.search import search_docs
            import os
            from collections import defaultdict
            
            print(f"[NLPQ_INFO] Searching for docs: {docs_query}", file=sys.stderr)
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
                
                print(f"[NLPQ_INFO] Found {len(sorted_docs)} relevant docs: {[os.path.basename(source) for source, _ in sorted_docs]}", file=sys.stderr)
                
                opal_docs = f"Found {len(sorted_docs)} relevant documents for OPAL syntax:\\n\\n"
                
                # Read and format each full document
                for i, (source, score) in enumerate(sorted_docs, 1):
                    try:
                        with open(source, 'r', encoding='utf-8') as f:
                            document_content = f.read()
                        
                        title = os.path.basename(source).replace(".md", "").replace("_", " ").title()
                        opal_docs += f"### Document {i}: {title}\\n"
                        opal_docs += f"{document_content[:1000]}{'...' if len(document_content) > 1000 else ''}\\n\\n"
                        print(f"[NLPQ_INFO] Added doc {i}: {title} ({len(document_content)} chars)", file=sys.stderr)
                    except Exception as e:
                        print(f"[NLPQ_INFO] Error reading doc {source}: {e}", file=sys.stderr)
                        continue
                
                print(f"[NLPQ_INFO] Total documentation length: {len(opal_docs)} chars", file=sys.stderr)
            else:
                opal_docs = "No relevant OPAL documentation found"
                
        except Exception as e:
            print(f"[NLPQ_INFO] Error searching docs: {e}", file=sys.stderr)
            opal_docs = "Error accessing documentation - using basic OPAL guidance:\\n\\nBasic OPAL syntax: filter, distinct, statsby, timechart, sort, limit"
        
        # Step 3: Create models with fallback capability
        import os  # Ensure os is available locally
        primary_model, fallback_model = create_model_with_fallback()
        
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

CRITICAL OPAL SYNTAX RULES:
1. VERBS - Use ONLY these valid verbs:
   - filter, statsby, timechart, distinct, sort, limit, make_col, fields
   - NEVER: pick (use fields), by (use group_by()), show, select, get

2. TIME FILTERING: NEVER use filter timestamp >, filter time >, filter start_time >, etc.
   - Time range ({time_range}) is handled automatically by the API
   - FORBIDDEN: "filter start_time >", "frame back:", "@now", "timestamp >", "_c_timestamp", "now"

3. FIELD SELECTION: Use fields, not pick
   - Correct: | fields timestamp, body, container
   - WRONG: | pick timestamp, body, container

4. AGGREGATIONS: Proper statsby syntax with commas
   - Correct: statsby count:count(), avg_duration:avg(duration), group_by(service_name)
   - WRONG: statsby count() group_by(service_name) # missing comma

5. CONDITIONAL LOGIC: ALWAYS use if() with exactly 3 arguments
   - Correct: if(condition, true_value, false_value)
   - Correct: sum(if(error, 1, 0))
   - WRONG: case() functions, if() with 4+ arguments

6. PERCENTILES: Use decimal values 0.0-1.0, not 1-100
   - Correct: percentile(duration, 0.95), percentile(duration, 0.99)
   - WRONG: percentile(duration, 95), percentile(duration, 99)

7. REGULAR EXPRESSIONS: Use proper regex syntax
   - Correct: filter body ~ "error"
   - Correct: filter body ~ /error|Error/
   - WRONG: filter body ~ /(?i)(error|exception)/ # complex regex can fail

8. FIELD REFERENCES: Only use fields from the schema above
   - Check the DATASET SCHEMA section for available field names
   - Do NOT assume fields like _c_timestamp, @.now exist

COMMON SUCCESSFUL PATTERNS:
- Simple filtering: filter field_name = "value" | limit 10
- Count by groups: statsby count:count(), group_by(field_name)
- Error analysis: statsby error_rate:avg(if(error, 1.0, 0.0)), group_by(service_name)
- Field selection: filter condition | fields field1, field2, field3
- Top N: statsby count:count(), group_by(field) | sort desc(count) | limit 10

TASK: Generate a single, working OPAL query using ONLY the verbs and fields from above.
Focus on data analysis, aggregation, and filtering by field values - NOT time filtering.
Verify all field names exist in the DATASET SCHEMA.

OPAL Query:"""
        
        print(f"[NLPQ_INFO] Step 3: Generating OPAL query", file=sys.stderr)
        print(f"[NLPQ_INFO] Prompt length: {len(prompt)} chars", file=sys.stderr)
        print(f"[NLPQ_INFO] Prompt preview: {prompt[:500]}...", file=sys.stderr)
        
        response = invoke_with_fallback(primary_model, fallback_model, [HumanMessage(content=prompt)], "OPAL query generation")
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
        print(f"[NLPQ_INFO] Generated query: {opal_query}", file=sys.stderr)
        
        # Step 3.5: Pre-validation to catch obvious issues
        validation_issues = validate_query_syntax(opal_query, schema_info)
        if validation_issues:
            print(f"[NLPQ_RELIABILITY] Pre-validation found issues: {validation_issues}", file=sys.stderr)
            # Try to fix obvious issues before execution
            opal_query = fix_obvious_issues(opal_query, validation_issues)
            print(f"[NLPQ_RELIABILITY] Pre-validation corrected query: {opal_query}", file=sys.stderr)
        
        # Step 4: Execute the query
        print(f"[NLPQ_INFO] Step 4: Executing query", file=sys.stderr)
        query_result = await observe_execute_opal_query(
            query=opal_query,
            dataset_id=dataset_id, 
            time_range=time_range,
            start_time=start_time,
            end_time=end_time,
            row_count=50  # Limit for efficiency
        )
        
        # Step 5: Multi-tier error recovery with progressive strategies
        retry_count = 0
        max_retries = 3
        recovery_strategies = []
        
        while retry_count < max_retries:
            # Enhanced error classification
            error_type, is_error = classify_error(query_result)
            
            if not is_error:
                break  # Success, exit retry loop
                
            retry_count += 1
            print(f"[NLPQ_RELIABILITY] Attempt {retry_count}/{max_retries}: {error_type} detected", file=sys.stderr)
            
            try:
                # First attempt: Surgical fix (targeted error-specific fix)
                if retry_count == 1:
                    print(f"[NLPQ_RELIABILITY] Trying surgical fix for {error_type}", file=sys.stderr)
                    fixed_query = apply_surgical_fix(opal_query, query_result, error_type, schema_info)
                    recovery_strategies.append(f"Attempt {retry_count}: Surgical fix for {error_type}")
                    strategy_name = "Surgical fix"
                else:
                    # Fallback: Use traditional recovery strategy
                    recovery_strategy = select_recovery_strategy(error_type, retry_count-1, schema_info, request)
                    recovery_strategies.append(f"Attempt {retry_count}: {recovery_strategy['name']}")
                    fixed_query = await apply_recovery_strategy(
                        recovery_strategy, opal_query, query_result, error_type, 
                        primary_model, fallback_model, schema_info, request, dataset_id, recovery_strategies
                    )
                    strategy_name = recovery_strategy['name']
                
                if fixed_query and fixed_query != opal_query:
                    print(f"[NLPQ_RELIABILITY] Trying strategy '{strategy_name}': {fixed_query[:100]}...", file=sys.stderr)
                    
                    # Execute with retry logic for transient failures
                    query_result = await execute_with_retry(
                        fixed_query, dataset_id, time_range, start_time, end_time
                    )
                    opal_query = fixed_query
                else:
                    print(f"[NLPQ_RELIABILITY] Strategy '{strategy_name}' did not generate a different query", file=sys.stderr)
                    # Don't break early - try other strategies
                    if retry_count == max_retries:
                        print(f"[NLPQ_RELIABILITY] All strategies exhausted, giving up", file=sys.stderr)
                        break
                    
            except Exception as e:
                strategy_name = "Surgical fix" if retry_count == 1 else "Recovery strategy"
                print(f"[NLPQ_RELIABILITY] Strategy '{strategy_name}' failed: {e}", file=sys.stderr)
                if retry_count == max_retries:
                    query_result = f"Error: All recovery strategies failed. Last error: {str(e)}"
                continue
        
        # Step 6: Analyze results and return with recovery information
        final_error_type, final_is_error = classify_error(query_result)
        
        if final_is_error:
            recovery_summary = "\\n".join(recovery_strategies) if recovery_strategies else "No recovery strategies attempted"
            return f"""**Query Failed After {retry_count} Recovery Attempts**

**Final OPAL Query:** `{opal_query}`

**Final Error:** {query_result}

**Recovery Strategies Tried:**
{recovery_summary}

**Diagnosis:** {final_error_type}

**Suggestions:**
1. Try using direct OPAL tools (get_dataset_info, execute_opal_query) for more control
2. Simplify your request and try again
3. Check if the dataset contains the fields you're looking for
4. Verify the time range has data available

**Working Alternative:** You can try a basic query like:
- `limit 10` (to see recent data)
- `statsby count:count()` (to count all records)
- `limit 5` (to see available data)"""
        
        # Parse and format successful results
        lines = query_result.split('\n')
        if len(lines) > 1:
            header = lines[0] if lines[0] else "Results"
            data_lines = [line for line in lines[1:] if line.strip()]
            
            # NEW: Store successful query pattern in memory system
            print(f"[NLPQ_MEMORY] Storing successful query pattern", file=sys.stderr)
            try:
                success_stored = await store_successful_query(
                    dataset_id=dataset_id,
                    nlp_query=request,
                    opal_query=opal_query,
                    row_count=len(data_lines),
                    time_range=time_range
                )
                if success_stored:
                    print(f"[NLPQ_MEMORY] Successfully stored query pattern for future use", file=sys.stderr)
                else:
                    print(f"[NLPQ_MEMORY] Failed to store query pattern (memory system may be disabled)", file=sys.stderr)
            except Exception as store_error:
                print(f"[NLPQ_MEMORY] Error storing successful query: {store_error}", file=sys.stderr)
            
            result = f"**Analysis for: {request}**\n\n"
            result += f"**Dataset:** {dataset_id}\n"
            result += f"**Time Range:** {time_range}\n"
            result += f"**OPAL Query:** `{opal_query}`\n\n"
            result += f"**Results:**\n```\n{query_result[:1000]}{'...' if len(query_result) > 1000 else ''}\n```\n\n"
            
            # Add basic analysis
            result += f"**Summary:** Found {len(data_lines)} records matching your request."
            
            return result
        else:
            # Also store successful queries that return no data (they're still valid)
            print(f"[NLPQ_MEMORY] Storing successful query pattern (no data returned)", file=sys.stderr)
            try:
                success_stored = await store_successful_query(
                    dataset_id=dataset_id,
                    nlp_query=request,
                    opal_query=opal_query,
                    row_count=0,
                    time_range=time_range
                )
                if success_stored:
                    print(f"[NLPQ_MEMORY] Successfully stored query pattern for future use", file=sys.stderr)
            except Exception as store_error:
                print(f"[NLPQ_MEMORY] Error storing successful query: {store_error}", file=sys.stderr)
                
            return f"**No data found**\n\nQuery: `{opal_query}`\nResult: {query_result}"
            
    except Exception as e:
        print(f"[NLPQ_INFO] Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return f"Error in simplified NLP query: {str(e)}"


def classify_error(query_result: str) -> tuple[str, bool]:
    """
    Enhanced error classification for targeted recovery strategies.
    Returns (error_type, is_error) tuple.
    """
    if not query_result:
        return ("empty_result", True)
    
    query_lower = query_result.lower()
    
    # Not an error - successful CSV data
    if query_result.startswith('"') and ',' in query_result:
        return ("success", False)
    
    # HTTP errors
    if "400" in query_result or "bad request" in query_lower:
        return ("http_400", True)
    if "500" in query_result or "internal server error" in query_lower:
        return ("http_500", True)
    if "timeout" in query_lower or "timed out" in query_lower:
        return ("timeout", True)
    
    # Specific OPAL syntax errors (more targeted)
    if "unknown verb" in query_lower or "unknown function" in query_lower:
        return ("unknown_verb", True)
    if "expected line continuation" in query_lower:
        return ("line_continuation_error", True)
    if "options argument" in query_lower and "not recognized" in query_lower:
        return ("invalid_options", True)
    if "does not exist among fields" in query_lower:
        return ("field_not_found", True)
    if "argument" in query_lower and "must be of type" in query_lower:
        return ("type_mismatch", True)
    if "expected" in query_lower and ("," in query_lower or "(" in query_lower):
        return ("syntax_expected", True)
    
    # Generic categories for fallback
    if "syntax error" in query_lower or "parse error" in query_lower:
        return ("syntax_error", True)
    if "unknown field" in query_lower or "field not found" in query_lower:
        return ("unknown_field", True)
    if "type mismatch" in query_lower or "invalid type" in query_lower:
        return ("type_error", True)
    
    # Dataset/permission errors
    if "dataset not found" in query_lower or "access denied" in query_lower:
        return ("access_error", True)
    
    # Generic error patterns
    if query_result.startswith("Error") or "error" in query_lower:
        return ("generic_error", True)
    
    return ("success", False)


def select_recovery_strategy(error_type: str, retry_count: int, schema_info: str, request: str) -> dict:
    """
    Select the best recovery strategy based on error type and retry attempt.
    Returns strategy configuration dict.
    """
    # Strategy progression: specific -> general -> fallback
    strategies = {
        "unknown_verb": [
            {"name": "verb_replacement", "approach": "specific_docs", "search_terms": "OPAL verbs group_by statsby timechart filter in function"},
            {"name": "basic_syntax", "approach": "fundamental_rebuild", "search_terms": "OPAL basic syntax examples filter function"},
            {"name": "simple_fallback", "approach": "minimal_query", "search_terms": "OPAL simple queries filter"}
        ],
        "line_continuation_error": [
            {"name": "format_correction", "approach": "specific_docs", "search_terms": "OPAL multiline query format"},
            {"name": "syntax_rebuild", "approach": "fundamental_rebuild", "search_terms": "OPAL query structure"},
            {"name": "simple_fallback", "approach": "minimal_query", "search_terms": "OPAL single line"}
        ],
        "invalid_options": [
            {"name": "options_fix", "approach": "specific_docs", "search_terms": "OPAL timechart options bins empty_bins"},
            {"name": "timechart_rebuild", "approach": "fundamental_rebuild", "search_terms": "OPAL timechart examples"},
            {"name": "basic_aggregation", "approach": "minimal_query", "search_terms": "OPAL statsby"}
        ],
        "field_not_found": [
            {"name": "field_mapping", "approach": "schema_focused", "search_terms": "OPAL field names get_field JSON access"},
            {"name": "schema_rebuild", "approach": "fundamental_rebuild", "search_terms": "OPAL basic queries field access"},
            {"name": "simple_count", "approach": "minimal_query", "search_terms": "OPAL simple filter"}
        ],
        "type_mismatch": [
            {"name": "type_correction", "approach": "specific_docs", "search_terms": "OPAL data types function arguments get_field JSON"},
            {"name": "aggregation_fix", "approach": "fundamental_rebuild", "search_terms": "OPAL aggregation functions type conversion"},
            {"name": "basic_filter", "approach": "minimal_query", "search_terms": "OPAL filter boolean"}
        ],
        "syntax_error": [
            {"name": "syntax_correction", "approach": "specific_docs", "search_terms": "OPAL syntax comma parentheses"},
            {"name": "structure_rebuild", "approach": "fundamental_rebuild", "search_terms": "OPAL query structure"},
            {"name": "basic_filter", "approach": "minimal_query", "search_terms": "OPAL filter examples"}
        ],
        "syntax_expected": [
            {"name": "punctuation_fix", "approach": "specific_docs", "search_terms": "OPAL syntax comma expected parentheses"},
            {"name": "structure_rebuild", "approach": "fundamental_rebuild", "search_terms": "OPAL query structure"},
            {"name": "simple_filter", "approach": "minimal_query", "search_terms": "OPAL basic filter"}
        ],
        "missing_column": [
            {"name": "schema_aware_rebuild", "approach": "schema_focused", "search_terms": "OPAL column selection timechart"},
            {"name": "field_inspection", "approach": "fundamental_rebuild", "search_terms": "OPAL field selection"},
            {"name": "basic_count", "approach": "minimal_query", "search_terms": "OPAL count queries"}
        ],
        "unknown_field": [
            {"name": "field_mapping", "approach": "schema_focused", "search_terms": "OPAL field names"},
            {"name": "schema_rebuild", "approach": "fundamental_rebuild", "search_terms": "OPAL basic queries"},
            {"name": "simple_count", "approach": "minimal_query", "search_terms": "OPAL simple"}
        ],
        "type_error": [
            {"name": "type_correction", "approach": "specific_docs", "search_terms": "OPAL data types aggregation"},
            {"name": "aggregation_fix", "approach": "fundamental_rebuild", "search_terms": "OPAL aggregation functions"},
            {"name": "basic_filter", "approach": "minimal_query", "search_terms": "OPAL filter"}
        ],
        "timeout": [
            {"name": "query_optimization", "approach": "specific_docs", "search_terms": "OPAL performance limit"},
            {"name": "simpler_query", "approach": "fundamental_rebuild", "search_terms": "OPAL simple fast"},
            {"name": "basic_limit", "approach": "minimal_query", "search_terms": "OPAL limit"}
        ],
        "http_400": [
            {"name": "request_correction", "approach": "specific_docs", "search_terms": "OPAL valid queries in function filter boolean"},
            {"name": "syntax_rebuild", "approach": "fundamental_rebuild", "search_terms": "OPAL basic syntax filter statsby"},
            {"name": "minimal_query", "approach": "minimal_query", "search_terms": "OPAL simple filter"}
        ],
        "generic_error": [
            {"name": "general_fix", "approach": "specific_docs", "search_terms": "OPAL common errors"},
            {"name": "basic_rebuild", "approach": "fundamental_rebuild", "search_terms": "OPAL basic examples"},
            {"name": "fallback_simple", "approach": "minimal_query", "search_terms": "OPAL"}
        ]
    }
    
    # Get strategy list for error type, fallback to generic_error
    strategy_list = strategies.get(error_type, strategies["generic_error"])
    
    # Select strategy based on retry count (0-indexed)
    strategy_index = min(retry_count - 1, len(strategy_list) - 1)
    return strategy_list[strategy_index]


def apply_surgical_fix(failed_query: str, error_result: str, error_type: str, schema_info: str) -> str:
    """
    Apply targeted, surgical fixes to OPAL queries based on specific error messages.
    This preserves the original query structure while fixing specific syntax issues.
    """
    fixed_query = failed_query
    error_lower = error_result.lower()
    
    print(f"[SURGICAL_FIX] Applying targeted fix for {error_type}", file=sys.stderr)
    print(f"[SURGICAL_FIX] Original query: {fixed_query[:100]}...", file=sys.stderr)
    
    # CRITICAL FIX: Remove invalid dataset references at query start
    # These appear as "o::xxx:dataset:yyy | filter..." which breaks OPAL parsing
    dataset_pattern = r'^o::[^|]+\s*\|\s*'
    if re.match(dataset_pattern, fixed_query.strip()):
        fixed_query = re.sub(dataset_pattern, '', fixed_query.strip())
        print(f"[SURGICAL_FIX] Removed invalid dataset prefix from query", file=sys.stderr)
    
    # Handle HTTP 400 errors which often have dataset references or parsing issues
    if error_type == "http_400":
        if "expected one of" in error_lower:
            # This is usually caused by dataset references at query start
            dataset_ref_pattern = r'^o::[^|]*\|\s*'
            if re.search(dataset_ref_pattern, fixed_query):
                fixed_query = re.sub(dataset_ref_pattern, '', fixed_query)
                print(f"[SURGICAL_FIX] Removed dataset reference causing HTTP 400", file=sys.stderr)
        
        # Fix multi-line statsby queries - common cause of HTTP 400
        if "statsby" in fixed_query and "\n" in fixed_query:
            lines = [line.strip() for line in fixed_query.split('\n') if line.strip()]
            if len(lines) > 1 and lines[0].strip() == "statsby":
                # Convert multi-line statsby to single line
                aggregations = []
                for line in lines[1:]:
                    if line and not line.startswith('|'):
                        # Remove trailing comma if present
                        line = line.rstrip(',')
                        aggregations.append(line)
                    elif line.startswith('|'):
                        # This is a new pipeline stage, stop collecting aggregations
                        break
                
                if aggregations:
                    single_line = f"statsby {', '.join(aggregations)}"
                    # Add remaining pipeline if present
                    remaining = fixed_query.split('|', 1)[1:] if '|' in fixed_query else []
                    if remaining:
                        fixed_query = f"{single_line} | {remaining[0]}"
                    else:
                        fixed_query = single_line
                    print(f"[SURGICAL_FIX] Converted multi-line statsby to single line", file=sys.stderr)
        
        # Fix duration function string arguments
        if "duration(" in fixed_query and '"' in fixed_query:
            # Convert duration("100ms") to duration_ms(100) or similar
            duration_pattern = r'duration\("([^"]+)"\)'
            matches = re.findall(duration_pattern, fixed_query)
            for match in matches:
                if match.endswith('ms'):
                    # Convert "100ms" to duration_ms(100)
                    num = re.sub(r'[^\d.]', '', match)
                    if num:
                        fixed_query = re.sub(f'duration\\("{re.escape(match)}"\\)', f'duration_ms({num})', fixed_query)
                        print(f"[SURGICAL_FIX] Fixed duration string: duration(\"{match}\") -> duration_ms({num})", file=sys.stderr)
                elif match.endswith('s'):
                    # Convert "1s" to 1000000000 (nanoseconds)
                    num = re.sub(r'[^\d.]', '', match)
                    if num:
                        ns_value = int(float(num) * 1000000000)
                        fixed_query = re.sub(f'duration\\("{re.escape(match)}"\\)', str(ns_value), fixed_query)
                        print(f"[SURGICAL_FIX] Fixed duration string: duration(\"{match}\") -> {ns_value}ns", file=sys.stderr)
        
        # Fix field reference errors - common pattern: "field \"null\" does not exist"
        if 'field "null" does not exist' in error_result:
            # Replace references to literal null field with actual null checks
            fixed_query = re.sub(r'\bnull\s*(?![=(])', 'is_null(field_name)', fixed_query)
            print(f"[SURGICAL_FIX] Fixed null field reference", file=sys.stderr)
        
        elif 'field "undefined" does not exist' in error_result:
            # Replace references to literal undefined field 
            fixed_query = re.sub(r'\bundefined\s*(?![=(])', 'is_null(field_name)', fixed_query)
            print(f"[SURGICAL_FIX] Fixed undefined field reference", file=sys.stderr)
        
        # Fix syntax errors - handle common comma/colon issues
        if "expected ','" in error_result:
            # Look for missing commas in function arguments or statsby aggregations
            if "statsby" in fixed_query:
                # Add commas between aggregation functions if missing
                fixed_query = re.sub(r'(\w+\([^)]*\))\s+(\w+\()', r'\1, \2', fixed_query)
                print(f"[SURGICAL_FIX] Added missing comma in statsby aggregation", file=sys.stderr)
        
        if "expected ':'" in error_result:
            # Look for missing colons in field assignments or aggregations
            if "statsby" in fixed_query:
                # Fix aggregations missing colons like "count count()" -> "count:count()"
                fixed_query = re.sub(r'\b(\w+)\s+(\w+\([^)]*\))', r'\1:\2', fixed_query)
                print(f"[SURGICAL_FIX] Added missing colon in field assignment", file=sys.stderr)
        
        # Fix double pipe || syntax issues - OPAL uses single pipe |
        if "||" in fixed_query:
            # Replace double pipes with single pipes for OPAL pipeline
            fixed_query = re.sub(r'\|\|', '|', fixed_query)
            print(f"[SURGICAL_FIX] Fixed double pipe syntax: || -> |", file=sys.stderr)
        
        # Fix field selection syntax issues with pick/fields confusion
        if "fields" in error_lower and "unknown" in error_lower:
            # Handle cases where fields verb is used incorrectly
            if re.search(r'\bfields\s+[^|]+\|', fixed_query):
                # Incorrect: fields field1, field2 | next_stage
                # Correct: pick_col field1, field2 | next_stage
                fixed_query = re.sub(r'\bfields\b', 'pick_col', fixed_query)
                print(f"[SURGICAL_FIX] Fixed field selection: fields -> pick_col", file=sys.stderr)
        
        # Fix pod/container field selection patterns
        if "pick_col" in fixed_query and ("name" in fixed_query or "status" in fixed_query):
            # Common issue: trying to select fields that don't exist in schema
            # Replace common pod field patterns with available fields
            pod_field_mappings = {
                r'\bpod_name\b': 'podName',
                r'\bpod\.name\b': 'podName', 
                r'\bcontainer_name\b': 'containerName',
                r'\bcontainer\.name\b': 'containerName',
                r'\bnode_name\b': 'nodeName',
                r'\bnode\.name\b': 'nodeName',
                r'\bstatus\b(?!\s*[><=])': 'status',  # status not in comparison
                r'\bphase\b': 'phase'
            }
            
            for pattern, replacement in pod_field_mappings.items():
                if re.search(pattern, fixed_query):
                    fixed_query = re.sub(pattern, replacement, fixed_query)
                    print(f"[SURGICAL_FIX] Fixed pod field: {pattern} -> {replacement}", file=sys.stderr)
    
    elif error_type == "unknown_verb":
        # Extract the specific unknown verb from error message
        if "unknown verb" in error_lower:
            # Pattern: "unknown verb \"by\""
            match = re.search(r'unknown verb "([^"]+)"', error_result)
            if match:
                bad_verb = match.group(1)
                if bad_verb == "by":
                    # Replace standalone "by" with proper group_by() function
                    fixed_query = re.sub(r'\s+by\s+([a-zA-Z_]\w*)', r', group_by(\1)', fixed_query)
                    print(f"[SURGICAL_FIX] Fixed 'by' verb: {bad_verb} -> group_by()", file=sys.stderr)
                    
        if "unknown function" in error_lower:
            # Pattern: "unknown function \"by\""
            match = re.search(r'unknown function "([^"]+)"', error_result)
            if match:
                bad_func = match.group(1)
                if bad_func == "by":
                    # Fix "by(field)" to "group_by(field)" 
                    fixed_query = re.sub(r'\bby\s*\(', 'group_by(', fixed_query)
                    print(f"[SURGICAL_FIX] Fixed function: {bad_func}() -> group_by()", file=sys.stderr)
                elif bad_func == "isempty":
                    # Fix "isempty(field)" to "is_null(field)"
                    fixed_query = re.sub(r'\bisempty\s*\(', 'is_null(', fixed_query)
                    print(f"[SURGICAL_FIX] Fixed function: {bad_func}() -> is_null()", file=sys.stderr)
                elif bad_func == "length":
                    # Fix "length(field)" to "strlen(field)" for strings or "array_length(field)" for arrays
                    # Default to strlen for safety since most length calls are on strings
                    fixed_query = re.sub(r'\blength\s*\(', 'strlen(', fixed_query)
                    print(f"[SURGICAL_FIX] Fixed function: {bad_func}() -> strlen()", file=sys.stderr)
                elif bad_func == "size":
                    # Fix "size(field)" to "array_length(field)" for arrays
                    fixed_query = re.sub(r'\bsize\s*\(', 'array_length(', fixed_query)
                    print(f"[SURGICAL_FIX] Fixed function: {bad_func}() -> array_length()", file=sys.stderr)
                elif bad_func in ["empty", "isEmpty"]:
                    # Common variations of empty check
                    fixed_query = re.sub(rf'\b{bad_func}\s*\(', 'is_null(', fixed_query)
                    print(f"[SURGICAL_FIX] Fixed function: {bad_func}() -> is_null()", file=sys.stderr)
                elif bad_func == "bin_auto":
                    # Fix "bin_auto()" to use explicit time binning
                    # Common pattern: timechart bin_auto(field) -> timechart 5m, aggregation
                    if "timechart" in fixed_query:
                        # Replace bin_auto with standard time binning
                        fixed_query = re.sub(r'\bbin_auto\s*\([^)]*\)', '5m', fixed_query)
                        print(f"[SURGICAL_FIX] Fixed function: {bad_func}() -> 5m (explicit time bin)", file=sys.stderr)
                    else:
                        # In other contexts, bin_auto might be for histogram binning
                        fixed_query = re.sub(r'\bbin_auto\s*\(([^)]+)\)', r'histogram(\1, 10)', fixed_query)
                        print(f"[SURGICAL_FIX] Fixed function: {bad_func}() -> histogram() with 10 bins", file=sys.stderr)
    
    elif error_type == "line_continuation_error":
        # Fix multi-line query formatting
        lines = fixed_query.split('\n')
        if len(lines) > 1:
            # Join lines with proper OPAL continuation (no line breaks within statements)
            fixed_lines = []
            current_statement = ""
            
            for line in lines:
                line = line.strip()
                if line:
                    if current_statement and not line.startswith('|'):
                        current_statement += " " + line
                    elif line.startswith('|') or not current_statement:
                        if current_statement:
                            fixed_lines.append(current_statement)
                        current_statement = line
                    
            if current_statement:
                fixed_lines.append(current_statement)
                
            fixed_query = " ".join(fixed_lines)
            print(f"[SURGICAL_FIX] Fixed line continuation", file=sys.stderr)
    
    # Universal multi-line query fixes - apply to all error types
    if '\n' in fixed_query:
        # Fix JSON nested in OPAL causing line break issues
        if '{' in fixed_query and '}' in fixed_query:
            # Convert multi-line JSON to single line within OPAL
            json_pattern = r'\{\s*([^}]+)\s*\}'
            def fix_json(match):
                content = match.group(1)
                # Remove line breaks and normalize whitespace within JSON
                content = re.sub(r'\s+', ' ', content.replace('\n', ' '))
                return '{' + content + '}'
            
            fixed_query = re.sub(json_pattern, fix_json, fixed_query, flags=re.DOTALL)
            print(f"[SURGICAL_FIX] Fixed nested JSON formatting", file=sys.stderr)
        
        # Remove line breaks that aren't part of string literals
        if not ('"""' in fixed_query or "'''" in fixed_query):
            # Safe to join lines - no multi-line strings
            lines = [line.strip() for line in fixed_query.split('\n') if line.strip()]
            fixed_query = ' '.join(lines)
            print(f"[SURGICAL_FIX] Collapsed multi-line query to single line", file=sys.stderr)
    
    elif error_type == "invalid_options":
        # Fix invalid timechart/statsby options
        if "timechart" in error_lower and "size" in error_lower:
            # Replace size option with valid bins option
            fixed_query = re.sub(r'options\([^)]*size[^)]*\)', 'options(bins:10)', fixed_query)
            print(f"[SURGICAL_FIX] Fixed invalid timechart options", file=sys.stderr)
    
    elif error_type == "field_not_found":
        # Extract field name that doesn't exist and try to map it to schema
        field_match = re.search(r'field "([^"]+)" does not exist among fields', error_result)
        if field_match:
            missing_field = field_match.group(1)
            # Try to find similar field in schema (simple fuzzy matching)
            schema_fields = re.findall(r"'name': '([^']+)'", schema_info)
            
            # Simple similarity matching
            best_match = None
            for field in schema_fields:
                if missing_field.lower() in field.lower() or field.lower() in missing_field.lower():
                    best_match = field
                    break
            
            if best_match:
                fixed_query = fixed_query.replace(missing_field, best_match)
                print(f"[SURGICAL_FIX] Mapped field: {missing_field} -> {best_match}", file=sys.stderr)
    
    # NEW: Add fixes based on documented OPAL capabilities
    # Fix filter syntax with multiple values - use IN operator 
    if "filter" in fixed_query and ("=" in fixed_query or "==" in fixed_query):
        # Look for patterns like: filter field == 'value1' or field == 'value2'
        or_pattern = r"(\w+)\s*==?\s*'([^']+)'\s+or\s+\1\s*==?\s*'([^']+)'"
        match = re.search(or_pattern, fixed_query)
        if match:
            field, val1, val2 = match.groups()
            replacement = f"filter in({field}, '{val1}', '{val2}')"
            fixed_query = re.sub(or_pattern, replacement.replace('filter ', ''), fixed_query)
            print(f"[SURGICAL_FIX] Converted OR filter to IN operator: {field} == '{val1}' or {field} == '{val2}' -> in({field}, '{val1}', '{val2}')", file=sys.stderr)
    
    # Fix JSON field access - use get_field() or path navigation
    if "." in fixed_query and not re.search(r'\bget_field\b', fixed_query):
        # Look for patterns like: field.subfield
        field_access_pattern = r'(\w+)\.(\w+)'
        matches = re.findall(field_access_pattern, fixed_query)
        for base_field, sub_field in matches:
            # Replace with get_field function 
            fixed_query = re.sub(rf'\b{base_field}\.{sub_field}\b', f"get_field({base_field}, '{sub_field}')", fixed_query)
            print(f"[SURGICAL_FIX] Fixed JSON field access: {base_field}.{sub_field} -> get_field({base_field}, '{sub_field}')", file=sys.stderr)
    
    # Fix array/list filtering - suggest array functions
    if "array" in error_lower or "list" in error_lower:
        if "array_contains" not in fixed_query and "[" in fixed_query:
            # Suggest array_contains for array filtering 
            bracket_pattern = r"(\w+)\[(\d+)\]"
            matches = re.findall(bracket_pattern, fixed_query)
            if matches:
                print(f"[SURGICAL_FIX] Array access detected - consider using array_contains() instead of index access", file=sys.stderr)
    
        # Additional common OPAL syntax fixes for HTTP 400 errors
        
        # Fix incorrect aggregation syntax in statsby
        if "statsby" in fixed_query:
            # Fix missing group_by in statsby aggregations
            if "group_by" not in fixed_query and ("by" in fixed_query or "group" in fixed_query):
                # Pattern: statsby count(), field -> statsby count(), group_by(field)
                statsby_pattern = r'statsby\s+([^|]+?)(?:,\s*by\s+(\w+)|,\s*group\s+(\w+)|,\s*(\w+)(?=\s*\|))'
                match = re.search(statsby_pattern, fixed_query)
                if match:
                    aggregation = match.group(1).strip()
                    group_field = match.group(2) or match.group(3) or match.group(4)
                    if group_field and not group_field.startswith('group_by'):
                        fixed_query = re.sub(statsby_pattern, f'statsby {aggregation}, group_by({group_field})', fixed_query)
                        print(f"[SURGICAL_FIX] Fixed statsby grouping: added group_by({group_field})", file=sys.stderr)
        
        # Fix percentage/ratio calculations
        if "percentage" in error_lower or "ratio" in error_lower:
            # Common issue: trying to calculate percentages without proper aggregation
            if "%" in fixed_query:
                # Remove % symbols as they're not OPAL syntax
                fixed_query = fixed_query.replace('%', '')
                print(f"[SURGICAL_FIX] Removed percentage symbols (not OPAL syntax)", file=sys.stderr)
        
        # Fix time duration constants
        time_duration_fixes = {
            r'\b1min\b': '1m',
            r'\b5min\b': '5m', 
            r'\b10min\b': '10m',
            r'\b30min\b': '30m',
            r'\b1hour\b': '1h',
            r'\b2hours\b': '2h',
            r'\b24hours\b': '24h',
            r'\b1week\b': '168h',
            r'\b(\d+)\s*minutes?\b': r'\1m',
            r'\b(\d+)\s*hours?\b': r'\1h',
            r'\b(\d+)\s*days?\b': r'\1d'
        }
        
        for pattern, replacement in time_duration_fixes.items():
            if re.search(pattern, fixed_query, re.IGNORECASE):
                fixed_query = re.sub(pattern, replacement, fixed_query, flags=re.IGNORECASE)
                print(f"[SURGICAL_FIX] Fixed time duration: {pattern} -> {replacement}", file=sys.stderr)
        
        # Fix comparison operators
        comparison_fixes = {
            r'\bis\s+not\s+null\b': 'is not null',
            r'\bis\s+null\b': 'is null',
            r'\bnot\s+equal\s+to\b': '!=',
            r'\bequals\s+to\b': '==',
            r'\bgreater\s+than\b': '>',
            r'\bless\s+than\b': '<',
            r'\bcontains\b(?!\s*\()': '~'  # contains not as function
        }
        
        for pattern, replacement in comparison_fixes.items():
            if re.search(pattern, fixed_query, re.IGNORECASE):
                fixed_query = re.sub(pattern, replacement, fixed_query, flags=re.IGNORECASE)
                print(f"[SURGICAL_FIX] Fixed comparison operator: {pattern} -> {replacement}", file=sys.stderr)
    
    elif error_type == "type_mismatch":
        # Fix type mismatches (e.g., string instead of numeric for duration)
        if "duration" in error_lower and "string" in error_lower:
            # Common issue: using string field for duration calculation
            # Look for duration function calls with string arguments
            duration_pattern = r'duration\([^)]*"([^"]+)"[^)]*\)'
            matches = re.findall(duration_pattern, fixed_query)
            for match in matches:
                # Try to convert string field references to proper field access
                fixed_query = re.sub(f'duration\\([^)]*"{match}"[^)]*\\)', f'duration({match})', fixed_query)
                print(f"[SURGICAL_FIX] Fixed duration type: \"{match}\" -> {match}", file=sys.stderr)
    
    # Final cleanup: fix escape sequences and normalize whitespace
    fixed_query = fixed_query.replace('\\n', ' ').replace('\\t', ' ')
    fixed_query = re.sub(r'\s+', ' ', fixed_query).strip()
    
    # Remove any remaining dataset references that might cause issues
    fixed_query = re.sub(r'^o::[^|]*\|\s*', '', fixed_query)
    
    # Ensure proper OPAL syntax structure
    if fixed_query and not re.match(r'^(filter|statsby|timechart|fields|sort|limit)', fixed_query):
        print(f"[SURGICAL_FIX] Warning: Query doesn't start with valid OPAL verb", file=sys.stderr)
    
    print(f"[SURGICAL_FIX] Result: {fixed_query[:100]}...", file=sys.stderr)
    return fixed_query


async def apply_recovery_strategy(strategy: dict, failed_query: str, error_result: str, 
                                error_type: str, primary_model, fallback_model, schema_info: str, request: str, 
                                dataset_id: str, recovery_history: list = None) -> str:
    """
    Apply the selected recovery strategy to generate a corrected query.
    """
    approach = strategy["approach"]
    search_terms = strategy["search_terms"]
    
    print(f"[NLPQ_RELIABILITY] Applying {approach} strategy with search: {search_terms}", file=sys.stderr)
    
    try:
        # Get strategy-specific documentation
        from src.pinecone.search import search_docs
        
        if approach == "specific_docs":
            # Targeted documentation search
            doc_results = search_docs(f"{search_terms} {error_type}", n_results=8)
        elif approach == "schema_focused":
            # Schema-aware documentation search
            doc_results = search_docs(f"{search_terms} schema fields", n_results=10)
        elif approach == "fundamental_rebuild":
            # Basic OPAL documentation
            doc_results = search_docs(search_terms, n_results=12)
        else:  # minimal_query
            # Simplest possible queries
            doc_results = search_docs(f"{search_terms} basic simple", n_results=5)
        
        # Format documentation
        if doc_results and len(doc_results) > 0:
            recovery_docs = f"Recovery documentation for {strategy['name']}:\\n\\n"
            for i, result in enumerate(doc_results[:5], 1):
                text = result.get("text", "")
                recovery_docs += f"{i}. {text[:400]}{'...' if len(text) > 400 else ''}\\n\\n"
        else:
            recovery_docs = "No specific recovery documentation found - using basic OPAL guidance"
        
        # Build conversational context
        conversation_context = ""
        if recovery_history:
            conversation_context = f"""
PREVIOUS RECOVERY ATTEMPTS:
{chr(10).join(recovery_history[-3:])}  # Show last 3 attempts

LEARNING FROM FAILURES: The above attempts didn't work. Learn from these patterns and avoid repeating the same mistakes.
"""

        # Create strategy-specific prompt
        if approach == "minimal_query":
            recovery_prompt = f"""The query failed with {error_type}. Generate the SIMPLEST possible OPAL query to get ANY data from this request.

USER REQUEST: {request}
FAILED QUERY: {failed_query}
ERROR: {error_result[:200]}
{conversation_context}
AVAILABLE FIELDS FROM SCHEMA:
{schema_info[:800]}

STRATEGY: Create the most basic query possible using ONLY the fields listed above.

CRITICAL RULES:
- Use ONLY these verbs: filter, statsby, timechart, fields, sort, limit
- NEVER: pick, select, by, show, get (these cause 400 errors)
- Use 'fields' not 'pick' for column selection
- For aggregation: statsby count:count(), group_by(field_name)
- For multiple values: use in(field, 'value1', 'value2', 'value3') function
- For JSON fields: use get_field(object, 'key') to extract nested values
- Field names must exist in the schema above
- Percentiles: use 0.95, 0.99 (not 95, 99)
- No time filtering - API handles time range

Generate the simplest working OPAL query using only schema fields:"""
        
        elif approach == "schema_focused":
            recovery_prompt = f"""The query failed with {error_type}. Rebuild using ONLY fields from the schema.

USER REQUEST: {request}
FAILED QUERY: {failed_query}
ERROR: {error_result[:200]}
{conversation_context}
AVAILABLE SCHEMA:
{schema_info}

RECOVERY GUIDANCE:
{recovery_docs}

STRATEGY: Carefully map the user request to available schema fields. Use exact field names.

CRITICAL RULES:
- ONLY use field names that appear in the schema above
- For multiple values: use in(field, 'value1', 'value2') instead of OR conditions
- For JSON objects: use get_field(object, 'key') to access nested fields
- Check field types before using in aggregations
- Use proper OPAL syntax from documentation
- Start simple and build up

Generate a corrected OPAL query using schema fields:"""
        
        else:  # specific_docs or fundamental_rebuild
            recovery_prompt = f"""The query failed with {error_type}. Generate a corrected version using proper OPAL syntax.

USER REQUEST: {request}
FAILED QUERY: {failed_query}
ERROR: {error_result[:200]}
{conversation_context}
SCHEMA INFO:
{schema_info[:500]}

RECOVERY GUIDANCE:
{recovery_docs}

STRATEGY: Use the documentation above to fix the specific error while maintaining the user's intent.

CRITICAL RULES:
- Follow EXACT syntax from the documentation
- Use only verbs shown in the recovery guidance
- For multiple values: use in(field, 'value1', 'value2', 'value3') function
- For JSON objects: use get_field(object, 'key') or path_exists() functions
- Use proper boolean functions: contains(), starts_with(), ends_with()
- For array data: use array_contains() instead of direct indexing
- Respect field names from schema
- Fix the specific error mentioned
- For error rate analysis: Use statsby error_rate:avg(if(error, 1.0, 0.0)), group_by(service_field)
- For complex requests: Break into simple aggregations with conditional logic

Generate a corrected OPAL query:"""
        
        # Generate recovery query
        recovery_response = invoke_with_fallback(primary_model, fallback_model, [HumanMessage(content=recovery_prompt)], "recovery strategy")
        fixed_query = recovery_response.content.strip()
        
        # Clean the response
        if "```" in fixed_query:
            fixed_query = fixed_query.split("```")[1]
            if fixed_query.startswith("opal"):
                fixed_query = fixed_query[4:]
        
        # Remove explanatory text - keep only the query
        lines = fixed_query.split('\\n')
        cleaned_lines = []
        for line in lines:
            line = line.strip()
            if line and not line.lower().startswith(('the ', 'this ', 'here ', 'query:')):
                cleaned_lines.append(line)
        
        fixed_query = '\\n'.join(cleaned_lines).strip()
        if fixed_query.startswith('|'):
            fixed_query = fixed_query[1:].strip()
        
        print(f"[NLPQ_RELIABILITY] Strategy generated: {fixed_query[:100]}...", file=sys.stderr)
        
        # Apply validation and fixes to recovery query too
        validation_issues = validate_query_syntax(fixed_query, schema_info)
        if validation_issues:
            print(f"[NLPQ_RELIABILITY] Recovery query has issues: {validation_issues[:100]}...", file=sys.stderr)
            fixed_query = fix_obvious_issues(fixed_query, validation_issues)
            print(f"[NLPQ_RELIABILITY] Auto-fixed recovery query: {fixed_query[:100]}...", file=sys.stderr)
        
        return fixed_query
        
    except Exception as e:
        print(f"[NLPQ_RELIABILITY] Recovery strategy failed: {e}", file=sys.stderr)
        # Fallback to basic query (no time filtering)
        if "count" in request.lower() or "how many" in request.lower():
            return "statsby count:count()"
        elif "distinct" in request.lower() or "unique" in request.lower():
            return "limit 10"  # Safe fallback - just show data
        else:
            return "limit 5"  # Safe fallback - just show data


async def execute_with_retry(query: str, dataset_id: str, time_range: str, 
                           start_time: str, end_time: str, max_retries: int = 2) -> str:
    """
    Execute query with exponential backoff for transient failures.
    """
    from src.observe import execute_opal_query as observe_execute_opal_query
    
    for attempt in range(max_retries + 1):
        try:
            if attempt > 0:
                wait_time = min(2 ** attempt, 5)  # Cap at 5 seconds
                print(f"[NLPQ_RELIABILITY] Retrying query execution in {wait_time}s (attempt {attempt + 1})", file=sys.stderr)
                await asyncio.sleep(wait_time)
            
            result = await observe_execute_opal_query(
                query=query,
                dataset_id=dataset_id,
                time_range=time_range,
                start_time=start_time,
                end_time=end_time,
                row_count=50
            )
            
            return result
            
        except Exception as e:
            if attempt == max_retries:
                return f"Error: Query execution failed after {max_retries + 1} attempts: {str(e)}"
            print(f"[NLPQ_RELIABILITY] Execution attempt {attempt + 1} failed: {e}", file=sys.stderr)
    
    return "Error: Maximum retries exceeded"


def validate_query_syntax(query: str, schema_info: str) -> list:
    """
    Pre-validate OPAL query syntax to catch obvious issues before execution.
    Returns list of validation issues found.
    """
    issues = []
    query_lower = query.lower()
    
    # Check for invalid verbs (most common issue)
    invalid_verbs = ['pick', 'select', 'show', 'get', 'choose', 'find', 'by']
    for verb in invalid_verbs:
        if f'{verb}(' in query_lower or f' {verb} ' in query_lower:
            if verb == 'pick':
                issues.append("Invalid verb 'pick' - use 'fields' instead")
            elif verb == 'by':
                issues.append("Invalid verb 'by' - use 'group_by()' function")
            else:
                issues.append(f"Invalid verb '{verb}' - use valid OPAL verbs only")
    
    # Check for percentile range errors
    if 'percentile(' in query_lower:
        percentile_matches = re.findall(r'percentile\([^,]+,\s*(\d+)', query)
        for match in percentile_matches:
            if int(match) > 1:
                issues.append(f"Percentile value {match} should be 0.{match} (decimal between 0-1)")
    
    # Check for SQL syntax leakage
    sql_keywords = ['select', 'from', 'where', 'group by', 'order by', 'having', 'join']
    for keyword in sql_keywords:
        if keyword in query_lower:
            issues.append(f"SQL keyword '{keyword}' found - use OPAL syntax instead")
    
    # Check for forbidden field references
    forbidden_fields = ['_c_timestamp', '@.now', 'now', '@."timestamp"']
    for field in forbidden_fields:
        if field.lower() in query_lower:
            issues.append(f"Forbidden field reference '{field}' - check schema for valid field names")
    
    # Check for invalid OPAL patterns
    if 'filter options(' in query_lower:
        issues.append("Invalid 'filter options()' - options should be used with timechart/statsby")
    
    if 'dataset(' in query_lower:
        issues.append("Invalid 'dataset()' function - dataset is already specified")
    
    # Check for time filtering attempts (should be handled by API parameters)
    time_patterns = ['start_time >', 'end_time >', 'timestamp >', 'frame back:', '@now', '@."timestamp"', 'filter.*time.*>', 'time.*between']
    for pattern in time_patterns:
        if re.search(pattern, query_lower):
            issues.append(f"Time filtering detected '{pattern}' - time range is handled by API parameters, not OPAL query")
    
    # Check for case() function usage (should be if())
    if 'case(' in query_lower:
        issues.append("Use if() function instead of case() - syntax: if(condition, true_value, false_value)")
    
    # Check for invalid sort syntax
    if re.search(r'sort\s+-', query_lower):
        issues.append("Invalid sort syntax with dash - use 'sort desc(field)' or 'sort asc(field)'")
    if re.search(r'sort\s+\w+\s+(desc|asc)', query_lower):
        issues.append("Invalid sort syntax - use 'sort desc(field)' not 'sort field desc'")
    if re.search(r'sort\s+(desc|asc)\s+\w+', query_lower):
        issues.append("Invalid sort syntax - use 'sort desc(field)' with parentheses")
    if re.search(r'sort\s+\w+\s*$', query_lower):
        issues.append("Invalid sort syntax - use 'sort desc(field)' or 'sort asc(field)' with parentheses")
    
    # Check for make_col assignment operator (should use : not =)
    if re.search(r'make_col\s+\w+\s*=', query_lower):
        issues.append("Invalid make_col syntax - use 'make_col column:expression' not 'make_col column = expression'")
    
    # Check for made-up verbs (common hallucinations)
    hallucinated_verbs = ['make_set', 'find', 'pick', 'choose', 'get', 'show']
    for verb in hallucinated_verbs:
        if f'{verb}(' in query_lower:
            issues.append(f"Invalid verb '{verb}()' - not a valid OPAL verb")
    
    # Check for basic syntax issues
    if query.count('(') != query.count(')'):
        issues.append("Mismatched parentheses")
    
    # Check for multiple pipes without verbs
    if '||' in query:
        issues.append("Double pipe '||' found - use single pipe '|' between OPAL verbs")
    
    return issues


def fix_obvious_issues(query: str, issues: list) -> str:
    """
    Fix obvious syntax issues in OPAL query.
    """
    fixed_query = query
    
    # Fix invalid verbs first (most critical)
    if "Invalid verb 'pick'" in str(issues):
        fixed_query = fixed_query.replace(' pick ', ' | fields ')
        fixed_query = fixed_query.replace('| pick ', '| fields ')
    
    if "Invalid verb 'by'" in str(issues):
        # This is tricky - usually appears as "by service_name" and should be "group_by(service_name)"
        fixed_query = re.sub(r'\s+by\s+(\w+)', r', group_by(\1)', fixed_query)
    
    # Fix percentile values
    for issue in issues:
        if "Percentile value" in issue and "should be 0." in issue:
            # Extract the bad value and fix it
            matches = re.findall(r'percentile\(([^,]+),\s*(\d+)\)', fixed_query)
            for field, bad_val in matches:
                if int(bad_val) > 1:
                    good_val = f"0.{bad_val}" if int(bad_val) < 100 else "0.99"
                    fixed_query = fixed_query.replace(f'percentile({field}, {bad_val})', f'percentile({field}, {good_val})')
    
    for issue in issues:
        if "SQL keyword" in issue:
            # Remove common SQL keywords
            sql_replacements = {
                'select ': '',
                'from ': '',
                'where ': 'filter ',
                'group by': 'group_by',
                'order by': 'sort',
                'having ': '',
                'join ': ''
            }
            for sql_term, opal_term in sql_replacements.items():
                fixed_query = fixed_query.replace(sql_term, opal_term)
                fixed_query = fixed_query.replace(sql_term.upper(), opal_term)
        
        elif "filter options()" in issue:
            # Move options to appropriate verb
            fixed_query = fixed_query.replace('filter options(', 'filter ')
            if 'timechart' in fixed_query:
                fixed_query = fixed_query.replace('timechart', 'timechart options(empty_bins:true)')
        
        elif "dataset()" in issue:
            # Remove dataset() function calls
            fixed_query = re.sub(r'dataset\([^)]*\)\s*\|\s*', '', fixed_query)
        
        elif "Time filtering detected" in issue:
            # Remove time filtering clauses - time is handled by API parameters
            # Remove common time filtering patterns
            time_removal_patterns = [
                r'filter\s+start_time\s*[><=]+[^|]*\|?',
                r'filter\s+end_time\s*[><=]+[^|]*\|?',
                r'filter\s+timestamp\s*[><=]+[^|]*\|?',
                r'frame\s+back:\s*[^|]*\|?',
                r'@now[^|]*\|?',
                r'@\."timestamp"[^|]*\|?'
            ]
            for pattern in time_removal_patterns:
                fixed_query = re.sub(pattern, '', fixed_query, flags=re.IGNORECASE)
            # Clean up any resulting empty filters or double pipes
            fixed_query = re.sub(r'\|\s*\|', '|', fixed_query)
            fixed_query = re.sub(r'^\s*\|\s*', '', fixed_query)  # Remove leading pipe
            fixed_query = re.sub(r'\s*\|\s*$', '', fixed_query)  # Remove trailing pipe
        
        elif "Use if() function instead of case()" in issue:
            # Convert case() to if() function
            # Pattern to match case(condition, true_value, false_value) and similar
            fixed_query = re.sub(r'\bcase\s*\(', 'if(', fixed_query, flags=re.IGNORECASE)
            # Handle complex case patterns like case(metric="x", value, true, 0)
            # Convert to if(metric="x", value, 0)
            fixed_query = re.sub(r'if\(([^,]+),\s*([^,]+),\s*true,\s*([^)]+)\)', r'if(\1, \2, \3)', fixed_query)
        
        elif "Invalid sort syntax" in issue:
            # Fix sort syntax issues
            # Fix sort -field to sort desc(field)
            fixed_query = re.sub(r'sort\s+-(\w+)', r'sort desc(\1)', fixed_query, flags=re.IGNORECASE)
            # Fix sort field desc to sort desc(field)
            fixed_query = re.sub(r'sort\s+(\w+)\s+(desc|asc)', r'sort \2(\1)', fixed_query, flags=re.IGNORECASE)
            # Fix sort desc field to sort desc(field)
            fixed_query = re.sub(r'sort\s+(desc|asc)\s+(\w+)', r'sort \1(\2)', fixed_query, flags=re.IGNORECASE)
            # Fix bare sort field to sort desc(field)
            fixed_query = re.sub(r'sort\s+([a-zA-Z_]\w*)\s*(\||$)', r'sort desc(\1)\2', fixed_query, flags=re.IGNORECASE)
        
        elif "Invalid make_col syntax" in issue:
            # Fix make_col assignment operator (= to :)
            # Fix make_col column = expression to make_col column:expression
            fixed_query = re.sub(r'make_col\s+(\w+)\s*=\s*', r'make_col \1:', fixed_query, flags=re.IGNORECASE)
        
        elif "Invalid verb" in issue:
            # Replace common hallucinated verbs
            verb_replacements = {
                'make_set(': 'distinct(',
                'find(': 'filter ',
                'pick(': 'filter ',
                'choose(': 'filter ',
                'get(': 'filter ',
                'show(': 'filter '
            }
            for bad_verb, good_verb in verb_replacements.items():
                fixed_query = fixed_query.replace(bad_verb, good_verb)
        
        elif "Double pipe" in issue:
            fixed_query = fixed_query.replace('||', '|')
        
        elif "Mismatched parentheses" in issue:
            # Try to balance parentheses (basic attempt)
            open_count = fixed_query.count('(')
            close_count = fixed_query.count(')')
            if open_count > close_count:
                fixed_query += ')' * (open_count - close_count)
            elif close_count > open_count:
                fixed_query = fixed_query.rstrip(')')
                fixed_query += ')' * open_count
    
    return fixed_query.strip()
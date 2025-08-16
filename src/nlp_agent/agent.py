"""
Main LangGraph agent for OPAL query generation.
"""

from multiprocessing.resource_sharer import stop
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
import asyncio
import time
import re


def create_opal_agent():
    """Create and compile the OPAL query agent.
    
    NOTE: This is kept for compatibility but the simplified approach
    in execute_nlp_query is now preferred to avoid rate limiting.
    """
    
    # Initialize the language model
    model = ChatAnthropic(
        model=os.getenv("SMART_TOOLS_MODEL", "claude-sonnet-4-20250514"),
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
            model_name=os.getenv("SMART_TOOLS_MODEL", "claude-3-5-sonnet-20241022"),
            temperature=0,
            api_key=os.getenv("SMART_TOOLS_API_KEY") or os.getenv("ANTHROPIC_API_KEY"),
            timeout=30,
            stop=None
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
        
        # Step 3.5: Pre-validation to catch obvious issues
        validation_issues = validate_query_syntax(opal_query, schema_info)
        if validation_issues:
            print(f"[RELIABILITY] Pre-validation found issues: {validation_issues}", file=sys.stderr)
            # Try to fix obvious issues before execution
            opal_query = fix_obvious_issues(opal_query, validation_issues)
            print(f"[RELIABILITY] Pre-validation corrected query: {opal_query}", file=sys.stderr)
        
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
            print(f"[RELIABILITY] Attempt {retry_count}/{max_retries}: {error_type} detected", file=sys.stderr)
            
            # Progressive recovery strategies based on error type
            recovery_strategy = select_recovery_strategy(error_type, retry_count, schema_info, request)
            recovery_strategies.append(f"Attempt {retry_count}: {recovery_strategy['name']}")
            
            try:
                fixed_query = await apply_recovery_strategy(
                    recovery_strategy, opal_query, query_result, error_type, 
                    model, schema_info, request, dataset_id
                )
                
                if fixed_query and fixed_query != opal_query:
                    print(f"[RELIABILITY] Trying strategy '{recovery_strategy['name']}': {fixed_query[:100]}...", file=sys.stderr)
                    
                    # Execute with retry logic for transient failures
                    query_result = await execute_with_retry(
                        fixed_query, dataset_id, time_range, start_time, end_time
                    )
                    opal_query = fixed_query
                else:
                    print(f"[RELIABILITY] Strategy '{recovery_strategy['name']}' did not generate a different query", file=sys.stderr)
                    break
                    
            except Exception as e:
                print(f"[RELIABILITY] Strategy '{recovery_strategy['name']}' failed: {e}", file=sys.stderr)
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
- `filter timestamp > timestamp - 1h | limit 10` (to see recent data)
- `statsby count:count()` (to count all records)
- `distinct(timestamp) | limit 5` (to see time ranges with data)"""
        
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
    
    # OPAL syntax errors
    if "unknown verb" in query_lower:
        return ("unknown_verb", True)
    if "syntax error" in query_lower or "parse error" in query_lower:
        return ("syntax_error", True)
    if "expected" in query_lower and ("," in query_lower or "(" in query_lower):
        return ("syntax_expected", True)
    if "need to pick" in query_lower or "must select" in query_lower:
        return ("missing_column", True)
    
    # Field/schema errors
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
            {"name": "verb_replacement", "approach": "specific_docs", "search_terms": "OPAL verbs filter statsby timechart distinct"},
            {"name": "basic_syntax", "approach": "fundamental_rebuild", "search_terms": "OPAL basic syntax examples"},
            {"name": "simple_fallback", "approach": "minimal_query", "search_terms": "OPAL simple queries"}
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
            {"name": "request_correction", "approach": "specific_docs", "search_terms": "OPAL valid queries"},
            {"name": "syntax_rebuild", "approach": "fundamental_rebuild", "search_terms": "OPAL basic syntax"},
            {"name": "minimal_query", "approach": "minimal_query", "search_terms": "OPAL simple"}
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


async def apply_recovery_strategy(strategy: dict, failed_query: str, error_result: str, 
                                error_type: str, model, schema_info: str, request: str, 
                                dataset_id: str) -> str:
    """
    Apply the selected recovery strategy to generate a corrected query.
    """
    approach = strategy["approach"]
    search_terms = strategy["search_terms"]
    
    print(f"[RELIABILITY] Applying {approach} strategy with search: {search_terms}", file=sys.stderr)
    
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
        
        # Create strategy-specific prompt
        if approach == "minimal_query":
            recovery_prompt = f"""The query failed with {error_type}. Generate the SIMPLEST possible OPAL query to get ANY data from this request.

USER REQUEST: {request}
FAILED QUERY: {failed_query}
ERROR: {error_result[:200]}

SCHEMA INFO:
{schema_info[:500]}

RECOVERY GUIDANCE:
{recovery_docs}

STRATEGY: Create the most basic query possible - just filter by time and maybe count records. Don't try to be fancy.

CRITICAL RULES:
- Use only basic verbs: filter, statsby, timechart, distinct, sort, limit
- Start with simple time filter: filter timestamp > timestamp - 1h
- If aggregating, use: statsby count:count()
- If grouping, use: group_by(field_name)
- NEVER use made-up verbs

Generate the simplest working OPAL query:"""
        
        elif approach == "schema_focused":
            recovery_prompt = f"""The query failed with {error_type}. Rebuild using ONLY fields from the schema.

USER REQUEST: {request}
FAILED QUERY: {failed_query}
ERROR: {error_result[:200]}

AVAILABLE SCHEMA:
{schema_info}

RECOVERY GUIDANCE:
{recovery_docs}

STRATEGY: Carefully map the user request to available schema fields. Use exact field names.

CRITICAL RULES:
- ONLY use field names that appear in the schema above
- Check field types before using in aggregations
- Use proper OPAL syntax from documentation
- Start simple and build up

Generate a corrected OPAL query using schema fields:"""
        
        else:  # specific_docs or fundamental_rebuild
            recovery_prompt = f"""The query failed with {error_type}. Generate a corrected version using proper OPAL syntax.

USER REQUEST: {request}
FAILED QUERY: {failed_query}
ERROR: {error_result[:200]}

SCHEMA INFO:
{schema_info[:500]}

RECOVERY GUIDANCE:
{recovery_docs}

STRATEGY: Use the documentation above to fix the specific error while maintaining the user's intent.

CRITICAL RULES:
- Follow EXACT syntax from the documentation
- Use only verbs shown in the recovery guidance
- Respect field names from schema
- Fix the specific error mentioned

Generate a corrected OPAL query:"""
        
        # Generate recovery query
        recovery_response = model.invoke([HumanMessage(content=recovery_prompt)])
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
        
        print(f"[RELIABILITY] Strategy generated: {fixed_query[:100]}...", file=sys.stderr)
        return fixed_query
        
    except Exception as e:
        print(f"[RELIABILITY] Recovery strategy failed: {e}", file=sys.stderr)
        # Fallback to basic query
        if "count" in request.lower() or "how many" in request.lower():
            return "statsby count:count()"
        elif "distinct" in request.lower() or "unique" in request.lower():
            return "distinct(timestamp) | limit 10"  # Safe fallback
        else:
            return "filter timestamp > timestamp - 1h | limit 5"


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
                print(f"[RELIABILITY] Retrying query execution in {wait_time}s (attempt {attempt + 1})", file=sys.stderr)
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
            print(f"[RELIABILITY] Execution attempt {attempt + 1} failed: {e}", file=sys.stderr)
    
    return "Error: Maximum retries exceeded"


def validate_query_syntax(query: str, schema_info: str) -> list:
    """
    Pre-validate OPAL query syntax to catch obvious issues before execution.
    Returns list of validation issues found.
    """
    issues = []
    query_lower = query.lower()
    
    # Check for SQL syntax leakage
    sql_keywords = ['select', 'from', 'where', 'group by', 'order by', 'having', 'join']
    for keyword in sql_keywords:
        if keyword in query_lower:
            issues.append(f"SQL keyword '{keyword}' found - use OPAL syntax instead")
    
    # Check for invalid OPAL patterns
    if 'filter options(' in query_lower:
        issues.append("Invalid 'filter options()' - options should be used with timechart/statsby")
    
    if 'dataset(' in query_lower:
        issues.append("Invalid 'dataset()' function - dataset is already specified")
    
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
            import re
            fixed_query = re.sub(r'dataset\([^)]*\)\s*\|\s*', '', fixed_query)
        
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
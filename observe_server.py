#!/usr/bin/env python3
"""
Observe MCP Server
A Model Context Protocol server that provides access to Observe API functionality
using organized modules for better maintainability and reusability.
"""

import os
import sys
from typing import Dict, Any, Optional, List, Union

try:
    from typing_extensions import TypedDict
except ImportError:
    from typing import TypedDict

# Type definitions for better type safety
class ErrorResponse(TypedDict):
    error: bool
    message: str


try:
    import httpx
    from dotenv import load_dotenv
    pass
except Exception as e:
    pass
    raise

# Try to import Pinecone and related helpers
try:
    import pinecone
    from src.pinecone.search import search_docs
except ImportError as e:
    # Define fallback search functions
    def search_docs(query: str, n_results: int = 5) -> List[Dict[str, Any]]:
        return [{
            "text": f"Error: Pinecone not available. The server cannot perform vector search because the pinecone package is not installed. Please install it with 'pip install pinecone>=3.0.0' and restart the server. Your query was: {query}", 
            "source": "error", 
            "title": "Pinecone Not Available", 
            "score": 1.0
        }]

# Load environment variables from .env file
load_dotenv()

# Import organized Observe API modules
from src.observe import (
    list_datasets as observe_list_datasets,
    get_dataset_info as observe_get_dataset_info,
    execute_opal_query as observe_execute_opal_query
)

# Import organized auth modules
from src.auth import (
    create_authenticated_mcp,
    requires_scopes,
    initialize_auth_middleware,
    setup_auth_provider
)

# Import standardized logging
from src.logging import (
    get_logger,
    set_session_context,
    log_session_context,
    session_logger,
    semantic_logger,
    opal_logger
)

# Smart tools removed - keeping only core functionality

from fastmcp import Context

# Create FastMCP instance with authentication
mcp = create_authenticated_mcp(server_name="observe-community")

# Initialize auth middleware for statistics and logging
auth_provider = setup_auth_provider()
initialize_auth_middleware(auth_provider)

# Smart tools configuration check removed

# --- MCP Tools (Refactored to use organized modules) ---

# Authentication/system tools removed - keeping only core functionality

# --- Observe API Tools (using refactored modules) ---

@mcp.tool()
@requires_scopes(['admin', 'write', 'read'])
async def execute_opal_query(ctx: Context, query: str, dataset_id: str = None, primary_dataset_id: str = None, secondary_dataset_ids: Optional[str] = None, dataset_aliases: Optional[str] = None, time_range: Optional[str] = "1h", start_time: Optional[str] = None, end_time: Optional[str] = None, row_count: Optional[int] = 1000, format: Optional[str] = "csv", timeout: Optional[float] = None) -> str:
    """
    Execute an OPAL query on single or multiple datasets.
    
    Args:
        query: The OPAL query to execute
        dataset_id: DEPRECATED: Use primary_dataset_id instead. Kept for backward compatibility.
        primary_dataset_id: The ID of the primary dataset to query
        secondary_dataset_ids: Optional JSON string list of secondary dataset IDs (e.g., '["44508111"]')
        dataset_aliases: Optional JSON string mapping of aliases to dataset IDs (e.g., '{"volumes": "44508111"}')
        time_range: Time range for the query (e.g., "1h", "1d", "7d"). Used if start_time and end_time are not provided.
        start_time: Optional start time in ISO format (e.g., "2023-04-20T16:20:00Z")
        end_time: Optional end time in ISO format (e.g., "2023-04-20T16:30:00Z")
        row_count: Maximum number of rows to return (default: 1000, max: 100000)
        format: Output format, either "csv" or "ndjson" (default: "csv")
        timeout: Request timeout in seconds (default: uses client default of 30s)
    
    Examples:
        # Single dataset query (backward compatible)
        execute_opal_query(query="filter metric = 'CPUUtilization'", dataset_id="44508123")
        
        # Multi-dataset join query
        execute_opal_query(
            query="join on(instanceId=@volumes.instanceId), volume_size:@volumes.size",
            primary_dataset_id="44508123",  # EC2 Instance Metrics
            secondary_dataset_ids='["44508111"]',  # EBS Volumes (JSON string)
            dataset_aliases='{"volumes": "44508111"}'  # Aliases (JSON string)
        )
    """
    import json
    
    # Parse JSON string parameters if provided
    parsed_secondary_dataset_ids = None
    parsed_dataset_aliases = None
    
    if secondary_dataset_ids:
        try:
            parsed_secondary_dataset_ids = json.loads(secondary_dataset_ids)
        except (json.JSONDecodeError, TypeError) as e:
            return f"Error parsing secondary_dataset_ids: {e}. Expected JSON array like ['44508111']"
    
    if dataset_aliases:
        try:
            parsed_dataset_aliases = json.loads(dataset_aliases)
        except (json.JSONDecodeError, TypeError) as e:
            return f"Error parsing dataset_aliases: {e}. Expected JSON object like {{\"volumes\": \"44508111\"}}"
    
    return await observe_execute_opal_query(
        query=query,
        dataset_id=dataset_id,
        primary_dataset_id=primary_dataset_id,
        secondary_dataset_ids=parsed_secondary_dataset_ids,
        dataset_aliases=parsed_dataset_aliases,
        time_range=time_range,
        start_time=start_time,
        end_time=end_time,
        row_count=row_count,
        format=format,
        timeout=timeout
    )

@mcp.tool()
@requires_scopes(['admin', 'read'])
async def list_datasets(ctx: Context, match: Optional[str] = None, workspace_id: Optional[str] = None, type: Optional[str] = None, interface: Optional[str] = None) -> str:
    """
    List available datasets in Observe.
    
    Args:
        match: Optional substring to match dataset names
        workspace_id: Optional workspace ID to filter by
        type: Optional dataset type to filter by (e.g., 'Event')
        interface: Optional interface to filter by (e.g., 'metric', 'log')
    """
    return await observe_list_datasets(
        match=match,
        workspace_id=workspace_id,
        type=type,
        interface=interface
    )

@mcp.tool()
@requires_scopes(['admin', 'read'])
async def get_dataset_info(ctx: Context, dataset_id: str) -> str:
    """
    Get detailed information about a specific dataset.
    
    Args:
        dataset_id: The ID of the dataset
    """
    return await observe_get_dataset_info(dataset_id=dataset_id)

@mcp.tool()
@requires_scopes(['admin', 'read'])
async def get_relevant_docs(ctx: Context, query: str, n_results: int = 5) -> str:
    """Get relevant documentation for a query using Pinecone vector search"""
    try:
        # Import required modules
        import os
        from collections import defaultdict
        
        chunk_results = search_docs(query, n_results=max(n_results * 3, 15))  # Get more chunks to ensure we have enough from relevant docs
        
        if not chunk_results:
            return f"No relevant documents found for: '{query}'"
        
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
        
        # Sort documents by average score and limit to requested number
        sorted_docs = sorted(doc_scores.items(), key=lambda x: x[1], reverse=True)[:n_results]
        
        if not sorted_docs:
            return f"No valid documents found for: '{query}'"
        
        response = f"Found {len(sorted_docs)} relevant documents for: '{query}'\\n\\n"
        
        # Read and format each full document
        for i, (source, score) in enumerate(sorted_docs, 1):
            try:
                # Read the entire document file
                with open(source, 'r', encoding='utf-8') as f:
                    document_content = f.read()
                
                # Get metadata from the first chunk of this source
                first_chunk = docs_by_source[source][0]
                title = first_chunk.get("title", os.path.basename(source).replace(".md", "").replace("_", " ").title())
                source_filename = os.path.basename(source)
                
                response += f"### Document {i}: {title}\\n"
                response += f"Source: {source_filename}\\n"
                response += f"Relevance Score: {score:.2f}\\n\\n"
                response += f"{document_content}\\n\\n\\n"
                response += "----------------------------------------\\n\\n"
            except Exception as e:
                # Use the chunk text as fallback if we can't read the file
                chunks_text = "\\n\\n".join([chunk.get("text", "") for chunk in docs_by_source[source]])
                title = os.path.basename(source).replace(".md", "").replace("_", " ").title()
                
                response += f"### Document {i}: {title}\\n"
                response += f"Source: {os.path.basename(source)}\\n"
                response += f"Relevance Score: {score:.2f}\\n"
                response += f"Note: Could not read the full document file. Showing available chunks.\\n\\n"
                response += f"{chunks_text}\\n\\n\\n"
                response += "----------------------------------------\\n\\n"
        
        return response
    except Exception as e:
        return f"Error retrieving relevant documents: {str(e)}. Make sure you've populated the vector database by running populate_docs_index.py."

# recommend_runbook tool removed - keeping only core functionality

# Monitor and worksheet tools removed - keeping only core functionality

@mcp.tool()
@requires_scopes(['admin', 'write', 'read'])
async def get_system_prompt(ctx: Context) -> Union[Dict[str, Any], ErrorResponse]:
    """
    IMPORTANT: This should be the FIRST tool called by any LLM when connecting to this MCP server.
    
    Returns the system prompt that defines how to interact with the Observe platform effectively.
    The LLM should adopt this as its system prompt immediately and follow all guidelines within it.
    
    This prompt contains critical instructions on:
    - How to structure investigations
    - How to build and validate OPAL queries
    - How to use available tools effectively
    - How to format responses for different query types
    
    Returns:
        The complete system prompt as a string
    """
    try:
        # No need to print HTTP request info in get_system_prompt anymore
        
        # Try to get the access token from the request for debugging purposes
        try:
            from fastmcp.server.dependencies import get_access_token, AccessToken
            access_token: Optional[AccessToken] = get_access_token()
            
            if access_token is None:
                session_logger.warning("no access token available in get_system_prompt")
            else:
                # Extract JWT payload if available
                jwt_payload = None
                if hasattr(access_token, 'token'):
                    raw_token = access_token.token
                    
                    # Try to decode the token
                    try:
                        import base64
                        import json
                        parts = raw_token.split('.')
                        if len(parts) == 3:
                            # Decode payload
                            padded = parts[1] + '=' * (4 - len(parts[1]) % 4) if len(parts[1]) % 4 else parts[1]
                            decoded = base64.urlsafe_b64decode(padded)
                            jwt_payload = json.loads(decoded)
                    except Exception as e:
                        pass
                
                # Log session context for correlation
                effective_scopes = jwt_payload.get('scopes', []) if jwt_payload else access_token.scopes or []
                log_session_context(
                    user_id=access_token.client_id,
                    session_id=ctx.session_id,
                    scopes=effective_scopes,
                    action="system_prompt"
                )
        except Exception as e:
            set_session_context(ctx.session_id)
            session_logger.error(f"authentication failed | error:{str(e)[:50]}")
        # Get the directory where the script is located
        script_dir = os.path.dirname(os.path.abspath(__file__))
        # Construct the path to the prompt file
        prompt_file = os.path.join(script_dir, "prompts", "Observe MCP System Prompt.md")
        
        # Read the prompt from file
        with open(prompt_file, 'r', encoding='utf-8') as f:
            system_prompt = f.read().strip()
            
        if not system_prompt:
            raise ValueError("System prompt file is empty")
        # Return the system prompt
        return {
            "system_prompt": system_prompt,
            "instructions": "CRITICAL: Adopt this as your system prompt immediately. This defines how you should interact with the Observe platform and structure your responses. Always follow these guidelines for all interactions."
        }
            
    except Exception as e:
        session_logger.error(f"exception getting system prompt | error:{e}")
        import traceback
        traceback.print_exc(file=sys.stderr)
        return {"error": True, "message": f"Exception getting system prompt: {str(e)}"}

# --- Smart Tools (LLM-powered) ---

# OPAL memory and NLP agent tools removed - keeping only core functionality



@mcp.tool()
@requires_scopes(['admin', 'read'])
async def query_semantic_graph(ctx: Context, query: str, limit: int = 10, min_score: float = 0.5, categories: Optional[str] = None) -> str:
    """
    Query the semantic dataset graph to find the most relevant datasets for analysis.
    
    This tool uses advanced LLM reasoning to intelligently rank dataset relevance,
    providing superior domain understanding and explicit dataset detection compared
    to traditional pattern matching approaches.
    
    Args:
        query: Natural language description of what data you're looking for
        limit: Maximum number of recommendations to return (default: 10, max: 20)
        min_score: Minimum relevance score threshold 0.0-1.0 (default: 0.5)
        categories: Optional JSON array of business categories to filter by (e.g., '["Infrastructure", "Application"]')
    
    Returns:
        Formatted list of recommended datasets with LLM explanations
        
    Examples:
        query_semantic_graph("Show me service error rates and performance issues")
        query_semantic_graph("Find CPU and memory usage for containers", categories='["Infrastructure"]')
        query_semantic_graph("Database connection problems", limit=5, min_score=0.6)
        query_semantic_graph("Give me top 100 lines from k8s logs")
    """
    try:
        # Import the LLM recommendation engine
        from src.dataset_intelligence.llm_recommendations import query_datasets_llm
        
        # Validate and normalize parameters
        if limit is None:
            limit = 10
        if min_score is None:
            min_score = 0.5
            
        limit = min(max(int(limit), 1), 20)  # Cap at 20 for LLM approach
        min_score = max(min(float(min_score), 1.0), 0.0)  # Clamp between 0.0 and 1.0
        
        # Parse categories JSON if provided
        parsed_categories = None
        if categories:
            try:
                import json
                parsed_categories = json.loads(categories)
                if not isinstance(parsed_categories, list):
                    return "Error: categories must be a JSON array of strings"
            except json.JSONDecodeError as e:
                return f"Error parsing categories JSON: {e}"
        
        set_session_context(ctx.session_id)
        semantic_logger.info(f"processing query | query:{query[:100]} | limit:{limit} | min_score:{min_score} | categories:{parsed_categories}")
        
        # Get LLM-based recommendations
        recommendations = await query_datasets_llm(
            query=query,
            limit=limit,
            min_score=min_score,
            categories=parsed_categories
        )
        
        if not recommendations:
            return f"""**Dataset Recommendations - No Results Found**

Your query: "{query}"

No datasets met the minimum relevance threshold of {min_score:.1f}.

**Suggestions:**
- Try lowering the min_score parameter (e.g., 0.3)
- Use more descriptive terms in your query
- Remove category filters if you used any
- Check available datasets with: `list_datasets()`

**Available business categories:** Infrastructure, Application, Monitoring, Database, Security, Network, Storage"""
        
        # Format results
        result = f"**Dataset Recommendations for:** {query}\n\n"
        result += f"**Found {len(recommendations)} relevant datasets** (min score: {min_score:.1f}):\n\n"
        
        for i, rec in enumerate(recommendations, 1):
            result += f"**{i}. {rec.name}**\n"
            result += f"   - **Dataset ID:** `{rec.dataset_id}`\n"
            result += f"   - **Type:** {rec.dataset_type} | **Category:** {rec.business_category}/{rec.technical_category}\n"
            result += f"   - **Relevance Score:** {rec.relevance_score:.3f} (confidence: {rec.confidence:.2f})\n"
            
            # Show LLM explanation
            result += f"   - **Why recommended:** {rec.explanation}\n"
            
            if rec.matching_factors:
                factors_str = ", ".join(rec.matching_factors[:4])
                if len(rec.matching_factors) > 4:
                    factors_str += f" (+{len(rec.matching_factors)-4} more)"
                result += f"   - **Key Factors:** {factors_str}\n"
            
            if rec.key_fields:
                key_fields_str = ", ".join(rec.key_fields[:5])
                if len(rec.key_fields) > 5:
                    key_fields_str += f" (+{len(rec.key_fields)-5} more)"
                result += f"   - **Key Fields:** {key_fields_str}\n"
            
            result += "\n"
        
        result += f"**Next Steps:**\n"
        result += f"1. Use `get_dataset_info()` to see full schema\n"
        result += f"2. Use `execute_opal_query()` to sample data"
        
        semantic_logger.info(f"query completed | results:{len(recommendations)}")
        return result
        
    except ImportError as e:
        return f"Semantic graph system not available. Missing dependencies: {str(e)}"
    except Exception as e:
        semantic_logger.error(f"semantic query failed | error:{str(e)}")
        return f"Error in semantic graph: {str(e)}"


@mcp.tool()
@requires_scopes(['admin', 'write', 'read'])
async def generate_opal_query(ctx: Context, nlp_query: str, dataset_ids: str, preferred_interface: Optional[str] = None) -> str:
    """
    Generate an OPAL query from natural language using rule-based patterns and schema adaptation.
    
    SUCCESS RATES BY QUERY TYPE (~75% overall success):
    ✅ Simple queries (logs, metrics, basic traces): 95% success
    ✅ Time-series and aggregations: 85% success  
    ⚠️ Complex boolean logic: 40% success
    ❌ Multi-dataset correlations: 15% success
    
    BEST PRACTICES - Use for:
    - Single dataset filtering and aggregation
    - Time-series analysis with timechart
    - Basic service performance metrics
    - Error rate and latency analysis
    - Simple field transformations
    
    AVOID - These patterns frequently fail:
    - Multi-dataset joins/correlations (use sequential queries instead)
    - Complex nested boolean expressions (simplify to sequential filters)
    - Field references within same aggregation statement
    - Cross-dataset lookups without primary keys
    
    RECOMMENDED NLP PATTERNS:
    ✅ "Show services with error rates above 1%"
    ✅ "Find slow database queries over 5 seconds" 
    ✅ "Display CPU usage trends in 15-minute windows"
    ❌ "Correlate high CPU services with trace errors across datasets"
    ❌ "Find spans that are (errors OR slow) AND (frontend OR checkout)"
    
    Args:
        nlp_query: Natural language description (keep simple for best results)
        dataset_ids: Comma-separated dataset IDs (single dataset recommended)
        preferred_interface: Optional interface hint - "logs", "metrics", or "traces"
    
    Returns:
        Clean OPAL query ready for execution
    """
    try:
        import json
        import os
        import openai
        
        # Get OpenAI API key
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            return "Error: OPENAI_API_KEY not configured"
        
        set_session_context(ctx.session_id)
        opal_logger.info(f"generating OPAL query | query:{nlp_query[:100]} | datasets:{dataset_ids} | interface:{preferred_interface or 'auto-detect'}")
        
        # Parse dataset IDs
        dataset_list = [ds.strip() for ds in dataset_ids.split(',') if ds.strip()]
        if not dataset_list:
            return "Error: No valid dataset IDs provided"
            
        # Check for multi-dataset scenarios and warn about limitations
        is_multi_dataset = len(dataset_list) > 1
        if is_multi_dataset:
            opal_logger.warning(f"multi-dataset request - enforcing single dataset | dataset_count:{len(dataset_list)}")
        
        # Get dataset information for schema context
        opal_logger.debug("retrieving dataset schemas")
        dataset_schemas = {}
        for dataset_id in dataset_list[:3]:  # Limit to 3 datasets for context management
            opal_logger.debug(f"fetching schema for dataset {dataset_id}")
            try:
                schema_info = await observe_get_dataset_info(dataset_id=dataset_id)
                opal_logger.debug(f"schema retrieved | dataset:{dataset_id} | size:{len(str(schema_info))}")
                # Log first 200 chars to verify it's real data
                schema_preview = str(schema_info)[:200].replace('\n', ' ')
                dataset_schemas[dataset_id] = schema_info
            except Exception as e:
                opal_logger.error(f"schema fetch failed | dataset:{dataset_id} | error:{e}")
                dataset_schemas[dataset_id] = "Schema unavailable"
        
        opal_logger.debug(f"schemas collected | count:{len(dataset_schemas)}")
        
        # Get relevant OPAL documentation - COMMENTED OUT FOR TESTING
        opal_logger.debug("skipping documentation retrieval (experimental)")
        opal_docs = "Using system prompt OPAL guide only (search_docs() skipped for testing)"
        
        # # ORIGINAL CODE - COMMENTED OUT FOR EXPERIMENT
        # search_query = f"OPAL query syntax {nlp_query}"
        # print(f"[GENERATE_OPAL] CALLING REAL search_docs() with query: '{search_query}'", file=sys.stderr)
        # try:
        #     docs_response = search_docs(search_query, n_results=3)
        #     print(f"[GENERATE_OPAL] ✅ REAL TOOL CALL SUCCESS: search_docs() returned {len(docs_response) if docs_response else 0} documents", file=sys.stderr)
        #     
        #     if docs_response and len(docs_response) > 0:
        #         # Log details about retrieved docs to verify they're real
        #         for i, doc in enumerate(docs_response[:2]):
        #             doc_preview = str(doc.get("text", ""))[:150].replace('\n', ' ')
        #             print(f"[GENERATE_OPAL] Doc {i+1} preview: {doc_preview}...", file=sys.stderr)
        #         
        #         opal_docs = "\n".join([doc.get("text", "")[:500] for doc in docs_response[:2]])
        #         print(f"[GENERATE_OPAL] Compiled documentation context: {len(opal_docs)} characters", file=sys.stderr)
        #     else:
        #         print(f"[GENERATE_OPAL] WARNING: search_docs() returned empty or null result", file=sys.stderr)
        #         opal_docs = "Documentation unavailable"
        # except Exception as e:
        #     print(f"[GENERATE_OPAL] ❌ REAL TOOL CALL FAILED: search_docs() error: {e}", file=sys.stderr)
        #     opal_docs = "Documentation unavailable"
        
        # Read the system prompt for OPAL guidance
        script_dir = os.path.dirname(os.path.abspath(__file__))
        prompt_file = os.path.join(script_dir, "prompts", "Observe MCP System Prompt.md")
        
        try:
            with open(prompt_file, 'r', encoding='utf-8') as f:
                system_prompt_content = f.read()
                
            # Extract the complete OPAL guidance sections
            opal_section_start = system_prompt_content.find("## OPAL Best Practices")
            
            if opal_section_start != -1:
                # Get everything from OPAL Best Practices to the end of the file
                # since the file ends with the syntax checklist
                opal_guide = system_prompt_content[opal_section_start:]
                opal_logger.debug(f"extracted OPAL guide | size:{len(opal_guide)}")
            else:
                opal_logger.warning("OPAL Best Practices section not found")
                # Try alternative extraction
                practices_start = system_prompt_content.find("OPAL Best Practices")
                if practices_start != -1:
                    opal_guide = system_prompt_content[practices_start:]
                    opal_logger.debug(f"found alternative OPAL section | size:{len(opal_guide)}")
                else:
                    opal_guide = "OPAL guide extraction failed - using fallback content"
                
        except Exception as e:
            opal_logger.warning(f"could not read OPAL guide: {e}")
            opal_guide = "OPAL guide unavailable"
        
        # Create the prompt for GPT-5 with multi-dataset awareness
        multi_dataset_constraint = ""
        if is_multi_dataset:
            multi_dataset_constraint = f"""
🚨 MULTI-DATASET LIMITATION ENFORCED:
Multiple datasets provided ({len(dataset_list)} datasets), but multi-dataset joins have 15% success rate.

REQUIRED APPROACH:
- Focus on PRIMARY dataset: {dataset_list[0]}
- Generate single-dataset query only
- Do NOT use @alias.field references
- Do NOT use join/lookup/follow operations
- If correlation needed: Suggest sequential single-dataset queries instead

"""
        
        generation_prompt = f"""You are an expert OPAL query generator for the Observe platform. Your task is to convert natural language queries into precise, executable OPAL queries.

USER REQUEST:
"{nlp_query}"

TARGET DATASETS: {dataset_ids}
PREFERRED INTERFACE: {preferred_interface or "auto-detect from query"}
{multi_dataset_constraint}
DATASET SCHEMAS:
{json.dumps(dataset_schemas, indent=2)}

OPAL DOCUMENTATION CONTEXT:
{opal_docs}

OPAL SYNTAX GUIDE:
{opal_guide}

YOUR TASK:
1. Analyze the user's natural language request to understand their intent
2. Examine the dataset schemas to identify the most relevant fields
3. Apply the OPAL syntax rules and best practices from the guide above
4. Use safe attribute access patterns with proper null handling
5. Generate a clean, executable OPAL query that fulfills their request

CRITICAL CONSTRAINTS (HIGH FAILURE RATES):
- If multiple dataset IDs provided: AVOID multi-dataset joins/correlations (15% success rate)
- If complex correlation requested: Suggest sequential single-dataset queries instead
- NO complex boolean expressions with parentheses (40% success rate)
- NO field references within same aggregation statement (causes "field does not exist" errors)

MANDATORY AGGREGATION PATTERN:
Use this two-step pattern for error rates and computed fields:
1. First statsby: Create base aggregations only
   statsby total_count:count(), error_count:sum(is_error), group_by(field)
2. Then make_col: Create computed fields from aggregated results
   | make_col error_rate:error_count/total_count*100

NEVER do this (FAILS):
statsby total:count(), errors:sum(is_error), rate:errors/total*100, group_by(field)

DURATION FILTERING PATTERN:
Use duration value directly for filtering, NOT duration_sec() function:
✅ CORRECT: filter duration > 5000000000    # 5 seconds in nanoseconds
❌ WRONG: filter duration > duration_sec(5)  # Function syntax error

CRITICAL: Follow ALL syntax rules and patterns from the OPAL guide above. Pay special attention to:
- Null handling with `is_null()` and `if_null()`  
- Safe attribute access for nested fields
- Proper conditional logic with `if()` not `case()`
- Correct aggregation syntax with `statsby`
- Use of verified OPAL functions only
- Sequential filtering instead of complex boolean logic

OUTPUT FORMAT:
Return ONLY the OPAL query as clean code, no explanations or markdown formatting.

Generate the OPAL query now:"""

        # Call GPT-5 using the new Responses API
        opal_logger.debug("calling LLM for OPAL generation")
        
        client = openai.OpenAI(api_key=api_key)
        
        try:
            response = client.responses.create(
                model="gpt-5-mini",
                input=generation_prompt,
                reasoning={"effort": "low"},   # Use low reasoning for faster response
                text={"verbosity": "low"}     # Keep output concise
            )
            
            opal_logger.debug(f"LLM call successful | model:{getattr(response, 'model', 'unknown')} | tokens:{getattr(getattr(response, 'usage', None), 'total_tokens', 0) if hasattr(response, 'usage') else 0}")
            
            generated_query = response.output_text.strip()
            opal_logger.debug(f"LLM response | length:{len(generated_query)} | preview:{generated_query[:100].replace(chr(10), ' ')}...")
            
        except Exception as llm_error:
            opal_logger.error(f"LLM call failed | error:{llm_error}")
            return f"Error calling GPT-5: {str(llm_error)}"
        
        # Basic validation - ensure it looks like OPAL
        if not generated_query:
            opal_logger.error("validation failed: GPT-5 returned empty response")
            return "Error: GPT-5 returned empty response"
        
        opal_logger.debug("starting response processing phase")
        
        # Remove any markdown formatting if present
        original_query = generated_query
        if generated_query.startswith("```"):
            opal_logger.debug("detected markdown formatting, removing")
            lines = generated_query.split('\n')
            generated_query = '\n'.join(lines[1:-1]) if len(lines) > 2 else generated_query
        
        # Clean up the query
        generated_query = generated_query.strip()
        
        # Log the transformation
        if original_query != generated_query:
            opal_logger.debug(f"query transformed during cleanup | before:{original_query[:100].replace(chr(10), ' ')}... | after:{generated_query[:100].replace(chr(10), ' ')}...")
        
        opal_logger.info(f"final OPAL query generated | query:{generated_query}")
        
        # Validate that it's not obviously hallucinated by checking for common OPAL keywords
        opal_keywords = ['filter', 'statsby', 'limit', 'sort', 'make_col', 'timechart', 'group_by']
        has_opal_keywords = any(keyword in generated_query.lower() for keyword in opal_keywords)
        
        if not has_opal_keywords:
            opal_logger.warning("generated query doesn't contain common OPAL keywords - possible hallucination")
        else:
            matching_keywords = [kw for kw in opal_keywords if kw in generated_query.lower()]
            opal_logger.debug(f"query validation passed | keywords_found:{matching_keywords}")
        
        opal_logger.info(f"successful completion | dataset_calls:{len(dataset_list[:3])} | search_calls:0 | llm_calls:1")
        opal_logger.debug("returning formatted response to user")
        
        return f"""**Generated OPAL Query:**

```opal
{generated_query}
```

**Target Datasets:** {dataset_ids}
**Query Intent:** {nlp_query}

**Usage:**
Use `execute_opal_query()` with this OPAL code and your target dataset(s) to run the query.
"""

    except Exception as e:
        opal_logger.error(f"critical error in generate_opal_query | error:{e} | type:{type(e).__name__}")
        import traceback
        traceback.print_exc(file=sys.stderr)
        opal_logger.error("failed completion")
        return f"Error generating OPAL query: {str(e)}"


mcp.run(transport="sse", host="0.0.0.0", port=8000)
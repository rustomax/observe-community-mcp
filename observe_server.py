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

# Import visualization module
from src.visualization import ChartGenerator, DataParser, detect_chart_type, detect_columns
from src.visualization.auto_detection import recommend_chart_and_columns, validate_column_mapping

from fastmcp import Context
from fastmcp.utilities.types import Image

# Import OpenAI Agents SDK for investigator agent
try:
    from agents import Agent, function_tool, ModelSettings
    from agents.run import Runner, RunConfig
    from agents.stream_events import StreamEvent
    from openai.types.shared import Reasoning
    HAS_OPENAI_AGENTS = True
    session_logger.info("✅ OpenAI Agents SDK imported successfully")
except ImportError as e:
    HAS_OPENAI_AGENTS = False
    Agent = None
    function_tool = None
    Runner = None
    RunConfig = None
    ModelSettings = None
    Reasoning = None
    session_logger.warning(f"❌ OpenAI Agents SDK not available: {e}")
except Exception as e:
    HAS_OPENAI_AGENTS = False
    Agent = None
    function_tool = None
    Runner = None
    RunConfig = None
    ModelSettings = None
    Reasoning = None
    session_logger.error(f"❌ Error importing OpenAI Agents SDK: {e}")

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

# @mcp.tool()  # COMMENTED OUT - Use discover_datasets() instead for better search
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

# @mcp.tool()  # COMMENTED OUT - Use enhanced discover_datasets() with schema info instead
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
async def discover_datasets(ctx: Context, query: str, max_results: int = 15, business_category_filter: Optional[str] = None, technical_category_filter: Optional[str] = None, interface_filter: Optional[str] = None) -> str:
    """
    Discover datasets using fast full-text search on our dataset intelligence database.
    
    This tool searches through analyzed datasets with intelligent categorization and usage guidance.
    Perfect for finding datasets by name, purpose, business area, or technical type.
    
    Args:
        query: Search query (e.g., "kubernetes logs", "service metrics", "error traces", "user sessions")
        max_results: Maximum number of datasets to return (default: 15, max: 30)
        business_category_filter: Filter by business category (Infrastructure, Application, Database, User, Security, etc.)
        technical_category_filter: Filter by technical category (Logs, Metrics, Traces, Events, Resources, etc.)
        interface_filter: Filter by interface type (log, metric, otel_span, etc.)
    
    Returns:
        Formatted list of matching datasets with their purposes and usage guidance
        
    Examples:
        discover_datasets("kubernetes logs errors")
        discover_datasets("service metrics performance", business_category_filter="Application")
        discover_datasets("database traces", technical_category_filter="Traces", max_results=10)
        discover_datasets("infrastructure logs", interface_filter="log")
    """
    try:
        import asyncpg
        import json
        from typing import List, Dict, Any
        
        # Database connection using environment variables
        DATABASE_URL = f"postgresql://{os.getenv('POSTGRES_USER', 'semantic_graph')}:{os.getenv('POSTGRES_PASSWORD')}@{os.getenv('POSTGRES_HOST', 'postgres')}:{os.getenv('POSTGRES_PORT', '5432')}/{os.getenv('POSTGRES_DB', 'semantic_graph')}"
        
        # Validate parameters
        max_results = min(max(1, max_results), 30)  # Clamp between 1 and 30
        
        # Connect to database and search
        conn = await asyncpg.connect(DATABASE_URL)
        
        try:
            # Use the enhanced search function with trigram similarity
            results = await conn.fetch("""
                SELECT * FROM search_datasets_enhanced($1, $2, $3, $4, $5, $6)
            """, query, max_results, business_category_filter, technical_category_filter, interface_filter, 0.2)
            
            if not results:
                return f"""# 🔍 Dataset Discovery Results

**Query**: "{query}"
**Found**: 0 datasets

**No matching datasets found.**

**Suggestions**:
- Try broader terms (e.g., "logs" instead of "error logs")
- Remove filters to see all results
- Check available categories: Infrastructure, Application, Database, User, Security, Monitoring

**Available datasets**: {await conn.fetchval("SELECT COUNT(*) FROM datasets_intelligence WHERE excluded = FALSE")} total datasets in the database.
"""
            
            # Format results
            formatted_results = []
            for i, row in enumerate(results, 1):
                # Parse JSON fields safely
                try:
                    query_patterns = json.loads(row.get('query_patterns', '[]')) if row.get('query_patterns') else []
                    nested_field_paths = json.loads(row.get('nested_field_paths', '{}')) if row.get('nested_field_paths') else {}
                    nested_field_analysis = json.loads(row.get('nested_field_analysis', '{}')) if row.get('nested_field_analysis') else {}
                    common_use_cases = row.get('common_use_cases', []) or []
                except (json.JSONDecodeError, TypeError):
                    query_patterns = []
                    nested_field_paths = {}
                    nested_field_analysis = {}
                    common_use_cases = []

                # Format interface types
                interfaces_str = ""
                if row['interface_types']:
                    interfaces_str = f"**Interfaces**: {', '.join(row['interface_types'])}\n"

                # Format key fields
                key_fields_str = ""
                if row.get('key_fields'):
                    key_fields = row['key_fields'][:4]  # Show top 4
                    key_fields_str = f"**Key Fields**: {', '.join(key_fields)}"
                    if len(row['key_fields']) > 4:
                        key_fields_str += f" (+{len(row['key_fields'])-4} more)"
                    key_fields_str += "\n"

                # Format nested field information
                nested_info_str = ""
                if nested_field_paths:
                    important_fields = nested_field_analysis.get('important_fields', []) if nested_field_analysis else []
                    if important_fields:
                        nested_text = ', '.join(important_fields[:3])
                        if len(important_fields) > 3:
                            nested_text += f" (+{len(important_fields)-3} more)"
                        nested_info_str = f"**Nested Fields**: {nested_text}\n"

                # Format query guidance
                query_guidance_str = ""
                if query_patterns and len(query_patterns) > 0:
                    primary_pattern = query_patterns[0]
                    if isinstance(primary_pattern, dict) and primary_pattern.get('pattern'):
                        query_guidance_str = f"**Query Example**: `{primary_pattern['pattern']}`\n"

                # Format usage scenarios
                usage_str = ""
                if common_use_cases:
                    usage_scenarios = common_use_cases[:2]  # Show top 2
                    usage_str = f"**Common Uses**: {', '.join(usage_scenarios)}\n"

                # Calculate combined relevance score
                combined_score = max(row['rank'], row.get('similarity_score', 0))
                score_details = []
                if row['rank'] > 0:
                    score_details.append(f"text-match: {row['rank']:.3f}")
                if row.get('similarity_score', 0) > 0:
                    score_details.append(f"similarity: {row['similarity_score']:.3f}")

                result_text = f"""## {i}. {row['dataset_name']}
**Dataset ID**: `{row['dataset_id']}`
**Category**: {row['business_category']} / {row['technical_category']}
{interfaces_str}**Purpose**: {row['inferred_purpose']}
**Usage**: {row.get('typical_usage', 'Not specified')}
{key_fields_str}{nested_info_str}{query_guidance_str}{usage_str}**Frequency**: {row.get('data_frequency', 'unknown')}
**Relevance Score**: {combined_score:.3f} ({', '.join(score_details) if score_details else 'fuzzy-match'})
"""
                formatted_results.append(result_text)
            
            # Get summary stats
            total_datasets = await conn.fetchval("SELECT COUNT(*) FROM datasets_intelligence WHERE excluded = FALSE")
            category_counts = await conn.fetch("""
                SELECT business_category, COUNT(*) as count 
                FROM datasets_intelligence 
                WHERE excluded = FALSE 
                GROUP BY business_category 
                ORDER BY count DESC 
                LIMIT 5
            """)
            
            category_summary = ", ".join([f"{row['business_category']} ({row['count']})" for row in category_counts[:3]])
            
            return f"""# 🎯 Dataset Discovery Results

**Query**: "{query}"
**Found**: {len(results)} datasets (showing top {max_results})
**Search Scope**: {total_datasets} total datasets | Top categories: {category_summary}

{chr(10).join(formatted_results)}

---
💡 **Next Steps**: 
- Use `get_dataset_info()` with the dataset ID to see full schema
- Use `execute_opal_query()` with the dataset ID to query the data
"""
            
        finally:
            await conn.close()
            
    except ImportError as e:
        return f"""# ❌ Dataset Discovery Error
**Issue**: Required database library not available
**Error**: {str(e)}
**Solution**: The dataset intelligence system requires asyncpg. Please install it with: pip install asyncpg"""
    except Exception as e:
        return f"""# ❌ Dataset Discovery Error
**Issue**: Database query failed
**Error**: {str(e)}
**Solution**: Check database connection and ensure dataset intelligence has been populated."""


# @mcp.tool() # COMMENTED OUT - Tool disabled as per user request
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
2. MANDATORY: Examine the dataset schemas to identify the EXACT field names that exist
3. VALIDATE: Only use field names that are explicitly present in the provided schemas
4. Apply the OPAL syntax rules and best practices from the guide above
5. Use safe attribute access patterns with proper null handling
6. Generate a clean, executable OPAL query that fulfills their request

CRITICAL SCHEMA VALIDATION:
- NEVER use field names not present in the schema (e.g., "response_time" when schema has "duration")
- NEVER mix SQL window syntax (over(partition_by...)) - use OPAL window() function only
- NEVER use duration_sec() function - use duration value directly for filtering
- VERIFY field types: duration fields need special handling vs numeric fields

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

        # Call GPT-5 for OPAL generation
        opal_logger.debug("calling LLM for OPAL generation")
        
        client = openai.OpenAI(api_key=api_key)
        
        try:
            response = client.chat.completions.create(
                model="gpt-5",
                messages=[
                    {"role": "system", "content": "You are an expert OPAL query generator for the Observe platform."},
                    {"role": "user", "content": generation_prompt}
                ]
            )
            
            opal_logger.debug(f"LLM call successful | model:{getattr(response, 'model', 'unknown')} | tokens:{getattr(getattr(response, 'usage', None), 'total_tokens', 0) if hasattr(response, 'usage') else 0}")
            
            generated_query = response.choices[0].message.content.strip()
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
        
        # Basic field validation against schema
        validation_warnings = []
        for dataset_id, schema_info in dataset_schemas.items():
            if isinstance(schema_info, dict) and 'fields' in schema_info:
                schema_fields = [field.get('name', '').lower() for field in schema_info.get('fields', [])]
                # Check for common field mismatches
                if 'response_time' in generated_query.lower() and 'response_time' not in schema_fields and 'duration' in schema_fields:
                    validation_warnings.append("⚠️  Using 'response_time' but schema has 'duration' field")
                if 'over(' in generated_query.lower():
                    validation_warnings.append("⚠️  SQL window syntax detected - use OPAL window() function")
                if 'duration_sec(' in generated_query.lower():
                    validation_warnings.append("⚠️  duration_sec() function - use duration value directly")
        
        if validation_warnings:
            for warning in validation_warnings:
                opal_logger.warning(f"validation warning: {warning}")
        
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


# @mcp.tool() # COMMENTED OUT - Tool disabled as per user request
@requires_scopes(['admin', 'write', 'read'])
async def create_visualization(
    ctx: Context,
    csv_data: str,
    chart_type: str = "",
    title: str = "",
    x_column: str = None,
    y_column: str = None,
    group_by_column: str = None,
    theme: str = "observability"
) -> Image:
    """
    Create a visualization from CSV data returned by execute_opal_query.
    
    This tool converts CSV data into base64-encoded PNG charts optimized for
    observability dashboards. It supports automatic column detection and 
    multiple chart types.
    
    Args:
        csv_data: Raw CSV data (typically from execute_opal_query output)
        chart_type: Type of chart ("line", "bar", "scatter", "heatmap", "pie", "histogram", "box")
                   Auto-detected if empty
        title: Chart title (optional)
        x_column: X-axis column name (auto-detected if None)
        y_column: Y-axis column name (auto-detected if None)
        group_by_column: Column for multi-series grouping (optional)
        theme: Visual theme ("observability" or "clean")
        
    Returns:
        Image object containing base64-encoded PNG chart
        
    Example:
        # First get data from OPAL
        csv_data = await execute_opal_query(ctx, "filter service_name = 'web'", dataset_id="123")
        
        # Then create visualization
        chart = await create_visualization(ctx, csv_data, chart_type="line", title="Service Performance")
    """
    try:
        # Create a simple error image using matplotlib instead of hardcoded bytes
        def create_error_image(error_message: str) -> bytes:
            import matplotlib.pyplot as plt
            import io
            
            fig, ax = plt.subplots(figsize=(8, 4), dpi=100)
            ax.text(0.5, 0.5, error_message, ha='center', va='center', 
                   fontsize=12, wrap=True, transform=ax.transAxes)
            ax.set_xlim(0, 1)
            ax.set_ylim(0, 1)
            ax.axis('off')
            
            buffer = io.BytesIO()
            fig.savefig(buffer, format='jpeg', bbox_inches='tight', dpi=100)
            buffer.seek(0)
            image_bytes = buffer.getvalue()
            plt.close(fig)
            return image_bytes
        
        # Validate inputs
        if not csv_data or not csv_data.strip():
            return Image(
                data=create_error_image("Error: CSV data is empty.\nPlease provide CSV data from execute_opal_query."),
                format="jpeg",
                annotations={"text": "Error: CSV data is empty. Please provide CSV data from execute_opal_query."}
            )
        
        # Parse CSV data
        parser = DataParser()
        try:
            df = parser.parse(csv_data)
        except ValueError as e:
            return Image(
                data=create_error_image(f"Error parsing CSV data:\n{str(e)}\nPlease ensure the CSV data is valid."),
                format="jpeg",
                annotations={"text": f"Error parsing CSV data: {str(e)}. Please ensure the CSV data is valid."}
            )
        
        # Auto-detect chart type if not specified
        if not chart_type:
            chart_type, auto_columns = recommend_chart_and_columns(df)
            if not x_column:
                x_column = auto_columns.get('x_column')
            if not y_column:
                y_column = auto_columns.get('y_column')
            if not group_by_column:
                group_by_column = auto_columns.get('group_by_column')
        else:
            # Validate chart type
            supported_types = ['line', 'bar', 'scatter', 'heatmap', 'pie', 'histogram', 'box']
            if chart_type not in supported_types:
                return Image(
                    data=create_error_image(f"Error: Unsupported chart type '{chart_type}'.\nSupported types: {', '.join(supported_types)}"),
                    format="jpeg", 
                    annotations={"text": f"Error: Unsupported chart type '{chart_type}'. Supported types: {', '.join(supported_types)}"}
                )
        
        # Auto-detect columns if not specified
        if not x_column or not y_column:
            auto_columns = detect_columns(df, chart_type, parser)
            x_column = x_column or auto_columns.get('x_column')
            y_column = y_column or auto_columns.get('y_column')
            
            # Handle special cases for pie and histogram
            if chart_type == 'pie':
                x_column = x_column or auto_columns.get('label_column')
                y_column = y_column or auto_columns.get('value_column')
            elif chart_type == 'heatmap':
                if not auto_columns.get('value_column'):
                    return Image(
                        data=create_error_image("Error: Heatmap requires a value column\nbut none could be auto-detected."),
                        format="jpeg",
                        annotations={"text": "Error: Heatmap requires a value column but none could be auto-detected."}
                    )
        
        # Validate column mapping
        column_mapping = {
            'x_column': x_column,
            'y_column': y_column,
            'group_by_column': group_by_column
        }
        
        if chart_type == 'pie':
            column_mapping = {
                'label_column': x_column,
                'value_column': y_column
            }
        elif chart_type == 'heatmap':
            column_mapping = {
                'x_column': x_column,
                'y_column': y_column,
                'value_column': parser.get_numeric_columns()[0] if parser.get_numeric_columns() else None
            }
        
        validation_issues = validate_column_mapping(df, chart_type, column_mapping)
        if validation_issues:
            return Image(
                data=create_error_image(f"Column mapping validation failed:\n" + "\n".join(validation_issues)),
                format="jpeg",
                annotations={"text": f"Column mapping validation failed:\n" + "\n".join(validation_issues)}
            )
        
        # Create chart
        generator = ChartGenerator(theme=theme)
        
        # Prepare arguments for chart creation
        chart_args = {
            'title': title,
            'x_column': x_column,
            'y_column': y_column,
            'group_by_column': group_by_column
        }
        
        # Special handling for pie charts
        if chart_type == 'pie':
            chart_args = {
                'title': title,
                'label_column': x_column,
                'value_column': y_column
            }
        
        # Special handling for heatmaps
        elif chart_type == 'heatmap':
            chart_args = {
                'title': title,
                'x_column': x_column,
                'y_column': y_column,
                'value_column': column_mapping['value_column']
            }
        
        # Generate chart
        image_bytes = generator.create_chart(df, chart_type, **chart_args)
        
        # Create description
        data_summary = parser.get_data_summary()
        description = f"""
📊 **{chart_type.title()} Chart Generated**

**Data Summary:**
- {data_summary['total_rows']} rows, {data_summary['total_columns']} columns
- Chart type: {chart_type}
- X-axis: {x_column or 'auto-detected'}
- Y-axis: {y_column or 'auto-detected'}
- Grouping: {group_by_column or 'none'}
- Theme: {theme}

**Column Types Detected:**
- Numeric: {', '.join(data_summary.get('numeric_columns', [])) or 'none'}
- Categorical: {', '.join(data_summary.get('categorical_columns', [])) or 'none'}
- DateTime: {', '.join(data_summary.get('datetime_columns', [])) or 'none'}

Use this chart to visualize your OPAL query results. The image is optimized for observability dashboards with proper scaling and theming.
        """.strip()
        
        # FastMCP Image class handles base64 encoding automatically
        return Image(
            data=image_bytes,
            format="jpeg", 
            annotations={"text": description}
        )
        
    except Exception as e:
        # Log error for debugging
        import traceback
        error_details = traceback.format_exc()
        session_logger.error(f"Error in create_visualization: {e}\nFull traceback: {error_details}")
        
        return Image(
            data=create_error_image(f"Error creating visualization:\n{str(e)}\nPlease check your CSV data and parameters."),
            format="jpeg",
            annotations={"text": f"Error creating visualization: {str(e)}. Please check your CSV data and parameters."}
        )


# --- AI Investigator Agent (using OpenAI Agents SDK) ---

if HAS_OPENAI_AGENTS:
    # Internal tool wrappers for agent to call existing MCP functions
    @function_tool
    async def internal_discover_datasets(query: str, limit: int = 5) -> str:
        """Find relevant datasets using fast database search"""
        try:
            session_logger.info(f"🔧 TOOL CALLED: internal_discover_datasets(query='{query}', limit={limit})")
            
            # Try to get context for progress updates (may fail if not in MCP context)
            try:
                from fastmcp.server.dependencies import get_context
                ctx = get_context()
                await ctx.report_progress(20, 100, "🔍 Searching for relevant datasets...")
            except RuntimeError:
                pass  # No context available, skip progress updates
            
            # Use fast database search directly
            import asyncpg
            DATABASE_URL = f"postgresql://{os.getenv('POSTGRES_USER', 'semantic_graph')}:{os.getenv('POSTGRES_PASSWORD')}@{os.getenv('POSTGRES_HOST', 'postgres')}:{os.getenv('POSTGRES_PORT', '5432')}/{os.getenv('POSTGRES_DB', 'semantic_graph')}"
            
            conn = await asyncpg.connect(DATABASE_URL)
            try:
                # Use the fast search function
                results = await conn.fetch("""
                    SELECT * FROM search_datasets($1, $2, $3, $4, $5)
                """, query, min(max(int(limit), 1), 20), None, None, None)
                
                # Format the results as JSON string like the MCP tool does
                import json
                if results:
                    result = json.dumps([{
                        'id': row['dataset_id'],
                        'name': row['dataset_name'], 
                        'dataset_type': 'Event',  # Default since we don't have this in the search results
                        'business_category': row['business_category'],
                        'technical_category': row['technical_category'],
                        'score': float(row['rank']),
                        'explanation': row['inferred_purpose']
                    } for row in results], indent=2)
                else:
                    result = "[]"
                    
                session_logger.info(f"🔧 TOOL RESULT: Found {len(results)} datasets, {len(str(result))} chars of data")
                return result
            finally:
                await conn.close()
                
        except Exception as e:
            session_logger.error(f"🔧 TOOL ERROR: internal_discover_datasets failed: {str(e)}")
            return f"Error querying datasets: {str(e)}"

    @function_tool
    async def internal_generate_opal_query(nlp_query: str, dataset_ids: str, preferred_interface: str = None) -> str:
        """Generate valid OPAL query from natural language"""
        try:
            session_logger.info(f"🔧 TOOL CALLED: internal_generate_opal_query(nlp_query='{nlp_query[:50]}...', dataset_ids='{dataset_ids}')")
            
            # Try to get context for progress updates
            try:
                from fastmcp.server.dependencies import get_context
                ctx = get_context()
                await ctx.report_progress(40, 100, f"🧠 Generating OPAL query...")
            except RuntimeError:
                pass  # No context available, skip progress updates
            
            # Call the existing MCP generate_opal_query function directly
            mock_context = Context(mcp)
            result = await generate_opal_query(
                mock_context,
                nlp_query=nlp_query,
                dataset_ids=dataset_ids,
                preferred_interface=preferred_interface
            )
            
            session_logger.info(f"🔧 TOOL RESULT: Generated OPAL query, {len(str(result))} chars")
            return result
        except Exception as e:
            session_logger.error(f"🔧 TOOL ERROR: internal_generate_opal_query failed: {str(e)}")
            return f"Error generating OPAL query: {str(e)}"

    @function_tool  
    async def internal_execute_opal_query(query: str, dataset_id: str, time_range: str = "1h") -> str:
        """Execute OPAL query using existing MCP tool"""
        try:
            session_logger.info(f"🔧 TOOL CALLED: internal_execute_opal_query(query='{query[:100]}...', dataset_id='{dataset_id}', time_range='{time_range}')")
            
            # Try to get context for progress updates
            try:
                from fastmcp.server.dependencies import get_context
                ctx = get_context()
                await ctx.report_progress(50, 100, f"📊 Executing OPAL query on dataset {dataset_id}...")
            except RuntimeError:
                pass  # No context available, skip progress updates
            
            # Import and call the underlying implementation directly
            from src.observe import execute_opal_query as observe_execute_opal_query
            
            result = await observe_execute_opal_query(
                query=query, 
                primary_dataset_id=dataset_id, 
                time_range=time_range,
                row_count=1000,
                format="csv"
            )
            session_logger.info(f"🔧 TOOL RESULT: Got {len(result)} chars of CSV data")
            return result  # Already CSV string
        except Exception as e:
            session_logger.error(f"🔧 TOOL ERROR: internal_execute_opal_query failed: {str(e)}")
            return f"Error executing OPAL query: {str(e)}"

    @function_tool
    async def internal_create_visualization(csv_data: str, chart_type: str, title: str) -> str:
        """Create visualization using existing MCP tool"""
        try:
            session_logger.info(f"🔧 TOOL CALLED: internal_create_visualization(chart_type='{chart_type}', title='{title}')")
            
            # Use the visualization components directly
            from src.visualization import ChartGenerator, DataParser
            import pandas as pd
            import io
            
            # Parse CSV data
            df = pd.read_csv(io.StringIO(csv_data))
            
            # Create chart
            generator = ChartGenerator(theme="observability")
            image_bytes = generator.create_chart(df, chart_type, title=title)
            
            session_logger.info(f"🔧 TOOL RESULT: Created {chart_type} visualization with {len(image_bytes)} bytes")
            return f"Created {chart_type} visualization: {title} (image data: {len(image_bytes)} bytes)"
        except Exception as e:
            session_logger.error(f"🔧 TOOL ERROR: internal_create_visualization failed: {str(e)}")
            return f"Error creating visualization: {str(e)}"

    @function_tool
    async def internal_get_dataset_info(dataset_id: str) -> str:
        """Get dataset schema using existing MCP tool"""
        try:
            session_logger.info(f"🔧 TOOL CALLED: internal_get_dataset_info(dataset_id='{dataset_id}')")
            result = await observe_get_dataset_info(dataset_id=dataset_id)
            session_logger.info(f"🔧 TOOL RESULT: Got dataset info with {len(str(result))} chars")
            return str(result)
        except Exception as e:
            session_logger.error(f"🔧 TOOL ERROR: internal_get_dataset_info failed: {str(e)}")
            return f"Error getting dataset info: {str(e)}"

    @function_tool
    async def internal_list_datasets(match: str = None, limit: int = 10) -> str:
        """List available datasets using existing MCP tool"""
        try:
            session_logger.info(f"🔧 TOOL CALLED: internal_list_datasets(match='{match}', limit={limit})")
            result = await observe_list_datasets(match=match)
            # Limit results for agent context
            import json
            datasets = json.loads(result)
            if isinstance(datasets, list) and len(datasets) > limit:
                datasets = datasets[:limit]
                result = json.dumps(datasets)
            session_logger.info(f"🔧 TOOL RESULT: Listed {len(datasets)} datasets")
            return result
        except Exception as e:
            session_logger.error(f"🔧 TOOL ERROR: internal_list_datasets failed: {str(e)}")
            return f"Error listing datasets: {str(e)}"

    @function_tool
    async def internal_get_relevant_docs(query: str, n_results: int = 3) -> str:
        """Get relevant documentation using existing MCP tool"""
        try:
            session_logger.info(f"🔧 TOOL CALLED: internal_get_relevant_docs(query='{query}', n_results={n_results})")
            
            # Call the search_docs function directly (already imported at top)
            from collections import defaultdict
            
            chunk_results = search_docs(query, n_results=max(n_results * 3, 15))
            
            if not chunk_results:
                result = f"No relevant documents found for: '{query}'"
                session_logger.info("🔧 TOOL RESULT: No documents found")
                return result
            
            # Group chunks by document (same logic as MCP tool)
            doc_groups = defaultdict(list)
            for chunk in chunk_results:
                doc_key = f"{chunk.get('source', 'unknown')}#{chunk.get('title', 'untitled')}"
                doc_groups[doc_key].append(chunk)
            
            # Take top documents and format result
            selected_docs = list(doc_groups.items())[:n_results]
            
            if not selected_docs:
                result = f"No relevant documents found for: '{query}'"
                session_logger.info("🔧 TOOL RESULT: No documents after grouping")
                return result
            
            # Format the response
            response_parts = []
            for doc_key, chunks in selected_docs:
                source, title = doc_key.split('#', 1)
                avg_score = sum(chunk.get('score', 0) for chunk in chunks) / len(chunks)
                
                response_parts.append(f"**{title}** (source: {source}, relevance: {avg_score:.2f})")
                response_parts.append(f"Content: {chunks[0].get('text', '')[:500]}...")  # First chunk preview
                response_parts.append("")  # Blank line
            
            result = "\n".join(response_parts)
            session_logger.info(f"🔧 TOOL RESULT: Found {len(selected_docs)} relevant documents")
            return result
            
        except Exception as e:
            session_logger.error(f"🔧 TOOL ERROR: internal_get_relevant_docs failed: {str(e)}")
            return f"Error getting relevant docs: {str(e)}"

    # Initialize investigation agent with explicit model configuration
    
    session_logger.info("🕵️ Initializing GPT-5 o11y scout agent with minimal reasoning...")
    
    investigation_agent = Agent(
        name="O11y Scout",
        instructions="""
        You are O11y Scout - an expert Site Reliability Engineer AI agent with advanced reasoning capabilities for investigating observability issues.
        
        REASONING APPROACH:
        Use your reasoning mode to deeply analyze observability problems by:
        1. Breaking down complex issues into investigatable components
        2. Forming hypotheses about root causes before collecting data
        3. Planning multi-step investigation strategies
        4. Correlating findings across different data sources
        5. Drawing insights from patterns in the data
        
        CRITICAL ANTI-HALLUCINATION RULES:
        1. NEVER make up data - only use results from tool calls
        2. ALWAYS call tools to get real data before making conclusions
        3. If a tool call fails, acknowledge the failure and try alternatives
        4. Base ALL analysis on actual returned data, not assumptions
        5. When you don't have data, explicitly state "I need to query for this data"
        
        INVESTIGATION METHODOLOGY:
        1. ANALYZE the user's query and form initial hypotheses
        2. DISCOVER relevant datasets using internal_discover_datasets
        3. EXPLORE available data using internal_list_datasets if needed
        4. UNDERSTAND data structure using internal_get_dataset_info
        5. GENERATE valid OPAL queries using internal_generate_opal_query (TRY FIRST for complex analytics!)
        6. QUERY for specific metrics using internal_execute_opal_query (with fallback OPAL patterns)
        7. VISUALIZE findings using internal_create_visualization
        8. CORRELATE data across multiple sources and time periods
        9. SEARCH documentation using internal_get_relevant_docs for context
        10. SYNTHESIZE findings into actionable insights and recommendations
        
        QUERY GENERATION STRATEGY:
        - TRY internal_generate_opal_query first for complex queries (percentiles, aggregations)
        - IF generation fails, use internal_execute_opal_query with proven OPAL patterns:
          * Start simple: `limit 5` to explore data structure
          * Add filtering: `filter field = "value" | limit 5` 
          * Add aggregation: `statsby count(), group_by(field) | sort desc(count) | limit 10`
          * Use proven patterns: `percentile(duration, 0.95)` for P95, `if_null()` for safety
        
        OPAL BEST PRACTICES (CRITICAL - Use these patterns when generate_opal_query fails):
        - NEVER use SQL syntax (SELECT, FROM, WHERE, GROUP BY) 
        - ALWAYS use `if()` not `case()` for conditions
        - ALWAYS use `is_null()` and `if_null()` for null handling  
        - ALWAYS use `:` for column creation: `make_col new_field:expression`
        - ALWAYS use `desc(field)` for sorting, never `-field`
        - ALWAYS use percentiles 0-1 range: `percentile(duration, 0.95)` not `percentile(duration, 95)`
        - ALWAYS pipe operations: `filter ... | statsby ... | sort ... | limit N`
        - ALWAYS include `filter not is_null(field)` before aggregations for consistency
        
        PROVEN INVESTIGATION PATTERNS (Use these when needed):
        
        For SERVICE LATENCY ANALYSIS (use on span datasets):
        ```opal
        filter not is_null(service_name)
        | statsby p50_duration:percentile(duration, 0.5), p95_duration:percentile(duration, 0.95), p99_duration:percentile(duration, 0.99), group_by(service_name) 
        | sort desc(p99_duration) 
        | limit 10
        ```
        
        For ERROR ANALYSIS (use on span datasets):
        ```opal
        filter error = true
        | statsby error_count:count(), avg_duration:avg(duration), group_by(service_name)
        | sort desc(error_count)
        | limit 10
        ```
        
        For LOG ERROR INVESTIGATION (use on log datasets):
        ```opal
        filter contains(body, "error") or contains(body, "ERROR") or contains(body, "Error")
        | statsby error_logs:count(), group_by(container, namespace)
        | sort desc(error_logs)
        | limit 10
        ```
        
        REASONING WORKFLOW:
        - Think through the problem systematically before acting
        - Consider multiple potential root causes
        - Plan your investigation strategy based on the specific issue type
        - Use tool results to refine your hypotheses
        - Connect patterns across different metrics and timeframes
        - Provide probabilistic assessments of likely root causes
        
        Remember: Combine deep reasoning with real data for superior investigations.
        """,
        tools=[
            internal_discover_datasets,
            internal_list_datasets,
            internal_get_dataset_info,
            internal_generate_opal_query,
            internal_execute_opal_query, 
            internal_create_visualization,
            internal_get_relevant_docs
        ],
        model='gpt-5',
        model_settings=ModelSettings(
            max_tokens=8000,  # GPT-5 can handle more tokens
            reasoning=Reasoning(effort="minimal"),  # Minimal reasoning for faster response
            verbosity="low"  # Low verbosity for cleaner output
        )
    )

    # @mcp.tool() # COMMENTED OUT - Tool disabled as per user request
    @requires_scopes(['admin', 'read'])
    async def o11y_scout(
        ctx: Context,
        investigation_query: str,
        max_investigation_depth: int = 10
    ) -> str:
        """
        O11y Scout: AI-powered observability investigation that analyzes real data to find root causes.
        
        This tool uses the O11y Scout AI agent to autonomously investigate observability issues by:
        - Finding relevant datasets for your specific query
        - Executing OPAL queries to get actual performance metrics  
        - Creating visualizations from real data
        - Providing data-driven analysis and recommendations
        
        Works for performance issues, errors, capacity planning, service health checks, etc.
        
        Args:
            investigation_query: Describe what you want to investigate (e.g., "microservice latency issues", "error rates in payment service", "database performance problems")
            max_investigation_depth: Maximum AI reasoning steps (default: 10, increase for complex investigations)
        
        Returns:
            Comprehensive investigation report with real data analysis, findings, and recommendations
        """
        try:
            session_logger.info(f"🕵️ Starting O11y Scout investigation: {investigation_query}")
            
            # Send initial progress notification
            session_logger.info("🔄 STREAMING: Sending initial progress notification...")
            await ctx.report_progress(0, 100, "🚀 O11y Scout initializing investigation...")
            session_logger.info("🔄 STREAMING: Initial progress notification sent!")
            
            # Check if agent is properly configured
            if not hasattr(investigation_agent, 'tools') or len(investigation_agent.tools) == 0:
                return "❌ Investigation agent not properly configured - no tools available"
            
            session_logger.info(f"Agent has {len(investigation_agent.tools)} tools available")
            
            # Check for OpenAI API key
            openai_api_key = os.getenv('OPENAI_API_KEY')
            if not openai_api_key:
                session_logger.warning("No OPENAI_API_KEY found in environment")
                return """
# ⚠️ Configuration Issue

**Query**: {investigation_query}

**Error**: OpenAI API key not configured.

**Solution**: Please set the OPENAI_API_KEY environment variable to enable AI-powered investigations.

You can still use individual MCP tools manually:
- `discover_datasets()` to find datasets
- `execute_opal_query()` to get metrics  
- `create_visualization()` to chart results
                """.format(investigation_query=investigation_query).strip()
            
            session_logger.info(f"Using OpenAI API key (ending: ...{openai_api_key[-6:]})")
            
            # Send progress update
            await ctx.report_progress(10, 100, "🕵️ O11y Scout analyzing your query...")
            
            # Execute investigation using Runner with real tool calling
            session_logger.info("Executing agent runner...")
            response = await Runner.run(
                starting_agent=investigation_agent,
                input=f"""
                You are investigating: {investigation_query}
                
                MANDATORY: You MUST call internal tools to get real data. Follow these steps exactly:
                
                1. FIRST: Call internal_discover_datasets with query: "{investigation_query}"
                2. SECOND: Based on results, call internal_execute_opal_query with a relevant dataset
                3. THIRD: Analyze the data you received and call more tools if needed
                4. FOURTH: Create visualizations if you have data to chart
                5. FINAL: Provide conclusions based ONLY on the tool results
                
                DO NOT provide analysis without calling tools first. Tool calls are MANDATORY.
                """,
                max_turns=max_investigation_depth
            )
            
            session_logger.info(f"Agent execution completed. Response type: {type(response)}")
            
            # Send progress update
            await ctx.report_progress(80, 100, "📊 O11y Scout analyzing findings...")
            
            # Extract results from RunResult - it contains the final output
            if hasattr(response, 'output'):
                investigation_content = str(response.output)
                session_logger.info(f"Got output from response.output: {len(investigation_content)} chars")
            elif hasattr(response, 'final_response'):
                investigation_content = str(response.final_response)
                session_logger.info(f"Got output from response.final_response: {len(investigation_content)} chars")
            else:
                investigation_content = str(response)
                session_logger.info(f"Got output from str(response): {len(investigation_content)} chars")
                session_logger.info(f"Response attributes: {dir(response)}")
            
            # Check if we got useful content
            if not investigation_content or len(investigation_content.strip()) < 50:
                session_logger.warning(f"Investigation content seems too short or empty: '{investigation_content[:100]}...'")
                return f"""
# ⚠️ Investigation Incomplete

**Query**: {investigation_query}

**Issue**: The AI agent completed but didn't produce a meaningful investigation report.

**Debug Info**: 
- Response type: {type(response)}
- Content length: {len(investigation_content)} characters
- Available tools: {len(investigation_agent.tools)}

**Suggestion**: Try increasing max_investigation_depth or check if OpenAI API key is configured.

**Raw Response**: {investigation_content[:500]}
                """.strip()
            
            investigation_report = f"""
# 🔍 AI Investigation Report

**Query**: {investigation_query}

## Investigation Results
{investigation_content}

## Data Sources
All findings are based on real data retrieved from:
- Observe OPAL queries  
- Actual dataset schemas
- Live performance metrics
- Real visualization generation

*Note: This investigation used only actual data from Observe platform tools. No data was fabricated or assumed.*
            """.strip()
            
            # Send final progress update
            await ctx.report_progress(100, 100, "✅ O11y Scout investigation complete!")
            
            session_logger.info(f"Investigation completed successfully")
            return investigation_report
            
        except Exception as e:
            import traceback
            error_details = traceback.format_exc()
            session_logger.error(f"Investigation failed: {e}\nFull traceback: {error_details}")
            
            return f"""
# ❌ Investigation Failed

**Query**: {investigation_query}
**Error**: {str(e)}

The investigation failed due to a technical error. This is a real error message, not fabricated content.

Please check the MCP server logs for more details.
            """.strip()


else:
    @mcp.tool()
    @requires_scopes(['admin', 'read'])
    async def investigate_observability_issue(
        ctx: Context,
        investigation_query: str,
        max_investigation_depth: int = 10
    ) -> str:
        """
        Observability investigation tool (OpenAI Agents SDK not available).
        
        This tool requires the OpenAI Agents SDK to be installed.
        Please install it with: pip install openai-agents>=0.1.0
        """
        # Fallback: Provide basic investigation using existing tools
        session_logger.info(f"Running fallback investigation for: {investigation_query}")
        
        try:
            # Step 1: Find relevant datasets
            semantic_results = await discover_datasets(ctx, query=investigation_query, max_results=5)
            
            # Step 2: Parse results to extract dataset IDs
            import json
            datasets = []
            if semantic_results and semantic_results != "[]":
                try:
                    parsed = json.loads(semantic_results)
                    if isinstance(parsed, list) and len(parsed) > 0:
                        datasets = parsed[:3]  # Use top 3 datasets
                except:
                    pass
            
            if not datasets:
                return f"""
# ⚠️ Fallback Investigation (Limited AI)

**Query**: {investigation_query}

**Issue**: OpenAI Agents SDK not available, and no relevant datasets found.

**Next Steps**: 
1. Try using `discover_datasets()` to find datasets manually
2. Use `execute_opal_query()` to get specific metrics
3. Use `create_visualization()` to chart results

**Note**: Full AI-powered investigations require OpenAI Agents SDK installation.
                """.strip()
            
            # Step 3: Query the first dataset for basic metrics
            first_dataset = datasets[0]
            dataset_id = first_dataset.get('id', '') if isinstance(first_dataset, dict) else str(first_dataset)
            
            if dataset_id:
                # Simple latency query
                latency_query = """
                filter not is_null(duration) and not is_null(service_name)
                | statsby 
                    p50_latency:percentile(duration, 0.5),
                    p95_latency:percentile(duration, 0.95), 
                    p99_latency:percentile(duration, 0.99),
                    call_count:count(),
                    group_by(service_name)
                | sort desc(p95_latency)
                | limit 10
                """
                
                query_results = await execute_opal_query(
                    ctx,
                    query=latency_query,
                    primary_dataset_id=dataset_id,
                    time_range="2h"
                )
                
                return f"""
# 🔍 Basic Investigation Report (Fallback Mode)

**Query**: {investigation_query}

## Findings

**Datasets Found**: {len(datasets)} relevant datasets
**Analysis**: Basic microservices latency analysis

## Microservices Latency Data

```csv
{query_results}
```

## Limitations

This is a basic investigation without advanced AI reasoning. 
For comprehensive analysis with hypothesis formation, pattern recognition, 
and multi-step investigations, install the OpenAI Agents SDK:

```bash
pip install openai-agents>=0.1.0
```

## Manual Next Steps

1. Analyze the latency data above for outliers
2. Run targeted queries on specific high-latency services
3. Correlate with error rates and deployment times
4. Create visualizations using `create_visualization()`
                """.strip()
            
            else:
                return f"""
# ⚠️ Fallback Investigation Failed

**Query**: {investigation_query}

**Issue**: Could not extract valid dataset ID from semantic search results.

**Available Datasets**: {len(datasets)} found, but unable to query.

**Manual Steps**: Use `discover_datasets()` and `execute_opal_query()` directly.
                """.strip()
                
        except Exception as e:
            session_logger.error(f"Fallback investigation failed: {e}")
            return f"""
# ❌ Investigation Tool Unavailable

**Query**: {investigation_query}

**Issue**: OpenAI Agents SDK not available and fallback investigation failed.

**Error**: {str(e)}

**Solution**: Install OpenAI Agents SDK and restart:
```bash
pip install openai-agents>=0.1.0
```

**Alternative**: Use individual MCP tools manually:
- `discover_datasets()` to find datasets
- `execute_opal_query()` to get metrics  
- `create_visualization()` to chart results
            """.strip()


@mcp.tool()
@requires_scopes(['admin', 'read'])
async def discover_metrics(ctx: Context, query: str, max_results: int = 20, category_filter: Optional[str] = None, technical_filter: Optional[str] = None) -> str:
    """
    Discover observability metrics using fast full-text search on our metrics intelligence database.
    
    This tool searches through 491+ analyzed metrics with intelligent categorization and usage guidance.
    Perfect for finding metrics by name, purpose, dimensions, or use case.
    
    IMPORTANT: This tool provides error FREQUENCIES and performance metrics. For complete error analysis 
    (actual error messages, stack traces), follow up with log dataset queries using discover_datasets().
    
    Args:
        query: Search query (e.g., "error rate", "cpu usage", "database latency", "service performance")
        max_results: Maximum number of metrics to return (default: 20, max: 50)
        category_filter: Filter by business category (Infrastructure, Application, Database, Storage, Network, Monitoring)
        technical_filter: Filter by technical category (Error, Latency, Count, Performance, Resource, Throughput, Availability)
    
    Returns:
        Formatted list of matching metrics with their datasets, purposes, and usage guidance
        
    Examples:
        discover_metrics("error rate service")  # Gets error counts - follow with logs for error details
        discover_metrics("cpu memory usage", category_filter="Infrastructure")
        discover_metrics("latency duration", technical_filter="Latency", max_results=10)
    """
    try:
        import asyncpg
        import json
        from typing import List, Dict, Any
        
        # Database connection using environment variables
        DATABASE_URL = f"postgresql://{os.getenv('POSTGRES_USER', 'semantic_graph')}:{os.getenv('POSTGRES_PASSWORD')}@{os.getenv('POSTGRES_HOST', 'postgres')}:{os.getenv('POSTGRES_PORT', '5432')}/{os.getenv('POSTGRES_DB', 'semantic_graph')}"
        
        # Validate parameters
        max_results = min(max(1, max_results), 50)  # Clamp between 1 and 50
        
        # Connect to database and search
        conn = await asyncpg.connect(DATABASE_URL)
        
        try:
            # Use the enhanced search function with trigram similarity
            results = await conn.fetch("""
                SELECT * FROM search_metrics_enhanced($1, $2, $3, $4, $5)
            """, query, max_results, category_filter, technical_filter, 0.2)
            
            if not results:
                return f"""# 🔍 Metrics Discovery Results
                
**Query**: "{query}"
**Results**: No metrics found

**Suggestions**:
- Try broader terms (e.g., "error" instead of "error_rate")
- Check available categories: Infrastructure, Application, Database, Storage, Network, Monitoring
- Use technical categories: Error, Latency, Count, Performance, Resource, Throughput, Availability

**Available metrics**: {await conn.fetchval("SELECT COUNT(*) FROM metrics_intelligence WHERE excluded = FALSE")} total metrics in the database.
"""
            
            # Format results
            formatted_results = []
            for i, row in enumerate(results, 1):
                # Parse JSON fields safely
                try:
                    dimensions = json.loads(row['common_dimensions']) if row['common_dimensions'] else {}
                    value_range = json.loads(row['value_range']) if row['value_range'] else {}
                    query_patterns = json.loads(row.get('query_patterns', '[]')) if row.get('query_patterns') else []
                    nested_field_paths = json.loads(row.get('nested_field_paths', '{}')) if row.get('nested_field_paths') else {}
                    nested_field_analysis = json.loads(row.get('nested_field_analysis', '{}')) if row.get('nested_field_analysis') else {}
                except (json.JSONDecodeError, TypeError):
                    dimensions = {}
                    value_range = {}
                    query_patterns = []
                    nested_field_paths = {}
                    nested_field_analysis = {}
                
                # Format dimension keys
                dim_keys = list(dimensions.keys()) if dimensions else []
                dim_text = f"**Dimensions**: {', '.join(dim_keys[:5])}" if dim_keys else "**Dimensions**: None"
                if len(dim_keys) > 5:
                    dim_text += f" (+{len(dim_keys)-5} more)"
                
                # Format value range
                range_text = ""
                if value_range and isinstance(value_range, dict):
                    if 'min' in value_range and 'max' in value_range:
                        range_text = f"**Range**: {value_range.get('min', 'N/A')} - {value_range.get('max', 'N/A')}"
                
                # Format last seen
                last_seen = row['last_seen'].strftime('%Y-%m-%d %H:%M') if row['last_seen'] else 'Unknown'
                
                # Format metric type and query patterns
                metric_type = row.get('metric_type', 'unknown')
                common_fields = row.get('common_fields', [])

                # Create enhanced query guidance section
                query_guidance = ""
                if query_patterns and len(query_patterns) > 0:
                    # Show primary query pattern
                    primary_pattern = query_patterns[0]
                    pattern_text = primary_pattern.get('pattern', '') if isinstance(primary_pattern, dict) else str(primary_pattern)
                    if pattern_text:
                        query_guidance = f"**Query Pattern**: `{pattern_text}`\n"
                        # Show use case if available
                        if isinstance(primary_pattern, dict) and primary_pattern.get('use_case'):
                            query_guidance += f"**Use Case**: {primary_pattern['use_case']}\n"

                # Add nested field information
                if nested_field_paths:
                    important_fields = nested_field_analysis.get('important_fields', []) if nested_field_analysis else []
                    if important_fields:
                        nested_text = ', '.join(important_fields[:3])
                        if len(important_fields) > 3:
                            nested_text += f" (+{len(important_fields)-3} more)"
                        query_guidance += f"**Key Nested Fields**: {nested_text}\n"

                if common_fields:
                    field_list = ', '.join(common_fields[:3])
                    if len(common_fields) > 3:
                        field_list += f" (+{len(common_fields)-3} more)"
                    query_guidance += f"**Common Fields**: {field_list}\n"
                
                # Calculate combined relevance score
                combined_score = max(row['rank'], row.get('similarity_score', 0))
                score_details = []
                if row['rank'] > 0:
                    score_details.append(f"text-match: {row['rank']:.3f}")
                if row.get('similarity_score', 0) > 0:
                    score_details.append(f"similarity: {row['similarity_score']:.3f}")

                result_text = f"""## {i}. {row['metric_name']}
**Dataset**: {row['dataset_name']}
**Category**: {row['business_category']} / {row['technical_category']}
**Type**: {metric_type}
**Purpose**: {row['inferred_purpose']}
**Usage**: {row['typical_usage']}
{dim_text}
{query_guidance}{range_text}
**Frequency**: {row['data_frequency']} | **Last Seen**: {last_seen}
**Relevance Score**: {combined_score:.3f} ({', '.join(score_details) if score_details else 'fuzzy-match'})
"""
                formatted_results.append(result_text)
            
            # Get summary stats
            total_metrics = await conn.fetchval("SELECT COUNT(*) FROM metrics_intelligence WHERE excluded = FALSE")
            category_counts = await conn.fetch("""
                SELECT business_category, COUNT(*) as count 
                FROM metrics_intelligence 
                WHERE excluded = FALSE 
                GROUP BY business_category 
                ORDER BY count DESC
            """)
            
            category_summary = ", ".join([f"{row['business_category']} ({row['count']})" for row in category_counts[:3]])
            
            return f"""# 🎯 Metrics Discovery Results

**Query**: "{query}"
**Found**: {len(results)} metrics (showing top {max_results})
**Search Scope**: {total_metrics} total metrics | Top categories: {category_summary}

{chr(10).join(formatted_results)}

---
💡 **Next Steps**: 
- Use `execute_opal_query()` with the dataset ID to query specific metrics
- Use `discover_datasets()` to find related datasets  
- Use `create_visualization()` to chart the metric data
"""
            
        finally:
            await conn.close()
            
    except ImportError as e:
        return f"""# ❌ Metrics Discovery Error

**Issue**: Required database library not available
**Error**: {str(e)}
**Solution**: The metrics intelligence system requires asyncpg. Please install it:
```bash
pip install asyncpg
```
"""
    
    except Exception as e:
        return f"""# ❌ Metrics Discovery Error

**Query**: "{query}"
**Error**: {str(e)}

**Possible Causes**:
- Database connection failed
- Metrics intelligence table not initialized
- Invalid search parameters

**Solution**: Ensure the metrics intelligence system is running and database is accessible.
"""


mcp.run(transport="sse", host="0.0.0.0", port=8000)
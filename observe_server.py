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
    from dotenv import load_dotenv
    pass
except Exception as e:
    pass
    raise

# Load environment variables from .env file first
load_dotenv()

# Initialize OpenTelemetry instrumentation early
from src.telemetry import initialize_telemetry, initialize_metrics
from src.telemetry.decorators import trace_mcp_tool, trace_observe_api_call, trace_database_operation
from src.telemetry.utils import add_mcp_context, add_observe_context, add_database_context
telemetry_enabled = initialize_telemetry()

# Initialize metrics if telemetry is enabled
if telemetry_enabled:
    metrics_enabled = initialize_metrics()
else:
    metrics_enabled = False

# Import BM25 document search
try:
    from src.postgres.doc_search import search_docs_bm25 as search_docs
except ImportError as e:
    # Define fallback search function
    def search_docs(query: str, n_results: int = 5) -> List[Dict[str, Any]]:
        return [{
            "text": f"Error: PostgreSQL BM25 search not available. The server cannot perform document search because the BM25 modules are not properly installed. Please ensure PostgreSQL is running and the documentation_chunks table exists. Your query was: {query}",
            "source": "error",
            "title": "BM25 Search Not Available",
            "score": 1.0
        }]

# Import organized Observe API modules
from src.observe import (
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

from fastmcp import Context

# Create FastMCP instance with authentication
mcp = create_authenticated_mcp(server_name="observe-community")

# Initialize auth middleware for statistics and logging
auth_provider = setup_auth_provider()
initialize_auth_middleware(auth_provider)

# Track sessions that have called get_system_prompt
session_prompt_status = {}

def check_system_prompt_called(ctx: Context, tool_name: str) -> Optional[str]:
    """Check if system prompt has been called for this session"""
    session_id = ctx.session_id
    if session_id not in session_prompt_status and tool_name != "get_system_prompt":
        return f"""🚨 CRITICAL: System prompt not loaded for this session!

⚡ You MUST call get_system_prompt() first to access specialized Observe platform expertise.

Without the system prompt, you'll lack:
- Verified OPAL syntax patterns
- Observe investigation methodology
- Performance optimization strategies
- Proper tool usage protocols

📝 Please run: get_system_prompt() before proceeding with {tool_name}.
"""
    return None


# Configure FastAPI instrumentation if telemetry is enabled
if telemetry_enabled:
    from src.telemetry.config import instrument_fastapi_app
    # Note: FastMCP wraps FastAPI, so we'll instrument the underlying app
    if hasattr(mcp, 'app'):
        instrument_fastapi_app(mcp.app)


@mcp.tool()
@requires_scopes(['admin', 'write', 'read'])
@trace_mcp_tool(tool_name="execute_opal_query", record_args=True, record_result=False)
async def execute_opal_query(ctx: Context, query: str, dataset_id: str = None, primary_dataset_id: str = None, secondary_dataset_ids: Optional[str] = None, dataset_aliases: Optional[str] = None, time_range: Optional[str] = "1h", start_time: Optional[str] = None, end_time: Optional[str] = None, format: Optional[str] = "csv", timeout: Optional[float] = None) -> str:
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

    # Check if system prompt has been called
    prompt_check = check_system_prompt_called(ctx, "execute_opal_query")
    if prompt_check:
        return prompt_check

    # Log the OPAL query operation with sanitized query (truncated for security)
    query_preview = query[:100] + "..." if len(query) > 100 else query
    dataset_info = primary_dataset_id or dataset_id
    opal_logger.info(f"query execution | dataset:{dataset_info} | query:'{query_preview}' | time_range:{time_range}")
    
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
        format=format,
        timeout=timeout
    )



@mcp.tool()
@requires_scopes(['admin', 'read'])
@trace_mcp_tool(tool_name="get_relevant_docs", record_args=True, record_result=False)
async def get_relevant_docs(ctx: Context, query: str, n_results: int = 5) -> str:
    """Get relevant documentation for a query using PostgreSQL BM25 search"""
    try:
        # Import required modules
        import os
        from collections import defaultdict

        # Check if system prompt has been called
        prompt_check = check_system_prompt_called(ctx, "get_relevant_docs")
        if prompt_check:
            return prompt_check

        # Log the documentation search operation
        semantic_logger.info(f"docs search | query:'{query}' | n_results:{n_results}")

        chunk_results = await search_docs(query, n_results=max(n_results * 3, 15))  # Get more chunks to ensure we have enough from relevant docs

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

        # Log successful documentation search
        semantic_logger.info(f"docs search complete | found:{len(sorted_docs)} documents | chunks:{len(chunk_results)}")

        return response
    except Exception as e:
        return f"Error retrieving relevant documents: {str(e)}. Make sure you've populated the BM25 index by running scripts/populate_docs_bm25.py."


@mcp.tool()
@requires_scopes(['admin', 'write', 'read'])
@trace_mcp_tool(tool_name="get_system_prompt", record_args=False, record_result=False)
async def get_system_prompt(ctx: Context) -> str:
    """
    🚨 CRITICAL: MUST BE CALLED FIRST BEFORE ANY OTHER TOOLS 🚨

    This tool provides the specialized Observe platform expertise that transforms
    generic LLMs into expert Observe analysts. Without this prompt, LLMs will:
    - Use incorrect OPAL syntax
    - Make inefficient dataset queries
    - Provide generic instead of Observe-specific guidance
    - Query non-existent fields causing errors

    ⚡ MANDATORY WORKFLOW: get_system_prompt() → discover_datasets/metrics() → execute_opal_query()

    Returns the complete system prompt that defines:
    - Observe platform investigation methodology
    - Schema validation requirements (CRITICAL for query success)
    - Verified OPAL syntax patterns
    - Performance optimization strategies
    - Tool usage protocols

    Returns:
        Complete system prompt as plain text (ready for immediate adoption)
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

                # Mark that this session has loaded the system prompt
                session_prompt_status[ctx.session_id] = True
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
        # Return the system prompt directly from the file
        return system_prompt
            
    except Exception as e:
        session_logger.error(f"exception getting system prompt | error:{e}")
        import traceback
        traceback.print_exc(file=sys.stderr)
        return {"error": True, "message": f"Exception getting system prompt: {str(e)}"}


@mcp.tool()
@requires_scopes(['admin', 'read'])
@trace_mcp_tool(tool_name="discover_datasets", record_args=True, record_result=False)
async def discover_datasets(ctx: Context, query: str, max_results: int = 15, business_category_filter: Optional[str] = None, technical_category_filter: Optional[str] = None, interface_filter: Optional[str] = None) -> str:
    """
    Discover datasets using fast full-text search on our dataset intelligence database.
    
    This tool searches through analyzed datasets with intelligent categorization and usage guidance.
    Perfect for finding datasets by name, purpose, business area, or technical type.

    CRITICAL: This tool returns essential schema information that MUST be analyzed before querying:
    - Key Fields: Exact field names available for filtering and selection
    - Nested Fields: JSON structure for complex field access
    - Dataset Type & Interface: Determines query patterns (log vs metric vs trace)

    Args:
        query: Search query (e.g., "kubernetes logs", "service metrics", "error traces", "user sessions")
        max_results: Maximum number of datasets to return (default: 15, max: 30)
        business_category_filter: Filter by business category (Infrastructure, Application, Database, User, Security, etc.)
        technical_category_filter: Filter by technical category (Logs, Metrics, Traces, Events, Resources, etc.)
        interface_filter: Filter by interface type (log, metric, otel_span, etc.)

    Returns:
        Formatted list of matching datasets with their purposes, usage guidance, and SCHEMA INFORMATION
        
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

        # Check if system prompt has been called
        prompt_check = check_system_prompt_called(ctx, "discover_datasets")
        if prompt_check:
            return prompt_check

        # Log the semantic search operation
        semantic_logger.info(f"dataset search | query:'{query}' | max_results:{max_results} | filters:{business_category_filter or technical_category_filter or interface_filter}")

        # Database connection using environment variables
        DATABASE_URL = f"postgresql://{os.getenv('POSTGRES_USER', 'semantic_graph')}:{os.getenv('SEMANTIC_GRAPH_PASSWORD', 'g83hbeyB32792r3Gsjnfwe0ihf2')}@{os.getenv('POSTGRES_HOST', 'localhost')}:{os.getenv('POSTGRES_PORT', '5432')}/{os.getenv('POSTGRES_DB', 'semantic_graph')}"
        
        # Validate parameters
        max_results = min(max(1, max_results), 30)  # Clamp between 1 and 30
        
        # Connect to database and search
        conn = await asyncpg.connect(DATABASE_URL)
        
        try:
            # Enhanced manual query with better search capabilities
            # Split complex queries into individual terms for better matching
            search_terms = query.lower().split()

            # Create individual search conditions for better matching
            search_conditions = []
            params = []
            param_idx = 1

            for term in search_terms:
                search_conditions.append(f"di.search_vector @@ plainto_tsquery('english', ${param_idx})")
                params.append(term)
                param_idx += 1

            # If no individual terms match, fall back to full query
            if not search_conditions:
                search_conditions = [f"di.search_vector @@ plainto_tsquery('english', ${param_idx})"]
                params.append(query)
                param_idx += 1

            # Combine search conditions with OR for better matching
            where_clause = f"({' OR '.join(search_conditions)})"

            # Add filters
            if business_category_filter:
                where_clause += f" AND di.business_categories ? ${param_idx}"
                params.append(business_category_filter)
                param_idx += 1

            if technical_category_filter:
                where_clause += f" AND di.technical_category = ${param_idx}"
                params.append(technical_category_filter)
                param_idx += 1

            if interface_filter:
                where_clause += f" AND ${param_idx} = ANY(di.interface_types)"
                params.append(interface_filter)
                param_idx += 1

            # Add limit parameter
            params.append(max_results)
            limit_param = param_idx

            query_sql = f"""
                SELECT
                    di.dataset_id::TEXT,
                    di.dataset_name::TEXT,
                    di.inferred_purpose,
                    di.typical_usage,
                    di.business_categories,
                    di.technical_category,
                    di.interface_types,
                    di.key_fields,
                    di.query_patterns,
                    di.nested_field_paths,
                    di.nested_field_analysis,
                    di.common_use_cases,
                    di.data_frequency,
                    FALSE as excluded,
                    ts_rank(di.search_vector, plainto_tsquery('english', $1))::REAL as rank,
                    0.0::REAL as similarity_score
                FROM datasets_intelligence di
                WHERE di.excluded = FALSE
                  AND {where_clause}
                ORDER BY rank DESC
                LIMIT ${limit_param}
            """

            results = await conn.fetch(query_sql, *params)
            
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

                # Format ALL available fields with complete schema information
                schema_info_str = ""

                # Combine all fields from key_fields and nested_field_paths
                all_fields_info = {}

                # Add top-level fields from key_fields
                if row.get('key_fields'):
                    for field in row['key_fields']:
                        all_fields_info[field] = {"type": "unknown", "sample_values": []}

                # Add detailed nested field information
                if nested_field_paths:
                    for field_path, field_info in nested_field_paths.items():
                        if isinstance(field_info, dict):
                            all_fields_info[field_path] = {
                                "type": field_info.get("type", "unknown"),
                                "sample_values": field_info.get("sample_values", [])[:3]  # Show 3 samples max
                            }
                        else:
                            all_fields_info[field_path] = {"type": "unknown", "sample_values": []}

                if all_fields_info:
                    schema_info_str = "🚨 **COMPLETE SCHEMA - USE EXACT FIELD NAMES & TYPES**:\n"

                    # Sort fields: top-level first, then nested
                    top_level_fields = [f for f in all_fields_info.keys() if '.' not in f]
                    nested_fields = [f for f in all_fields_info.keys() if '.' in f]

                    for field_list, header in [(top_level_fields, "📋 **Top-Level Fields**"), (nested_fields, "📍 **Nested Fields**")]:
                        if field_list:
                            schema_info_str += f"\n{header}:\n"
                            for field in sorted(field_list)[:15]:  # Limit to 15 per section to manage size
                                field_info = all_fields_info[field]
                                type_info = f"({field_info['type']})" if field_info['type'] != 'unknown' else ""

                                # Show sample values with type hints for duration fields
                                samples_str = ""
                                if field_info['sample_values']:
                                    samples = field_info['sample_values'][:2]  # Show 2 samples max
                                    samples_str = f" → {samples}"

                                    # Add duration unit hints
                                    if any(keyword in field.lower() for keyword in ['time', 'elapsed', 'duration', 'timestamp']):
                                        if any(len(str(s)) >= 15 for s in samples if str(s).isdigit()):
                                            samples_str += " (⏱️ likely nanoseconds)"
                                        elif any(len(str(s)) == 13 for s in samples if str(s).isdigit()):
                                            samples_str += " (⏱️ likely milliseconds)"

                                schema_info_str += f"  • `{field}` {type_info}{samples_str}\n"

                            if len(field_list) > 15:
                                schema_info_str += f"  • ... (+{len(field_list)-15} more {header.lower()} fields)\n"

                    schema_info_str += "\n"

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
**Category**: {', '.join(json.loads(row['business_categories']) if row['business_categories'] else ['Unknown'])} / {row['technical_category']}
{interfaces_str}**Purpose**: {row['inferred_purpose']}
**Usage**: {row.get('typical_usage', 'Not specified')}
{schema_info_str}{query_guidance_str}{usage_str}**Frequency**: {row.get('data_frequency', 'unknown')}
**Relevance Score**: {combined_score:.3f} ({', '.join(score_details) if score_details else 'fuzzy-match'})
"""
                formatted_results.append(result_text)
            
            # Get summary stats
            total_datasets = await conn.fetchval("SELECT COUNT(*) FROM datasets_intelligence WHERE excluded = FALSE")
            category_counts = await conn.fetch("""
                SELECT
                    jsonb_array_elements_text(business_categories) as business_category,
                    COUNT(*) as count
                FROM datasets_intelligence
                WHERE excluded = FALSE
                GROUP BY jsonb_array_elements_text(business_categories)
                ORDER BY count DESC
                LIMIT 5
            """)
            
            category_summary = ", ".join([f"{row['business_category']} ({row['count']})" for row in category_counts[:3]])
            
            # Log successful results
            semantic_logger.info(f"dataset search complete | found:{len(results)} datasets | total_available:{total_datasets}")

            return f"""# 🎯 Dataset Discovery Results

**Query**: "{query}"
**Found**: {len(results)} datasets (showing top {max_results})
**Search Scope**: {total_datasets} total datasets | Top categories: {category_summary}

{chr(10).join(formatted_results)}

---
💡 **Next Steps**:
- Use `execute_opal_query()` with the dataset ID to query the data
- Use `discover_metrics()` to find related metrics for analysis
"""
            
        finally:
            await conn.close()
            
    except ImportError as e:
        return f"""# ❌ Dataset Discovery Error
**Issue**: Required database library not available
**Error**: {str(e)}
**Solution**: The dataset intelligence system requires asyncpg. Please install it with: pip install asyncpg"""
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        return f"""# ❌ Dataset Discovery Error
**Issue**: Database query failed
**Error**: {str(e)}
**Type**: {type(e).__name__}
**Traceback**:
```
{tb[:1000]}
```
**Query Params**: query='{query}', business_filter='{business_category_filter}', max_results={max_results}
**Solution**: Check database connection and ensure dataset intelligence has been populated."""


@mcp.tool()
@requires_scopes(['admin', 'read'])
@trace_mcp_tool(tool_name="discover_metrics", record_args=True, record_result=False)
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

        # Check if system prompt has been called
        prompt_check = check_system_prompt_called(ctx, "discover_metrics")
        if prompt_check:
            return prompt_check

        # Log the semantic search operation
        semantic_logger.info(f"metrics search | query:'{query}' | max_results:{max_results} | filters:{category_filter or technical_filter}")

        # Database connection using environment variables
        DATABASE_URL = f"postgresql://{os.getenv('POSTGRES_USER', 'semantic_graph')}:{os.getenv('SEMANTIC_GRAPH_PASSWORD', 'g83hbeyB32792r3Gsjnfwe0ihf2')}@{os.getenv('POSTGRES_HOST', 'localhost')}:{os.getenv('POSTGRES_PORT', '5432')}/{os.getenv('POSTGRES_DB', 'semantic_graph')}"
        
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

                # Add nested field information with visual prominence
                if nested_field_paths:
                    important_fields = nested_field_analysis.get('important_fields', []) if nested_field_analysis else []
                    if important_fields:
                        nested_text = ', '.join(important_fields[:4])  # Show 4 instead of 3
                        if len(important_fields) > 4:
                            nested_text += f" (+{len(important_fields)-4} more)"
                        query_guidance += f"📍 **Key Nested Fields (EXACT PATHS)**: {nested_text}\n"

                if common_fields:
                    field_list = ', '.join(common_fields[:4])  # Show 4 instead of 3
                    if len(common_fields) > 4:
                        field_list += f" (+{len(common_fields)-4} more)"
                    query_guidance += f"🚨 **Common Fields (USE EXACT NAMES)**: {field_list}\n"
                
                # Calculate combined relevance score
                combined_score = max(row['rank'], row.get('similarity_score', 0))
                score_details = []
                if row['rank'] > 0:
                    score_details.append(f"text-match: {row['rank']:.3f}")
                if row.get('similarity_score', 0) > 0:
                    score_details.append(f"similarity: {row['similarity_score']:.3f}")

                result_text = f"""## {i}. {row['metric_name']}
**Dataset**: {row['dataset_name']}
**Dataset ID**: `{row['dataset_id']}`
**Category**: {', '.join(json.loads(row['business_categories']) if row['business_categories'] else ['Unknown'])} / {row['technical_category']}
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
                SELECT
                    jsonb_array_elements_text(business_categories) as business_category,
                    COUNT(*) as count
                FROM metrics_intelligence
                WHERE excluded = FALSE
                GROUP BY jsonb_array_elements_text(business_categories)
                ORDER BY count DESC
            """)
            
            category_summary = ", ".join([f"{row['business_category']} ({row['count']})" for row in category_counts[:3]])

            # Log successful results
            semantic_logger.info(f"metrics search complete | found:{len(results)} metrics | total_available:{total_metrics}")

            return f"""# 🎯 Metrics Discovery Results

**Query**: "{query}"
**Found**: {len(results)} metrics (showing top {max_results})
**Search Scope**: {total_metrics} total metrics | Top categories: {category_summary}

{chr(10).join(formatted_results)}

---
💡 **Next Steps**:
- Use `execute_opal_query()` with the dataset ID to query specific metrics
- Use `discover_datasets()` to find related datasets for comprehensive analysis
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


if __name__ == "__main__":
    import signal
    import atexit

    # Register shutdown handler for telemetry
    def shutdown_handler():
        if telemetry_enabled:
            from src.telemetry.config import shutdown_telemetry
            shutdown_telemetry()

    # Register shutdown on exit and signal
    atexit.register(shutdown_handler)
    signal.signal(signal.SIGTERM, lambda signum, frame: shutdown_handler())
    signal.signal(signal.SIGINT, lambda signum, frame: shutdown_handler())

    # Run the MCP server
    mcp.run(transport="sse", host="0.0.0.0", port=8000)
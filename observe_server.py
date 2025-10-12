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
    Execute OPAL (Observe Processing and Analytics Language) queries on datasets.

    OPAL is Observe's query language for filtering, transforming, and aggregating data.
    Always use discover_datasets() or discover_metrics() first to get schema information.

    🛠️ VERIFIED OPAL SYNTAX REFERENCE
    ═══════════════════════════════════

    CORE PATTERNS (Tested & Verified)
    ─────────────────────────────────
    Pattern         | ✅ Correct Syntax                      | ❌ Wrong Syntax
    ────────────────┼────────────────────────────────────────┼──────────────────────────
    Conditions      | if(error = true, "error", "ok")        | case when error...
    Columns         | make_col new_field: expression         | new_field = expression
    Sorting         | sort desc(field)                       | sort -field
    Limits          | limit 10                               | head 10
    Text Search     | filter body ~ error                    | filter body like "%error%"
    JSON Fields     | string(attrs."k8s.namespace.name")    | attrs.k8s.namespace.name

    🔍 MULTI-KEYWORD SEARCH (CRITICAL LOGIC)
    ─────────────────────────────────────────
    Syntax                          | Logic  | Case      | Performance | Use When
    ────────────────────────────────┼────────┼───────────┼─────────────┼──────────────
    field ~ <KEY1 KEY2>             | AND ⚠️ | Ignore    | Optimized   | ALL match
    contains(f,"K1") or contains... | OR     | Sensitive | Slower      | ANY match

    Examples:
      filter body ~ <error exception>                           # BOTH "error" AND "exception"
      filter contains(body, "error") or contains(body, "warn")  # EITHER "error" OR "warn"

    ⚠️ COMMON CONFUSION: ~ <K1 K2> uses AND logic, not OR!

    LOG ANALYSIS PATTERNS
    ────────────────────
    # Basic error search
    filter body ~ error | limit 10

    # Multiple keywords (AND logic)
    filter body ~ <error exception failure>

    # Extract Kubernetes context (nested JSON)
    make_col
        namespace:string(resource_attributes."k8s.namespace.name"),
        pod:string(resource_attributes."k8s.pod.name"),
        container:string(resource_attributes."k8s.container.name")
    | filter body ~ error
    | limit 50

    # Time-based filtering
    filter body ~ error
    | filter timestamp > @"1 hour ago"
    | limit 100

    # Statistical analysis with conditional aggregation
    filter body ~ error
    | make_col is_error:if(error=true, 1, 0)
    | statsby
        error_count:sum(is_error),
        total_count:count(),
        group_by(string(resource_attributes."k8s.namespace.name"))
    | sort desc(error_count)

    METRICS ANALYSIS PATTERNS
    ────────────────────────
    # Simple aggregation
    filter metric = "error_count"
    | statsby total_errors:sum(value), group_by(service_name)
    | sort desc(total_errors)

    # Conditional counting (count_if does NOT exist!)
    # WRONG: statsby error_count:count_if(error=true)
    # RIGHT: Use make_col + sum() pattern
    make_col is_error:if(error=true, 1, 0)
    | statsby error_count:sum(is_error), group_by(service_name)

    ⏱️ TIME UNIT CONVERSIONS
    ────────────────────────
    # Convert nanoseconds to milliseconds
    make_col elapsed_ms: elapsedTime / 1000000

    # Convert nanoseconds to seconds
    make_col elapsed_s: elapsedTime / 1000000000

    # Time-based filtering (built-in functions)
    filter TIMESTAMP > @"1 hour ago"
    filter TIMESTAMP between @"2024-01-01T00:00:00Z" and @"2024-01-02T00:00:00Z"

    QUERY RESULT CONTROL
    ───────────────────
    filter body ~ error | limit 10        # Small sample
    filter body ~ error | limit 100       # Larger dataset
    filter body ~ error                    # Default: up to 1000 rows

    🚨 COMMON ERRORS & SOLUTIONS
    ════════════════════════════
    ❌ "field not found" → Check schema from discover_datasets() first
    ❌ Empty JSON extraction → Use string(field."nested.key") syntax
    ❌ "invalid syntax" → Check verified patterns table above
    ❌ Wrong time units → Check sample values, convert if needed (nanoseconds!)
    ❌ Slow query → Add filters, use limit, check time range

    🚫 FUNCTIONS THAT DON'T EXIST (Common Mistakes)
    ════════════════════════════════════════════════
    ❌ count_if(condition) → Use: make_col flag:if(condition,1,0) | statsby sum(flag)
    ❌ bin(field, interval) → Time bucketing syntax may differ, check docs with get_relevant_docs()

    ⚠️ CRITICAL: NEVER ASSUME FIELD NAMES!
    ═══════════════════════════════════════
    Field names vary by dataset. Some datasets use 'timestamp', others use 'start_time',
    'end_time', 'TIMESTAMP', 'observed_timestamp', etc.

    ALWAYS run discover_datasets() or discover_metrics() FIRST to get the EXACT field names
    from the schema before writing queries. Field names are case-sensitive and dataset-specific.

    Args:
        query: OPAL query string (use verified syntax above)
        dataset_id: DEPRECATED - use primary_dataset_id instead
        primary_dataset_id: Main dataset ID from discover_datasets() or discover_metrics()
        secondary_dataset_ids: JSON array string for joins (e.g., '["44508111"]')
        dataset_aliases: JSON object string for joins (e.g., '{"volumes": "44508111"}')
        time_range: Relative time window (e.g., "1h", "24h", "7d", "30d")
        start_time: Absolute start time in ISO format (e.g., "2024-01-20T16:20:00Z")
        end_time: Absolute end time in ISO format (e.g., "2024-01-20T17:20:00Z")
        format: Output format - "csv" (default, human-readable) or "ndjson" (programmatic)
        timeout: Query timeout in seconds (default: 30s, increase for complex queries)

    Returns:
        Query results in requested format. CSV returns first 1000 rows by default
        unless limited by OPAL query's limit clause.

    Examples:
        # WORKFLOW: Always discover schema first!
        # Step 1: Get schema and field names
        discover_datasets("kubernetes logs")
        # Step 2: Use EXACT field names from schema
        execute_opal_query(
            query="filter body ~ error | limit 10",
            primary_dataset_id="42161740",
            time_range="1h"
        )

        # Conditional aggregation (NO count_if!)
        execute_opal_query(
            query='''
                make_col
                    service:string(resource_attributes."service.name"),
                    is_error:if(error=true, 1, 0)
                | statsby
                    total:count(),
                    errors:sum(is_error),
                    group_by(service)
                | make_col error_rate:100.0*errors/total
            ''',
            primary_dataset_id="42160967",
            time_range="1h"
        )

        # Multi-dataset join with aliases
        execute_opal_query(
            query="join on(instanceId=@volumes.instanceId), volume_size:@volumes.size",
            primary_dataset_id="44508123",
            secondary_dataset_ids='["44508111"]',
            dataset_aliases='{"volumes": "44508111"}'
        )

    Performance:
        - Log queries (1000+ entries): 1-3 seconds
        - Metrics queries (100+ points): 500ms-2s
        - Use filters and limits for better performance
        - Increase timeout for complex aggregations
    """
    import json

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
    """
    Search Observe documentation using BM25 search for OPAL syntax and platform guidance.

    This tool searches through official Observe documentation to find relevant information
    about OPAL syntax, functions, features, and best practices.

    WHEN TO USE THIS TOOL
    ─────────────────────
    - Unsure about OPAL syntax or available functions
    - Need documentation on specific Observe features
    - Want to verify query patterns against official docs
    - Looking for advanced OPAL capabilities not covered in basic syntax
    - Troubleshooting OPAL query errors or unexpected behavior

    TYPICAL USE CASES
    ────────────────
    - "OPAL filter syntax" → Learn filtering operators and patterns
    - "OPAL time functions" → Understand time manipulation functions
    - "kubernetes resource attributes" → Find available K8s fields
    - "statsby group_by" → Learn aggregation syntax
    - "OPAL join syntax" → Multi-dataset join patterns

    Args:
        query: Documentation search query describing what you need to learn
        n_results: Number of documents to return (default: 5, recommended: 3-10)

    Returns:
        Relevant documentation sections with:
        - Full document content
        - Source filename for reference
        - Relevance score indicating match quality

    Examples:
        # Learn OPAL syntax
        get_relevant_docs("OPAL filter syntax")
        get_relevant_docs("time range functions")

        # Find schema information
        get_relevant_docs("kubernetes resource attributes")
        get_relevant_docs("opentelemetry span fields")

        # Advanced features
        get_relevant_docs("OPAL join multiple datasets", n_results=3)
        get_relevant_docs("aggregation functions statsby")

    Performance:
        - Search time: 200-500ms
        - Returns full documents (may be lengthy)
    """
    try:
        # Import required modules
        import os
        from collections import defaultdict

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
@requires_scopes(['admin', 'read'])
@trace_mcp_tool(tool_name="discover_datasets", record_args=True, record_result=False)
async def discover_datasets(ctx: Context, query: str = "", dataset_id: Optional[str] = None, dataset_name: Optional[str] = None, max_results: int = 15, business_category_filter: Optional[str] = None, technical_category_filter: Optional[str] = None, interface_filter: Optional[str] = None) -> str:
    """
    Discover datasets using intelligent search and get complete schema information for querying.

    This tool searches through analyzed datasets with intelligent categorization and returns
    COMPLETE SCHEMA INFORMATION that is essential for constructing correct OPAL queries.

    🚨 CRITICAL SCHEMA VALIDATION REQUIREMENTS
    ═══════════════════════════════════════════
    This tool returns schema information that MUST be analyzed before querying:

    📋 KEY FIELDS - Available field names for filtering/selection
       - Use ONLY fields shown in the schema
       - Field names are case-sensitive
       - Never assume field names exist without checking

    📍 NESTED FIELDS - JSON structure for complex field access
       - Correct syntax: string(resource_attributes."k8s.namespace.name")
       - Wrong syntax: resource_attributes.k8s.namespace.name (will fail!)
       - Always use string() function for nested JSON paths
       - Check sample values to understand data structure

    ⏱️ TIME UNITS - CRITICAL: Observe uses NANOSECONDS by default!
       - Fields WITHOUT suffix (elapsedTime, duration, TIMESTAMP) = NANOSECONDS
       - Fields WITH suffix (_ms, _s) = as labeled (milliseconds, seconds)
       - Sample value indicators:
         • 19 digits = nanoseconds (e.g., 1760201545280843522)
         • 13 digits = milliseconds (e.g., 1758543367916)
       - Conversions:
         • To milliseconds: field / 1000000
         • To seconds: field / 1000000000

    🔍 DATASET INTERFACE TYPES
       - log: Use text search (~), filter by body/message fields
       - metric: Use metric name filters, aggregate with statsby
       - otel_span: Trace data with parent/child span relationships

    COMMON ERRORS PREVENTED BY SCHEMA ANALYSIS
    ───────────────────────────────────────────
    ❌ "Field not found" → Always check "Key Fields" section first
    ❌ Empty JSON extraction → Use string() with exact nested path from schema
    ❌ Wrong time units → Check sample values and field naming (no suffix = nanoseconds)
    ❌ Wrong query pattern → Match interface type (log vs metric vs trace)

    Args:
        query: Search query (e.g., "kubernetes logs", "error traces"). Optional if dataset_id/dataset_name provided.
        dataset_id: Exact dataset ID for fast lookup (e.g., "42161740"). Returns only this dataset.
        dataset_name: Exact dataset name for lookup (e.g., "Kubernetes Explorer/Kubernetes Logs"). Case-sensitive.
        max_results: Maximum datasets for search queries (1-30, default: 15). Ignored for exact ID/name lookups.
        business_category_filter: Filter by business category (Infrastructure, Application, Database, User, Security, etc.)
        technical_category_filter: Filter by technical category (Logs, Metrics, Traces, Events, Resources, etc.)
        interface_filter: Filter by interface type (log, metric, otel_span, etc.)

    Returns:
        Formatted dataset information with COMPLETE SCHEMA including:
        - Dataset ID and name for use with execute_opal_query()
        - Purpose and typical usage patterns
        - Top-level fields with types and sample values
        - Nested field paths with proper access syntax
        - Query pattern examples
        - Time unit indicators for duration fields

    Examples:
        # Smart search
        discover_datasets("kubernetes error logs")

        # Fast exact lookups
        discover_datasets(dataset_id="42161740")
        discover_datasets(dataset_name="Kubernetes Explorer/Kubernetes Logs")

        # Filtered search
        discover_datasets("performance", technical_category_filter="Metrics")
        discover_datasets("application logs", business_category_filter="Application", max_results=5)

    Performance:
        - Search queries: 200-500ms
        - Exact ID/name lookups: <100ms
    """
    try:
        import asyncpg
        import json
        from typing import List, Dict, Any

        # Log the semantic search operation
        semantic_logger.info(f"dataset search | query:'{query}' | max_results:{max_results} | filters:{business_category_filter or technical_category_filter or interface_filter}")

        # Database connection using individual parameters (same as working scripts)
        db_password = os.getenv('SEMANTIC_GRAPH_PASSWORD')
        if not db_password:
            raise ValueError("SEMANTIC_GRAPH_PASSWORD environment variable must be set")

        db_config = {
            'host': os.getenv('POSTGRES_HOST', 'localhost'),
            'port': int(os.getenv('POSTGRES_PORT', '5432')),
            'database': os.getenv('POSTGRES_DB', 'semantic_graph'),
            'user': os.getenv('POSTGRES_USER', 'semantic_graph'),
            'password': db_password
        }

        # Validate parameters
        max_results = min(max(1, max_results), 30)  # Clamp between 1 and 30

        # Connect to database using individual parameters (avoids SSL/TLS DNS issues)
        conn = await asyncpg.connect(**db_config)

        try:
            # Check for exact lookups by ID or name
            if dataset_id is not None:
                # Exact dataset ID lookup
                semantic_logger.info(f"dataset lookup by ID | dataset_id:{dataset_id}")

                results = await conn.fetch("""
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
                        di.excluded,
                        1.0::REAL as rank,
                        1.0::REAL as similarity_score
                    FROM datasets_intelligence di
                    WHERE di.dataset_id::TEXT = $1 AND di.excluded = FALSE
                """, dataset_id)

                if not results:
                    return f"""# 🔍 Dataset Lookup by ID

**Dataset ID**: `{dataset_id}`
**Result**: Not found

**Possible reasons**:
- Dataset ID does not exist
- Dataset has been excluded from search
- Incorrect dataset ID format

**Suggestion**: Try using `discover_datasets("search term")` to find available datasets."""

            elif dataset_name is not None:
                # Exact dataset name lookup
                semantic_logger.info(f"dataset lookup by name | dataset_name:{dataset_name}")

                results = await conn.fetch("""
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
                        di.excluded,
                        1.0::REAL as rank,
                        1.0::REAL as similarity_score
                    FROM datasets_intelligence di
                    WHERE di.dataset_name = $1 AND di.excluded = FALSE
                """, dataset_name)

                if not results:
                    return f"""# 🔍 Dataset Lookup by Name

**Dataset Name**: `{dataset_name}`
**Result**: Not found

**Possible reasons**:
- Dataset name does not exist
- Dataset has been excluded from search
- Name does not match exactly (case-sensitive)

**Suggestion**: Try using `discover_datasets("partial name")` to search for similar datasets."""

            elif not query:
                # No search criteria provided
                return """# ⚠️ Dataset Discovery Error

**Issue**: No search criteria provided

**Required**: At least one of the following must be provided:
- `query`: Search term for finding datasets
- `dataset_id`: Exact dataset ID to lookup
- `dataset_name`: Exact dataset name to lookup

**Examples**:
```python
discover_datasets("kubernetes logs")
discover_datasets(dataset_id="42161740")
discover_datasets(dataset_name="Kubernetes Explorer/Kubernetes Logs")
```"""
            else:
                # Perform full-text search (existing logic)
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
    Discover observability metrics with intelligent categorization and complete usage guidance.

    This tool searches through 491+ analyzed metrics and returns comprehensive information
    including dataset IDs, dimensions, value ranges, and query patterns.

    📊 METRICS-SPECIFIC GUIDANCE
    ═════════════════════════════

    WHAT METRICS PROVIDE:
    - Error FREQUENCIES and counts (not actual error messages)
    - Performance metrics (latency, throughput, resource utilization)
    - System health indicators (availability, saturation, errors)

    WHAT METRICS DON'T PROVIDE:
    - Actual error messages or stack traces → Use discover_datasets() for logs
    - Detailed request context → Use discover_datasets() for trace/span data

    📈 METRIC TYPES
       - Counter: Cumulative values that only increase (error_count, request_total)
       - Gauge: Point-in-time values that can go up/down (cpu_usage, memory_bytes, queue_depth)
       - Histogram: Distribution data with buckets (latency_bucket, response_time_bucket)

    📍 COMMON DIMENSIONS (Group-By Fields)
       - Service identifiers: service_name, endpoint, method
       - Infrastructure: namespace, pod, container, node, zone
       - Status indicators: status_code, error_type, severity
       - Check "Dimensions" section in results for available groupings

    ⏱️ TIME UNITS (Same as datasets!)
       - Fields without suffix (duration, elapsed) = NANOSECONDS
       - Fields with suffix (duration_ms, latency_s) = as labeled
       - Always check sample values and convert if needed

    🔍 VALUE RANGES - Use for filtering and anomaly detection
       - "Range: 0-100" indicates percentage metrics
       - "Range: 0-1000000000" indicates nanosecond duration metrics
       - Check ranges to understand metric scale and units

    TYPICAL WORKFLOWS
    ─────────────────
    1. ERROR INVESTIGATION
       discover_metrics("error rate") → Get error frequencies by service
       ↓
       discover_datasets("error logs") → Get actual error messages
       ↓
       Correlate: Which services have highest error rates + what errors occur

    2. PERFORMANCE ANALYSIS
       discover_metrics("latency duration") → Get p95/p99 latency by endpoint
       ↓
       execute_opal_query() → Filter for slow requests above threshold
       ↓
       discover_datasets("traces") → Analyze slow request traces

    3. RESOURCE MONITORING
       discover_metrics("cpu memory") → Get resource utilization metrics
       ↓
       execute_opal_query() → Aggregate by service and time window
       ↓
       Identify: Services approaching resource limits

    Args:
        query: Search query (e.g., "error rate", "cpu usage", "database latency", "service performance")
        max_results: Maximum metrics to return (1-50, default: 20)
        category_filter: Filter by business category (Infrastructure, Application, Database, Storage, Network, Monitoring)
        technical_filter: Filter by technical category (Error, Latency, Count, Performance, Resource, Throughput, Availability)

    Returns:
        Formatted metrics information including:
        - Metric name and dataset ID for querying
        - Purpose and typical usage patterns
        - Common dimensions for group-by operations
        - Value ranges for context and filtering
        - Query pattern examples
        - Last seen timestamp

    Examples:
        # Error analysis (frequencies only)
        discover_metrics("error rate service")

        # Resource monitoring
        discover_metrics("cpu memory usage", category_filter="Infrastructure")

        # Performance investigation
        discover_metrics("latency", technical_filter="Latency", max_results=10)

        # Multi-category search
        discover_metrics("database throughput")

    Performance:
        - Search queries: 200-500ms
    """
    try:
        import asyncpg
        import json
        from typing import List, Dict, Any

        # Log the semantic search operation
        semantic_logger.info(f"metrics search | query:'{query}' | max_results:{max_results} | filters:{category_filter or technical_filter}")

        # Database connection using individual parameters (same as working scripts)
        db_password = os.getenv('SEMANTIC_GRAPH_PASSWORD')
        if not db_password:
            raise ValueError("SEMANTIC_GRAPH_PASSWORD environment variable must be set")

        db_config = {
            'host': os.getenv('POSTGRES_HOST', 'localhost'),
            'port': int(os.getenv('POSTGRES_PORT', '5432')),
            'database': os.getenv('POSTGRES_DB', 'semantic_graph'),
            'user': os.getenv('POSTGRES_USER', 'semantic_graph'),
            'password': db_password
        }

        # Validate parameters
        max_results = min(max(1, max_results), 50)  # Clamp between 1 and 50

        # Connect to database using individual parameters (avoids SSL/TLS DNS issues)
        conn = await asyncpg.connect(**db_config)
        
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
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8000)
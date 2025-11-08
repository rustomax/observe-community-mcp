#!/usr/bin/env python3
"""
Observe MCP Server
A Model Context Protocol server that provides access to Observe API functionality
using organized modules for better maintainability and reusability.
"""

import os
import sys
from typing import Dict, Any, Optional, List, Union, Tuple

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

# Import Gemini-powered document search
from src.observe.gemini_search import search_docs_gemini as search_docs

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


# Input validation utility to prevent DoS via large payloads (H-INPUT-2)
def validate_input_size(value: Optional[str], param_name: str, max_bytes: int) -> None:
    """
    Validate input parameter size to prevent DoS attacks.

    Args:
        value: Input string to validate
        param_name: Parameter name for error messages
        max_bytes: Maximum allowed size in bytes

    Raises:
        ValueError: If input exceeds maximum size
    """
    if value is None:
        return

    size_bytes = len(value.encode('utf-8'))
    if size_bytes > max_bytes:
        max_kb = max_bytes / 1024
        actual_kb = size_bytes / 1024
        raise ValueError(
            f"{param_name} exceeds maximum size limit. "
            f"Maximum: {max_kb:.1f}KB, Actual: {actual_kb:.1f}KB. "
            f"Please reduce the size of your input."
        )


# Import OPAL query validation from shared module
from src.observe.opal_validation import validate_opal_query_structure

# Legacy comment for reference:
# OPAL query validation utility to prevent injection and catch errors early (H-INPUT-1)
# Function has been moved to src/observe/opal_validation.py to avoid circular imports

@mcp.tool()
@requires_scopes(['admin', 'write', 'read'])
@trace_mcp_tool(tool_name="execute_opal_query", record_args=True, record_result=False)
async def execute_opal_query(ctx: Context, query: str, dataset_id: str = None, primary_dataset_id: str = None, secondary_dataset_ids: Optional[str] = None, dataset_aliases: Optional[str] = None, time_range: Optional[str] = "1h", start_time: Optional[str] = None, end_time: Optional[str] = None, format: Optional[str] = "csv", timeout: Optional[float] = None) -> str:
    """
    Execute OPAL (Observe Processing and Analytics Language) queries on datasets.

    MANDATORY 2-STEP WORKFLOW (Skipping Step 1 = "field not found" errors):
    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    Step 1: discover("search term") → Get dataset_id + EXACT field names + dimensions
    Step 2: execute_opal_query(query, dataset_id) → Use ONLY fields from Step 1

    CRITICAL: METRICS REQUIRE SPECIAL SYNTAX
    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    Metric queries MUST use align verb - m() function ONLY works inside align!

    WILL ALWAYS FAIL:
      filter m("metric_name") > 0              # m() outside align
      statsby sum(m("metric_name"))            # m() without align

    REQUIRED PATTERN:
      align 5m, value:sum(m("metric_name"))    # align + m()
      | aggregate total:sum(value), group_by(service_name)
      | filter total > 100                     # filter AFTER aggregate

    TDIGEST METRICS (span_duration_5m, etc.):
      align 5m, combined: tdigest_combine(m_tdigest("metric"))
      | aggregate agg: tdigest_combine(combined), group_by(field)
      | make_col p95: tdigest_quantile(agg, 0.95)

      WARNING: Must use m_tdigest() not m(), must use tdigest_combine() before tdigest_quantile()

    COMMON QUERY PATTERNS (90% of use cases):
    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    DATASETS (Logs/Spans): filter → [make_col] → statsby/timechart
      # Error analysis by service
      filter <BODY_FIELD> ~ error
      | make_col service:string(resource_attributes."service.name")
      | statsby error_count:count(), group_by(service)
      | sort desc(error_count)

      # Time-series analysis
      filter <BODY_FIELD> ~ error
      | timechart count(), group_by(string(resource_attributes."k8s.namespace.name"))

    METRICS: align → aggregate → [filter]
      # Basic metric aggregation (use discover() to find metric names + dimensions)
      align 5m, errors:sum(m("<METRIC_NAME>"))
      | aggregate total_errors:sum(errors), group_by(service_name)
      | filter total_errors > 10
      | sort desc(total_errors)

      # P95/P99 latency with tdigest (for duration/latency metrics)
      align 5m, combined:tdigest_combine(m_tdigest("<TDIGEST_METRIC_NAME>"))
      | aggregate agg:tdigest_combine(combined), group_by(service_name)
      | make_col p95:tdigest_quantile(agg, 0.95), p99:tdigest_quantile(agg, 0.99)
      | make_col p95_ms:p95/1000000
      | sort desc(p95_ms)

    FIELD QUOTING (Field names with dots):
    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    WRONG: resource_attributes.k8s.namespace.name
       (OPAL interprets as: resource_attributes → k8s → namespace → name)

    CORRECT: resource_attributes."k8s.namespace.name"
       (Single field name containing dots - MUST quote the field name)

    Rule: If field name contains dots, wrap it in quotes: object."field.with.dots"

    COMMON FAILURES - DON'T DO THIS:
    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    1. Forgetting field quoting → Quote field names with dots
    2. SQL syntax (CASE/WHEN, -field) → Use if(), desc(field)
    3. count_if() function → Use make_col + if() + sum() pattern
    4. m() outside align verb → Metrics REQUIRE align + m() + aggregate
    5. Missing parentheses → group_by(field), desc(field), if(cond,val,val)

    CORE OPAL SYNTAX:
    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    filter: field ~ keyword, field = value, field > 100
    make_col: new_field:expression, nested:object."field.name"
    statsby: metric:count(), metric:sum(field), group_by(dimension)
    sort: desc(field), asc(field)  [NOT sort -field]
    limit: limit 10
    Conditionals: if(condition, true_value, false_value)
    Text Search: field ~ keyword (single token), field ~ <word1 word2> (multiple tokens, AND)
    OR Search: contains(field,"w1") or contains(field,"w2")

    TIME UNITS (Check sample values in discover()):
    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    No suffix (timestamp, duration) = NANOSECONDS → divide by 1M for ms
    With suffix (_ms, _s) = as labeled
      • 19 digits (1760201545280843522) = nanoseconds
      • 13 digits (1758543367916) = milliseconds

    DON'T EXIST IN OPAL:
    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    count_if() → Use: make_col flag:if(condition,1,0) | statsby sum(flag)
    pick → Use: make_col to select fields, or reference directly
    sort -field → Use: sort desc(field)
    SQL CASE/WHEN → Use: if(condition, true_val, false_val)

    EXAMPLES (Replace <FIELD> with actual names from discover()):
    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # Basic search
    filter <BODY_FIELD> ~ error | limit 10

    # Nested fields with dots (QUOTE the field name)
    filter resource_attributes."k8s.namespace.name" = "default" | limit 10
    make_col ns:resource_attributes."k8s.namespace.name" | filter ns = "default"

    # Conditional counting (NO count_if!)
    make_col is_error:if(contains(<BODY_FIELD>, "error"), 1, 0)
    | statsby error_count:sum(is_error), total:count(), group_by(service)
    | sort desc(error_count)

    # Multi-keyword search
    filter <BODY_FIELD> ~ <error exception>    # Both tokens present (AND)
    filter contains(<BODY_FIELD>,"error") or contains(<BODY_FIELD>,"warn")  # Either (OR)

    # Time-based with nanosecond conversion
    filter <TIME_FIELD> > @"1 hour ago"
    | make_col duration_ms:<NANO_FIELD> / 1000000
    | filter duration_ms > 500 | limit 100

    MULTI-DATASET JOINS (Joining two or more datasets):
    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    CRITICAL: Join syntax does NOT include dataset reference as first argument!

    CORRECT SYNTAX:
      join on(field=@alias.field), new_col:@alias.column

    WRONG SYNTAX (will fail):
      join @alias, on(field=@alias.field), new_col:@alias.column  # Extra @alias argument!

    # Example: Join spans with span events to get error details
    # Dataset 1 (primary): Spans with OPAL queries in attributes
    # Dataset 2 (secondary): Span Events with error messages

    primary_dataset_id = "42160967"  # Spans
    secondary_dataset_ids = '["42160966"]'  # Span Events
    dataset_aliases = '{"events": "42160966"}'

    query = '''
    filter service_name = "my-service"
    | filter span_name = "http_request"
    | make_col request_span_id:span_id
    | join on(request_span_id=@events.span_id),
        event_type:@events.event_name,
        error_msg:@events.attributes."error.message"
    | filter event_type = "error_event"
    | make_col error_message:string(error_msg)
    | limit 10
    '''

    # Key points:
    # 1. Use secondary_dataset_ids as JSON array: '["42160966"]'
    # 2. Use dataset_aliases to name datasets: '{"events": "42160966"}'
    # 3. Reference secondary dataset with @alias in join
    # 4. No @alias before on() predicate!

    Args:
        query: OPAL query (use syntax reference above)
        dataset_id: DEPRECATED - use primary_dataset_id
        primary_dataset_id: Dataset ID from discover() (searches both datasets and metrics)
        secondary_dataset_ids: JSON array for joins: '["44508111"]'
        dataset_aliases: JSON object for joins: '{"volumes": "44508111"}'
        time_range: "1h", "24h", "7d", "30d"
        start_time: ISO format "2024-01-20T16:20:00Z"
        end_time: ISO format "2024-01-20T17:20:00Z"
        format: "csv" (default) or "ndjson"
        timeout: Seconds (default: 30s)

    Returns:
        Query results (CSV: first 1000 rows, or limited by query)

    Need help with unknown syntax errors? Call get_relevant_docs("opal <keyword>")
    """
    import json

    # Validate input sizes to prevent DoS attacks (H-INPUT-2)
    validate_input_size(query, "query", 10 * 1024)  # 10KB max for OPAL queries
    validate_input_size(dataset_id, "dataset_id", 1024)  # 1KB max
    validate_input_size(primary_dataset_id, "primary_dataset_id", 1024)  # 1KB max
    validate_input_size(secondary_dataset_ids, "secondary_dataset_ids", 100 * 1024)  # 100KB max for JSON
    validate_input_size(dataset_aliases, "dataset_aliases", 100 * 1024)  # 100KB max for JSON

    # Validate OPAL query structure and apply auto-fix transformations (H-INPUT-1)
    validation_result = validate_opal_query_structure(query, time_range=time_range)
    if not validation_result.is_valid:
        return f"OPAL Query Validation Error: {validation_result.error_message}"

    # Use transformed query if auto-fixes were applied
    original_query = query
    if validation_result.transformed_query:
        opal_logger.info(f"Using auto-fixed query (applied {len(validation_result.transformations)} transformations)")
        query = validation_result.transformed_query

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

    # Normalize time_range: accept bare numbers (assume hours) and convert days to hours
    # Examples: "24" -> "24h", "7d" -> "168h", "1.5" -> "1.5h"
    normalized_time_range = time_range
    if time_range:
        time_str = str(time_range).strip()
        try:
            # Handle days conversion: "7d" -> "168h" (7 * 24)
            if time_str.endswith('d'):
                days = float(time_str[:-1])
                hours = days * 24
                normalized_time_range = f"{hours}h"
                opal_logger.info(f"time_range normalization | original:'{time_range}' | normalized:'{normalized_time_range}' | reason:days_to_hours")
            # Handle bare numbers: "24" -> "24h"
            elif time_str and not any(time_str.endswith(unit) for unit in ['h', 'm', 's', 'w']):
                float(time_str)  # Validate it's numeric
                normalized_time_range = f"{time_str}h"
                opal_logger.info(f"time_range normalization | original:'{time_range}' | normalized:'{normalized_time_range}' | reason:bare_number")
        except ValueError:
            # Not a valid number, keep as-is (might be a valid format or will error downstream)
            pass

    result = await observe_execute_opal_query(
        query=query,
        dataset_id=dataset_id,
        primary_dataset_id=primary_dataset_id,
        secondary_dataset_ids=parsed_secondary_dataset_ids,
        dataset_aliases=parsed_dataset_aliases,
        time_range=normalized_time_range,
        start_time=start_time,
        end_time=end_time,
        format=format,
        timeout=timeout
    )

    # Append transformation feedback if auto-fixes were applied at this level
    # (Note: inner function may also apply transformations, which will have their own feedback)
    if validation_result.transformations:
        transformation_notes = "\n\n" + "="*60 + "\n"
        transformation_notes += "AUTO-FIX APPLIED - Query Transformations\n"
        transformation_notes += "="*60 + "\n\n"
        for i, transformation in enumerate(validation_result.transformations, 1):
            transformation_notes += f"{transformation}\n\n"
        transformation_notes += "The query above was automatically corrected and executed successfully.\n"
        transformation_notes += "Please use the corrected syntax in future queries.\n"
        transformation_notes += "="*60
        result = result + transformation_notes

    return result



@mcp.tool()
@requires_scopes(['admin', 'read'])
@trace_mcp_tool(tool_name="get_relevant_docs", record_args=True, record_result=False)
async def get_relevant_docs(ctx: Context, query: str, n_results: int = 5) -> str:
    """
    Search Observe documentation using Gemini Search for OPAL syntax and platform guidance.

    This tool uses Google's Gemini AI with search grounding to find relevant, up-to-date
    documentation from docs.observeinc.com about OPAL syntax, functions, features, and best practices.

    WHEN YOU MUST USE THIS TOOL
    ═══════════════════════════════════════════════════════════════════════════════════

    MANDATORY: Call this tool if you receive ANY of these errors from execute_opal_query:
       • "field not found" → Search for field access syntax
       • "invalid syntax" → Search for the OPAL construct you're trying to use
       • "unknown function" → Search for function name and proper usage
       • "parse error" → Search for syntax of the operation that failed
       • Any other query execution failure → Search for error keywords

    RECOMMENDED: Call BEFORE attempting these complex operations:
       • Multi-dataset joins
       • Time bucketing or window functions
       • Advanced aggregations beyond statsby
       • Regex or pattern matching
       • Custom operators or functions you haven't used before

    ERROR RECOVERY WORKFLOW
    ─────────────────────────────────────────────────────────────────────────────────
    execute_opal_query() fails
            ↓
    get_relevant_docs("error message keywords" or "feature name")
            ↓
    Review official syntax from documentation
            ↓
    Retry execute_opal_query() with corrected syntax

    SEARCH TIPS:
    ───────────────
    • Use specific error keywords: "statsby syntax", "join datasets"
    • Include OPAL in your search: "OPAL filter operators"
    • Search for function names directly: "make_col examples"

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
        - Search time: 1-3 seconds (includes web search + AI processing)
        - Returns AI-curated documentation excerpts with citations
        - Rate limited to 400 requests per day (Gemini Tier 1 limit)
    """
    # Validate input sizes to prevent DoS attacks (H-INPUT-2)
    validate_input_size(query, "query", 1024)  # 1KB max for search queries

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
        return f"Error retrieving relevant documents: {str(e)}. Make sure GEMINI_API_KEY is set in your environment."


@mcp.tool()
@requires_scopes(['admin', 'read'])
@trace_mcp_tool(tool_name="discover", record_args=True, record_result=False)
async def discover(
    ctx: Context,
    query: str = "",
    dataset_id: Optional[str] = None,
    dataset_name: Optional[str] = None,
    metric_name: Optional[str] = None,
    result_type: Optional[str] = None,
    max_results: int = 20,
    business_category_filter: Optional[str] = None,
    technical_category_filter: Optional[str] = None,
    interface_filter: Optional[str] = None
) -> str:
    """
    Unified discovery tool for datasets and metrics in the Observe platform.

    ⚠️ CRITICAL: 2-PHASE WORKFLOW REQUIRED ⚠️
    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    Phase 1: SEARCH MODE (lightweight browsing)
      discover("error service") → Returns names, IDs, purposes
      NO field names, NO dimensions shown - context efficient!

    Phase 2: DETAIL MODE (complete schema) - ⚠️ REQUIRED BEFORE QUERIES
      discover(dataset_id="...") → ALL fields with types and samples
      discover(metric_name="...") → ALL dimensions with cardinality
      This phase is MANDATORY before writing any queries!

    YOU MUST COMPLETE PHASE 2 BEFORE CALLING execute_opal_query()!
    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    WHY 2 PHASES?
    • Context efficiency: Browse 20+ options without bloat
    • Natural workflow: Search → Select → Detail → Query
    • Complete information: Get full schemas only when needed
    • Prevents errors: Field names verified before query construction

    WHAT YOU GET IN EACH MODE:
    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    SEARCH MODE (Phase 1):
    📊 Datasets: Names, IDs, categories, purposes
    📈 Metrics: Names, IDs, categories, purposes
    ⛔ NOT included: Fields, dimensions, schemas (use Phase 2!)

    DETAIL MODE (Phase 2):
    📊 Datasets: Complete field list with types, samples, nested paths
    📈 Metrics: ALL dimensions with cardinality, value ranges, examples
    ✅ Everything needed to write queries correctly

    Args:
        query: Search term (e.g., "error service", "kubernetes logs", "cpu usage")
        dataset_id: Exact dataset ID for detailed lookup
        dataset_name: Exact dataset name for lookup
        metric_name: Exact metric name for detailed lookup
        result_type: Filter results - "dataset", "metric", or None (both)
        max_results: Maximum results to return (default: 20)
        business_category_filter: Infrastructure, Application, Database, etc.
        technical_category_filter: Logs, Metrics, Traces, Events, etc.
        interface_filter: log, metric, otel_span, etc.

    Returns:
        Formatted results with clear sections for datasets and metrics

    Examples:
        # PHASE 1: Search mode (browse available options)
        discover("error service")          # See what exists
        discover("latency", result_type="metric")  # Only metrics
        discover("kubernetes", business_category_filter="Infrastructure")

        # PHASE 2: Detail mode (REQUIRED before queries - get complete schema)
        discover(dataset_id="42161740")    # ALL fields for this dataset
        discover(metric_name="span_error_count_5m")  # ALL dimensions for this metric

        # Typical workflow:
        # 1. discover("errors") → browse options
        # 2. discover(dataset_id="42161740") → get field list
        # 3. execute_opal_query(...) → write query with correct fields

    Performance:
        - Search queries: 200-500ms, shows 10-20 results
        - Detail lookups: <100ms, shows complete schemas
    """
    # Validate input sizes to prevent DoS attacks (H-INPUT-2)
    validate_input_size(query, "query", 1024)
    validate_input_size(dataset_id, "dataset_id", 1024)
    validate_input_size(dataset_name, "dataset_name", 1024)
    validate_input_size(metric_name, "metric_name", 1024)
    validate_input_size(result_type, "result_type", 1024)
    validate_input_size(business_category_filter, "business_category_filter", 1024)
    validate_input_size(technical_category_filter, "technical_category_filter", 1024)
    validate_input_size(interface_filter, "interface_filter", 1024)

    try:
        import asyncpg
        import json
        from typing import List, Dict, Any

        # Log the discovery operation
        semantic_logger.info(f"unified discovery | query:'{query}' | dataset_id:{dataset_id} | dataset_name:{dataset_name} | metric_name:{metric_name} | result_type:{result_type} | max_results:{max_results}")

        # Database connection
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

        # Validate and normalize parameters
        max_results = min(max(1, max_results), 50)
        should_fetch_datasets = (result_type is None or result_type == "dataset")
        should_fetch_metrics = (result_type is None or result_type == "metric")

        # Connect to database
        conn = await asyncpg.connect(**db_config)

        try:
            dataset_results = []
            metric_results = []
            is_detail_mode = False

            # EXACT LOOKUPS (Detail Mode)
            if dataset_id is not None:
                is_detail_mode = True
                semantic_logger.info(f"exact dataset lookup | dataset_id:{dataset_id}")
                dataset_results = await conn.fetch("""
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
                        1.0::REAL as rank
                    FROM datasets_intelligence di
                    WHERE di.dataset_id::TEXT = $1 AND di.excluded = FALSE
                """, dataset_id)

            elif dataset_name is not None:
                is_detail_mode = True
                semantic_logger.info(f"exact dataset lookup | dataset_name:{dataset_name}")
                dataset_results = await conn.fetch("""
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
                        1.0::REAL as rank
                    FROM datasets_intelligence di
                    WHERE di.dataset_name = $1 AND di.excluded = FALSE
                """, dataset_name)

            elif metric_name is not None:
                is_detail_mode = True
                semantic_logger.info(f"exact metric lookup | metric_name:{metric_name}")
                metric_results = await conn.fetch("""
                    SELECT
                        mi.dataset_id::TEXT,
                        mi.metric_name,
                        mi.dataset_name,
                        mi.metric_type,
                        mi.description,
                        mi.common_dimensions,
                        mi.sample_dimensions,
                        mi.value_type,
                        mi.value_range,
                        mi.data_frequency,
                        mi.last_seen,
                        mi.inferred_purpose,
                        mi.typical_usage,
                        mi.business_categories,
                        mi.technical_category,
                        mi.query_patterns,
                        mi.common_fields,
                        mi.nested_field_paths,
                        1.0::REAL as rank
                    FROM metrics_intelligence mi
                    WHERE mi.metric_name = $1 AND mi.excluded = FALSE
                    LIMIT 1
                """, metric_name)

            # SEARCH MODE (query provided)
            elif query:
                # Search datasets if requested
                if should_fetch_datasets:
                    search_terms = query.lower().split()
                    search_conditions = []
                    params = []
                    param_idx = 1

                    for term in search_terms:
                        search_conditions.append(f"di.search_vector @@ plainto_tsquery('english', ${param_idx})")
                        params.append(term)
                        param_idx += 1

                    if not search_conditions:
                        search_conditions = [f"di.search_vector @@ plainto_tsquery('english', ${param_idx})"]
                        params.append(query)
                        param_idx += 1

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
                            ts_rank(di.search_vector, plainto_tsquery('english', $1))::REAL as rank
                        FROM datasets_intelligence di
                        WHERE di.excluded = FALSE AND {where_clause}
                        ORDER BY rank DESC
                        LIMIT ${limit_param}
                    """

                    dataset_results = await conn.fetch(query_sql, *params)

                # Search metrics if requested
                if should_fetch_metrics:
                    metric_results = await conn.fetch("""
                        SELECT * FROM search_metrics_enhanced($1, $2, $3, $4, $5)
                    """, query, max_results, business_category_filter, technical_category_filter, 0.2)

            else:
                return """# Discovery Error

**Issue**: No search criteria provided

**Required**: At least one of the following:
- `query`: Search term
- `dataset_id`: Exact dataset ID
- `dataset_name`: Exact dataset name
- `metric_name`: Exact metric name

**Examples**:
```python
discover("error service")
discover(dataset_id="42161740")
discover(metric_name="span_error_count_5m")
```"""

            # Check if we found anything
            if not dataset_results and not metric_results:
                search_term = query or dataset_id or dataset_name or metric_name
                total_datasets = await conn.fetchval("SELECT COUNT(*) FROM datasets_intelligence WHERE excluded = FALSE")
                total_metrics = await conn.fetchval("SELECT COUNT(*) FROM metrics_intelligence WHERE excluded = FALSE")

                return f"""# Discovery Results

**Search**: "{search_term}"
**Found**: 0 results

**Suggestions**:
- Try broader search terms
- Remove filters to see all results
- Check spelling and try alternative terms

**Available in database**:
- {total_datasets} datasets
- {total_metrics} metrics

**Examples**:
```python
discover("error")          # Broad search
discover("kubernetes")     # Infrastructure search
discover("latency")        # Performance metrics
```"""

            # Format results
            output_parts = []

            # Header
            mode_indicator = "**Mode**: Detail (Complete Schema)" if is_detail_mode else "**Mode**: Search (Lightweight Browsing - NO schemas shown)"

            if query:
                output_parts.append(f"# Discovery Results for \"{query}\"\n")
            else:
                output_parts.append(f"# Discovery Results\n")

            output_parts.append(f"{mode_indicator}\n")
            output_parts.append(f"**Found**: {len(dataset_results)} datasets, {len(metric_results)} metrics\n")

            # DATASETS SECTION
            if dataset_results:
                output_parts.append("\n" + "=" * 80)
                output_parts.append("\n## 📊 Datasets (LOG/SPAN/RESOURCE Interfaces)\n")
                output_parts.append("**Query Pattern**: Standard OPAL (filter, make_col, statsby)\n")

                for i, row in enumerate(dataset_results, 1):
                    if is_detail_mode:
                        output_parts.append(_format_dataset_detail(row, i, json))
                    else:
                        output_parts.append(_format_dataset_summary(row, i, json))

            # METRICS SECTION
            if metric_results:
                output_parts.append("\n" + "=" * 80)
                output_parts.append("\n## 📈 Metrics (METRIC Interface)\n")
                output_parts.append("**Query Pattern**: align + m() + aggregate (REQUIRED!)\n")

                for i, row in enumerate(metric_results, 1):
                    if is_detail_mode:
                        output_parts.append(_format_metric_detail(row, i, json))
                    else:
                        output_parts.append(_format_metric_summary(row, i, json))

            # NEXT STEPS
            output_parts.append("\n" + "=" * 80)
            output_parts.append("\n## Next Steps\n")

            if is_detail_mode:
                output_parts.append("""
**For Datasets**:
1. Use `execute_opal_query(query="...", primary_dataset_id="dataset_id")`
2. Copy field names exactly as shown (case-sensitive!)
3. Quote nested fields with dots: `resource_attributes."k8s.namespace.name"`

**For Metrics**:
1. Use `execute_opal_query()` with align + m() + aggregate pattern
2. Use dimensions shown above for group_by operations
3. See example queries in each metric's details
""")
            else:
                output_parts.append(f"""
💡 **Remember**: Get complete schema before querying → `discover(dataset_id="...")` or `discover(metric_name="...")`
""")

            result = "\n".join(output_parts)
            semantic_logger.info(f"unified discovery complete | datasets:{len(dataset_results)} | metrics:{len(metric_results)}")

            return result

        finally:
            await conn.close()

    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        semantic_logger.error(f"discovery error | {str(e)} | {error_details}")
        return f"""# Discovery Error

**Error**: {str(e)}

**Troubleshooting**:
- Check database connectivity
- Verify SEMANTIC_GRAPH_PASSWORD is set
- Try simpler search terms
- Check the server logs for details

**Support**: If the issue persists, contact support with this error message."""


# Helper functions for formatting (defined at module level for use by discover tool)
def _format_dataset_summary(row: Dict, index: int, json) -> str:
    """Format lightweight dataset summary for search/discovery."""
    combined_score = row.get('rank', 0.0)
    interfaces_str = ', '.join(row['interface_types']) if row.get('interface_types') else 'unknown'
    business_cats = json.loads(row['business_categories']) if row.get('business_categories') else ['Unknown']

    return f"""
### {index}. {row['dataset_name']}
**ID**: `{row['dataset_id']}`
**Category**: {', '.join(business_cats)} / {row.get('technical_category', 'Unknown')}
**Interfaces**: {interfaces_str}
**Purpose**: {row.get('inferred_purpose', 'N/A')}
**Relevance**: {combined_score:.3f}
"""


def _format_dataset_detail(row: Dict, index: int, json) -> str:
    """Format complete dataset details with full schema."""
    try:
        query_patterns = json.loads(row.get('query_patterns', '[]')) if row.get('query_patterns') else []
        nested_field_paths = json.loads(row.get('nested_field_paths', '{}')) if row.get('nested_field_paths') else {}
        common_use_cases = row.get('common_use_cases', []) or []
    except (json.JSONDecodeError, TypeError):
        query_patterns = []
        nested_field_paths = {}
        common_use_cases = []

    interfaces_str = ', '.join(row['interface_types']) if row.get('interface_types') else 'unknown'
    business_cats = json.loads(row['business_categories']) if row.get('business_categories') else ['Unknown']

    # Build schema information
    schema_str = "\n**COMPLETE SCHEMA**:\n"
    all_fields_info = {}

    # Add top-level fields
    if row.get('key_fields'):
        for field in row['key_fields']:
            if not field.startswith('link_'):
                all_fields_info[field] = {"type": "unknown", "samples": []}

    # Add nested fields
    if nested_field_paths:
        for field_path, field_info in nested_field_paths.items():
            if not field_path.startswith('link_'):
                if isinstance(field_info, dict):
                    all_fields_info[field_path] = {
                        "type": field_info.get("type", "unknown"),
                        "samples": field_info.get("sample_values", [])[:2]
                    }

    # Format fields
    top_level = [f for f in all_fields_info.keys() if '.' not in f]
    nested = [f for f in all_fields_info.keys() if '.' in f]

    if top_level:
        schema_str += "\n**Top-Level Fields**:\n"
        for field in sorted(top_level):
            info = all_fields_info[field]
            type_str = f"({info['type']})" if info['type'] != 'unknown' else ""
            samples_str = f" → {info['samples']}" if info['samples'] else ""
            schema_str += f"  • `{field}` {type_str}{samples_str}\n"

    if nested:
        schema_str += "\n**Nested Fields (MUST QUOTE!)**:\n"
        for field in sorted(nested):
            info = all_fields_info[field]
            type_str = f"({info['type']})" if info['type'] != 'unknown' else ""
            samples_str = f" → {info['samples']}" if info['samples'] else ""
            schema_str += f"  • `{field}` {type_str}{samples_str}\n"

    # Query example
    query_ex = ""
    if query_patterns and len(query_patterns) > 0:
        pattern = query_patterns[0]
        if isinstance(pattern, dict) and pattern.get('pattern'):
            query_ex = f"\n**Query Example**:\n```\n{pattern['pattern']}\n```\n"

    # Usage scenarios
    usage_str = ""
    if common_use_cases:
        usage_str = f"\n**Common Uses**: {', '.join(common_use_cases[:2])}\n"

    return f"""
### {index}. {row['dataset_name']}
**ID**: `{row['dataset_id']}`
**Category**: {', '.join(business_cats)} / {row.get('technical_category', 'Unknown')}
**Interfaces**: {interfaces_str}
**Purpose**: {row.get('inferred_purpose', 'N/A')}
**Usage**: {row.get('typical_usage', 'N/A')}
{schema_str}{query_ex}{usage_str}**Frequency**: {row.get('data_frequency', 'unknown')}
"""


def _format_metric_summary(row: Dict, index: int, json) -> str:
    """Format minimal metric summary for search/discovery - NO dimensions shown."""
    combined_score = max(row.get('rank', 0.0), row.get('similarity_score', 0.0))
    business_cats = json.loads(row.get('business_categories', '[]')) if row.get('business_categories') else ['Unknown']

    return f"""
### {index}. {row['metric_name']}
**Dataset**: {row.get('dataset_name', 'Unknown')}
**ID**: `{row['dataset_id']}`
**Category**: {', '.join(business_cats)} / {row.get('technical_category', 'Unknown')}
**Purpose**: {row.get('inferred_purpose', 'N/A')}
**Relevance**: {combined_score:.3f}
"""


def _format_metric_detail(row: Dict, index: int, json) -> str:
    """Format complete metric details with full dimensions."""
    try:
        dimensions = json.loads(row.get('common_dimensions', '{}')) if row.get('common_dimensions') else {}
        value_range = json.loads(row.get('value_range', '{}')) if row.get('value_range') else {}
        query_patterns = json.loads(row.get('query_patterns', '[]')) if row.get('query_patterns') else []
    except (json.JSONDecodeError, TypeError):
        dimensions = {}
        value_range = {}
        query_patterns = []

    business_cats = json.loads(row.get('business_categories', '[]')) if row.get('business_categories') else ['Unknown']

    # Format dimensions with cardinality (CRITICAL - addresses #1 pain point!)
    dim_text = "\n**✨ AVAILABLE DIMENSIONS (for group_by)**:\n"
    dim_keys = [k for k in dimensions.keys() if not k.startswith('link_')]
    if dim_keys:
        for dim in sorted(dim_keys):
            dim_info = dimensions[dim]
            if isinstance(dim_info, dict):
                cardinality = dim_info.get('unique_count', 'unknown')
                dim_text += f"  • `{dim}` ({cardinality} unique values)\n"
            else:
                dim_text += f"  • `{dim}`\n"
    else:
        dim_text += "  • No dimensions (metric is pre-aggregated)\n"

    # Value range
    range_text = ""
    if value_range and isinstance(value_range, dict):
        if 'min' in value_range and 'max' in value_range:
            range_text = f"\n**Value Range**: {value_range.get('min', 'N/A')} - {value_range.get('max', 'N/A')}\n"

    # Query example
    query_ex = ""
    if query_patterns and len(query_patterns) > 0:
        pattern = query_patterns[0]
        pattern_text = pattern.get('pattern', '') if isinstance(pattern, dict) else str(pattern)
        if pattern_text:
            query_ex = f"\n**Query Example**:\n```\n{pattern_text}\n```\n"

    # Last seen
    last_seen = row.get('last_seen', 'Unknown')
    if hasattr(last_seen, 'strftime'):
        last_seen = last_seen.strftime('%Y-%m-%d %H:%M')

    metric_type = row.get('metric_type', 'unknown')

    return f"""
### {index}. {row['metric_name']}
**Dataset**: {row.get('dataset_name', 'Unknown')}
**ID**: `{row['dataset_id']}`
**Category**: {', '.join(business_cats)} / {row.get('technical_category', 'Unknown')}
**Type**: {metric_type}
**Purpose**: {row.get('inferred_purpose', 'N/A')}
**Usage**: {row.get('typical_usage', 'N/A')}
{dim_text}{range_text}{query_ex}**Frequency**: {row.get('data_frequency', 'unknown')} | **Last Seen**: {last_seen}
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
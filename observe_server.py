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


# OPAL query validation utility to prevent injection and catch errors early (H-INPUT-1)
def validate_opal_query_structure(query: str) -> Tuple[bool, Optional[str]]:
    """
    Validate OPAL query structure for security and correctness.

    This performs structural validation without full semantic parsing:
    - Validates all verbs in piped sequences against whitelist
    - Checks balanced delimiters (prevents malformed queries)
    - Enforces complexity limits (prevents DoS)

    The Observe API remains the authoritative validator for full semantics.

    Args:
        query: OPAL query string to validate

    Returns:
        Tuple of (is_valid, error_message)

    Raises:
        ValueError: If query structure is invalid
    """
    # Complete list of OPAL functions from https://docs.observeinc.com/en/latest/content/query-language-reference/ListOfOPALFunctions.html
    # 286 functions across 11 categories (Aggregate, Boolean, Misc, Networking, Numeric, Regex, Semistructured, Special, String, Time, Window)
    ALLOWED_FUNCTIONS = {
        'abs', 'any', 'any_not_null', 'append_item', 'arccos_deg', 'arccos_rad', 'arcsin_deg', 'arcsin_rad',
        'arctan_deg', 'arctan_rad', 'array', 'array_agg', 'array_agg_distinct', 'array_contains', 'array_distinct',
        'array_length', 'array_max', 'array_min', 'array_null', 'array_to_string', 'array_union_agg', 'arrays_overlap',
        'asc', 'avg', 'bin_end_time', 'bin_size', 'bin_start_time', 'bool', 'bool_null', 'case', 'ceil', 'check_json',
        'coalesce', 'concat_arrays', 'concat_strings', 'contains', 'cos_deg', 'cos_rad', 'count', 'count_distinct',
        'count_distinct_exact', 'count_regex_matches', 'decode_base64', 'decode_uri', 'decode_uri_component', 'degrees',
        'delta', 'delta_monotonic', 'dense_rank', 'deriv', 'desc', 'detect_browser', 'drop_fields', 'duration',
        'duration_hr', 'duration_min', 'duration_ms', 'duration_null', 'duration_sec', 'editdistance', 'embed_sql_params',
        'encode_base64', 'encode_uri', 'encode_uri_component', 'ends_with', 'eq', 'ewma', 'exp', 'exponential_histogram_null',
        'first', 'first_not_null', 'float64', 'float64_null', 'floor', 'format_time', 'frame', 'frame_exact',
        'frame_following', 'frame_preceding', 'from_milliseconds', 'from_nanoseconds', 'from_seconds', 'get_field',
        'get_item', 'get_jmespath', 'get_regex', 'get_regex_all', 'group_by', 'gt', 'gte', 'hash', 'hash_agg',
        'hash_agg_distinct', 'haversine_distance_km', 'histogram_combine', 'histogram_fraction', 'histogram_null',
        'histogram_quantile', 'if', 'if_null', 'in', 'index_of_item', 'insert_item', 'int64', 'int64_null',
        'int64_to_ipv4', 'int_div', 'intersect_arrays', 'ipv4', 'ipv4_address_in_network', 'ipv4_network_int64',
        'ipv4_to_int64', 'is_null', 'label', 'lag', 'lag_not_null', 'last', 'last_not_null', 'lead', 'lead_not_null',
        'left', 'like', 'ln', 'log', 'lower', 'lpad', 'lt', 'lte', 'ltrim', 'm', 'm_exponential_histogram', 'm_histogram',
        'm_object', 'm_tdigest', 'make_array', 'make_array_range', 'make_fields', 'make_object', 'match_regex', 'max',
        'median', 'median_exact', 'merge_objects', 'metric', 'min', 'mod', 'ne', 'now', 'nullsfirst', 'nullslast',
        'numeric_null', 'object', 'object_agg', 'object_keys', 'object_null', 'on', 'options', 'order_by',
        'otel_exponential_histogram_quantile', 'otel_exponential_histogram_sum', 'otel_histogram_quantile',
        'otel_histogram_sum', 'parse_csv', 'parse_duration', 'parse_hex', 'parse_ip', 'parse_isotime', 'parse_json',
        'parse_kvs', 'parse_timestamp', 'parse_url', 'path_exists', 'percentile', 'percentile_cont', 'percentile_disc',
        'pi', 'pick_fields', 'pivot_array', 'position', 'pow', 'prepend_item', 'primary_key', 'prom_quantile',
        'query_end_time', 'query_start_time', 'radians', 'rank', 'rate', 'regex', 'replace', 'replace_regex', 'right',
        'round', 'row_end_time', 'row_number', 'row_timestamp', 'rpad', 'rtrim', 'same', 'search', 'sha2', 'sin_deg',
        'sin_rad', 'slice_array', 'sort_array', 'split', 'split_part', 'sqrt', 'starts_with', 'stddev', 'string',
        'string_agg', 'string_agg_distinct', 'string_null', 'strlen', 'substring', 'sum', 'tags', 'tan_deg', 'tan_rad',
        'tdigest', 'tdigest_agg', 'tdigest_combine', 'tdigest_null', 'tdigest_quantile', 'timestamp_null', 'to_days',
        'to_hours', 'to_milliseconds', 'to_minutes', 'to_nanoseconds', 'to_seconds', 'to_weeks', 'tokenize',
        'tokenize_part', 'topk_agg', 'trim', 'uniform', 'unpivot_array', 'upper', 'valid_for', 'variant_null',
        'variant_type_name', 'width_bucket', 'window', 'zipf'
    }

    # Common SQL→OPAL translation hints for better error messages
    SQL_FUNCTION_HINTS = {
        'count_if': 'OPAL doesn\'t have count_if(). Use: make_col flag:if(condition,1,0) | statsby sum(flag)',
        'len': 'OPAL doesn\'t have len(). Use: strlen(string) or array_length(array)',
        'length': 'OPAL doesn\'t have length(). Use: strlen(string) or array_length(array)',
        'isnull': 'OPAL doesn\'t have isnull(). Use: is_null(value)',
        'ifnull': 'OPAL doesn\'t have ifnull(). Use: if_null(value, default) or coalesce(value, default)',
        'nvl': 'OPAL doesn\'t have nvl(). Use: if_null(value, default) or coalesce(value, default)',
        'concat': 'OPAL doesn\'t have concat(). Use: concat_strings(str1, str2, ...) or concat_arrays(arr1, arr2)',
        'dateadd': 'OPAL doesn\'t have dateadd(). Use: timestamp + duration(amount, unit)',
        'datediff': 'OPAL doesn\'t have datediff(). Use: timestamp subtraction or duration operations',
        'getdate': 'OPAL doesn\'t have getdate(). Use: now() for current timestamp',
        'current_date': 'OPAL doesn\'t have current_date(). Use: now() for current timestamp',
    }

    # Complete list of OPAL verbs from https://docs.observeinc.com/en/latest/content/query-language-reference/ListOfOPALVerbs.html
    ALLOWED_VERBS = {
        # Aggregate verbs
        'aggregate', 'align', 'dedup', 'distinct', 'fill', 'histogram',
        'make_reference', 'make_session', 'merge_events', 'pivot', 'rollup',
        'statsby', 'timechart', 'bucketize', 'timestats', 'unpivot',

        # Filter verbs
        'always', 'bottomk', 'ever', 'filter', 'filter_last', 'limit',
        'never', 'topk',

        # Join verbs
        'exists', 'follow', 'follow_not', 'fulljoin', 'join', 'leftjoin',
        'lookup', 'lookup_ip_info', 'not_exists', 'surrounding', 'union',
        'update_resource',

        # Metadata verbs
        'add_key', 'drop_interface', 'interface', 'make_event', 'make_interval',
        'make_metric', 'make_resource', 'make_table', 'set_col_enum',
        'set_col_immutable', 'set_col_searchable', 'set_col_visible', 'set_label',
        'set_link', 'set_metric', 'set_metric_metadata', 'set_primary_key', 'set_pk',
        'set_timestamp', 'set_valid_from', 'set_valid_to', 'sort', 'timeshift',
        'unset_all_links', 'unset_keys', 'unset_link', 'unsort',

        # Projection verbs
        'drop_col', 'extract_regex', 'make_col', 'pick_col', 'rename_col',

        # Semistructured verbs
        'flatten', 'flatten_all', 'flatten_leaves', 'flatten_single'
    }

    # 1. Balanced delimiters (prevents malformed queries)
    if query.count('(') != query.count(')'):
        return False, "Unbalanced parentheses in OPAL query"
    if query.count('[') != query.count(']'):
        return False, "Unbalanced square brackets in OPAL query"
    if query.count('{') != query.count('}'):
        return False, "Unbalanced curly braces in OPAL query"

    # 2. String quote balance (basic check for common mistakes)
    # Note: This is a heuristic - escaped quotes complicate this
    double_quotes = query.count('"')
    if double_quotes % 2 != 0:
        return False, "Unbalanced double quotes in OPAL query"

    # 3. Query complexity limits (prevents DoS via complex queries)
    operation_count = query.count('|') + 1
    if operation_count > 20:  # Max 20 piped operations
        return False, f"OPAL query too complex: {operation_count} operations (max 20 allowed)"

    # 4. Nesting depth check (deeply nested parentheses can cause performance issues)
    max_nesting = 0
    current_nesting = 0
    for char in query:
        if char == '(':
            current_nesting += 1
            max_nesting = max(max_nesting, current_nesting)
        elif char == ')':
            current_nesting -= 1

    if max_nesting > 10:  # Max nesting depth of 10
        return False, f"OPAL query nesting too deep: {max_nesting} levels (max 10 allowed)"

    # 5. Validate all verbs in the pipeline
    # Split by pipe operator and check each verb
    operations = query.split('|')
    for i, operation in enumerate(operations, 1):
        # Extract first word (the verb) after stripping whitespace
        first_word = operation.strip().split()[0] if operation.strip().split() else ""

        if not first_word:
            return False, f"Empty operation at position {i} in pipeline"

        # Check if verb is in whitelist
        if first_word not in ALLOWED_VERBS:
            return False, (
                f"Unknown OPAL verb '{first_word}' at position {i}. "
                f"Valid verbs: {', '.join(sorted(list(ALLOWED_VERBS)[:10]))}... "
                f"(see https://docs.observeinc.com/en/latest/content/query-language-reference/ListOfOPALVerbs.html)"
            )

    # 6. Validate function calls (handles nested functions like window(count(1), group_by(x)))
    import re

    # Extract all function calls using regex: identifier followed by (
    # This pattern handles nested functions and multiple functions in the same expression
    function_pattern = r'\b([a-zA-Z_][a-zA-Z0-9_]*)\s*\('
    function_matches = re.findall(function_pattern, query)

    # Validate each function name
    for func_name in set(function_matches):  # Use set to avoid duplicate error messages
        if func_name not in ALLOWED_FUNCTIONS:
            # Check if this is a common SQL function with a known OPAL alternative
            if func_name in SQL_FUNCTION_HINTS:
                return False, (
                    f"Unknown function '{func_name}()'. "
                    f"{SQL_FUNCTION_HINTS[func_name]} "
                    f"(see https://docs.observeinc.com/en/latest/content/query-language-reference/ListOfOPALFunctions.html)"
                )
            else:
                # Generic unknown function error
                similar_funcs = [f for f in ALLOWED_FUNCTIONS if f.startswith(func_name[:3])][:5]
                suggestion = f" Similar functions: {', '.join(similar_funcs)}" if similar_funcs else ""
                return False, (
                    f"Unknown function '{func_name}()'. "
                    f"Valid OPAL functions: count, sum, avg, if, contains, string, parse_json, etc.{suggestion} "
                    f"(see https://docs.observeinc.com/en/latest/content/query-language-reference/ListOfOPALFunctions.html)"
                )

    # 7. Check for common SQL-style sort syntax (sort -field instead of sort desc(field))
    # Check each operation in the pipeline (avoids matching inside quoted strings)
    for operation in operations:
        # Check if this operation starts with "sort -" (after stripping whitespace)
        stripped_op = operation.strip()
        if re.match(r'^sort\s+-', stripped_op):
            return False, (
                "Invalid sort syntax. "
                "OPAL uses 'sort desc(field)' not 'sort -field'. "
                "Use: sort desc(field) for descending or sort asc(field) for ascending. "
                "(see https://docs.observeinc.com/en/latest/content/query-language-reference/verbs/sort.html)"
            )

    return True, None


@mcp.tool()
@requires_scopes(['admin', 'write', 'read'])
@trace_mcp_tool(tool_name="execute_opal_query", record_args=True, record_result=False)
async def execute_opal_query(ctx: Context, query: str, dataset_id: str = None, primary_dataset_id: str = None, secondary_dataset_ids: Optional[str] = None, dataset_aliases: Optional[str] = None, time_range: Optional[str] = "1h", start_time: Optional[str] = None, end_time: Optional[str] = None, format: Optional[str] = "csv", timeout: Optional[float] = None) -> str:
    """
    Execute OPAL (Observe Processing and Analytics Language) queries on datasets.

    MANDATORY 2-STEP WORKFLOW (Skipping Step 1 = "field not found" errors):
    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    Step 1: discover_datasets("search term") → Get dataset_id + EXACT field names
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
      # Metric aggregation
      align 5m, errors:sum(m("<METRIC_NAME>"))
      | aggregate total_errors:sum(errors), group_by(service_name)

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

    TIME UNITS (Check sample values in discover_datasets):
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

    EXAMPLES (Replace <FIELD> with actual names from discover_datasets):
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
        primary_dataset_id: Dataset ID from discover_datasets() or discover_metrics()
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

    # Validate OPAL query structure (H-INPUT-1)
    is_valid, error_message = validate_opal_query_structure(query)
    if not is_valid:
        return f"OPAL Query Validation Error: {error_message}"

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

    return await observe_execute_opal_query(
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
@trace_mcp_tool(tool_name="discover_datasets", record_args=True, record_result=False)
async def discover_datasets(ctx: Context, query: str = "", dataset_id: Optional[str] = None, dataset_name: Optional[str] = None, max_results: int = 15, business_category_filter: Optional[str] = None, technical_category_filter: Optional[str] = None, interface_filter: Optional[str] = None) -> str:
    """
    Discover datasets and get complete schema information for OPAL queries.

    Returns dataset ID + EXACT field names needed for execute_opal_query().

    WHAT YOU GET:
    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    • Dataset ID (required for execute_opal_query)
    • Top-level fields → Use directly: filter body ~ error
    • Nested fields with dots → MUST quote: resource_attributes."k8s.namespace.name"
    • Sample values → Check time field units (19 digits = nanoseconds, 13 = milliseconds)
    • Query examples → Copy structure, replace field names

    BEFORE CALLING execute_opal_query:
    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    1. Save dataset_id from results
    2. Copy-paste exact field names (case-sensitive, don't retype!)
    3. CRITICAL: Quote field names with dots: resource_attributes."k8s.namespace.name"
    4. Check sample values for time units (no suffix = nanoseconds)

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
    # Validate input sizes to prevent DoS attacks (H-INPUT-2)
    validate_input_size(query, "query", 1024)  # 1KB max for search queries
    validate_input_size(dataset_id, "dataset_id", 1024)  # 1KB max
    validate_input_size(dataset_name, "dataset_name", 1024)  # 1KB max
    validate_input_size(business_category_filter, "business_category_filter", 1024)  # 1KB max
    validate_input_size(technical_category_filter, "technical_category_filter", 1024)  # 1KB max
    validate_input_size(interface_filter, "interface_filter", 1024)  # 1KB max

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
                    return f"""# Dataset Lookup by ID

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
                    return f"""# Dataset Lookup by Name

**Dataset Name**: `{dataset_name}`
**Result**: Not found

**Possible reasons**:
- Dataset name does not exist
- Dataset has been excluded from search
- Name does not match exactly (case-sensitive)

**Suggestion**: Try using `discover_datasets("partial name")` to search for similar datasets."""

            elif not query:
                # No search criteria provided
                return """# Dataset Discovery Error

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
                return f"""# Dataset Discovery Results

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
                    schema_info_str = "**COMPLETE SCHEMA - USE EXACT FIELD NAMES & TYPES**:\n"

                    # Sort fields: top-level first, then nested
                    top_level_fields = [f for f in all_fields_info.keys() if '.' not in f]
                    nested_fields = [f for f in all_fields_info.keys() if '.' in f]

                    for field_list, header in [(top_level_fields, "**Top-Level Fields**"), (nested_fields, "**Nested Fields**")]:
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
                                            samples_str += " (likely nanoseconds)"
                                        elif any(len(str(s)) == 13 for s in samples if str(s).isdigit()):
                                            samples_str += " (likely milliseconds)"

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

            return f"""# Dataset Discovery Results

**Query**: "{query}"
**Found**: {len(results)} datasets (showing top {max_results})
**Search Scope**: {total_datasets} total datasets | Top categories: {category_summary}

{chr(10).join(formatted_results)}

---
**Next Steps**:
- Use `execute_opal_query()` with the dataset ID to query the data
- Use `discover_metrics()` to find related metrics for analysis
"""
            
        finally:
            await conn.close()
            
    except ImportError as e:
        return f"""# Dataset Discovery Error
**Issue**: Required database library not available
**Error**: {str(e)}
**Solution**: The dataset intelligence system requires asyncpg. Please install it with: pip install asyncpg"""
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        return f"""# Dataset Discovery Error
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

    METRICS QUERY REQUIREMENT:
    ═════════════════════════════
    ALL metric queries MUST use: align + m() + aggregate
    You CANNOT filter or aggregate metrics directly - see execute_opal_query() for pattern.

    METRICS-SPECIFIC GUIDANCE
    ═════════════════════════════

    WHAT METRICS PROVIDE:
    - Error FREQUENCIES and counts (not actual error messages)
    - Performance metrics (latency, throughput, resource utilization)
    - System health indicators (availability, saturation, errors)

    WHAT METRICS DON'T PROVIDE:
    - Actual error messages or stack traces → Use discover_datasets() for logs
    - Detailed request context → Use discover_datasets() for trace/span data

    METRIC TYPES
       - Counter: Cumulative values that only increase (error_count, request_total)
       - Gauge: Point-in-time values that can go up/down (cpu_usage, memory_bytes, queue_depth)
       - Histogram: Distribution data with buckets (latency_bucket, response_time_bucket)

    COMMON DIMENSIONS (Group-By Fields)
       - Service identifiers: service_name, endpoint, method
       - Infrastructure: namespace, pod, container, node, zone
       - Status indicators: status_code, error_type, severity
       - Check "Dimensions" section in results for available groupings

    TIME UNITS (Same as datasets!)
       - Fields without suffix (duration, elapsed) = NANOSECONDS
       - Fields with suffix (duration_ms, latency_s) = as labeled
       - Always check sample values and convert if needed

    VALUE RANGES - Use for filtering and anomaly detection
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
    # Validate input sizes to prevent DoS attacks (H-INPUT-2)
    validate_input_size(query, "query", 1024)  # 1KB max for search queries
    validate_input_size(category_filter, "category_filter", 1024)  # 1KB max
    validate_input_size(technical_filter, "technical_filter", 1024)  # 1KB max

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
                return f"""# Metrics Discovery Results

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
                        query_guidance += f"**Key Nested Fields (EXACT PATHS)**: {nested_text}\n"

                if common_fields:
                    field_list = ', '.join(common_fields[:4])  # Show 4 instead of 3
                    if len(common_fields) > 4:
                        field_list += f" (+{len(common_fields)-4} more)"
                    query_guidance += f"**Common Fields (USE EXACT NAMES)**: {field_list}\n"
                
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

            return f"""# Metrics Discovery Results

**Query**: "{query}"
**Found**: {len(results)} metrics (showing top {max_results})
**Search Scope**: {total_metrics} total metrics | Top categories: {category_summary}

{chr(10).join(formatted_results)}

---
**Next Steps**:
- Use `execute_opal_query()` with the dataset ID to query specific metrics
- Use `discover_datasets()` to find related datasets for comprehensive analysis
"""
            
        finally:
            await conn.close()
            
    except ImportError as e:
        return f"""# Metrics Discovery Error

**Issue**: Required database library not available
**Error**: {str(e)}
**Solution**: The metrics intelligence system requires asyncpg. Please install it:
```bash
pip install asyncpg
```
"""

    except Exception as e:
        return f"""# Metrics Discovery Error

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
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

# Import BM25-powered skills search (no external API dependencies)
from src.observe.skills_search import search_skills_bm25 as search_docs

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
    Execute OPAL (Observe Processing and Analytics Language) queries on datasets and metrics in Observe.

    ## Overview

    Observe stores three fundamental types of observability data, each requiring different OPAL approaches:

    1. **Events** (Logs) - Point-in-time occurrences with no duration
    2. **Intervals** (Spans, Resources) - Time-bounded entities with start/end times
    3. **Metrics** - Pre-aggregated measurements collected at regular intervals

    **Critical Rule:** Always use `discover_context()` BEFORE writing queries to get exact field names, metric types, and available dimensions.

    ---

    ## Understanding Data Types

    ### Events (Logs)
    **Characteristics:**
    - Point-in-time entries (single timestamp)
    - High volume, text-heavy
    - Examples: Application logs, system logs, audit logs

    **Interface:** `log`

    **Best for:** Searching text, error analysis, event counting

    **Query approach:** Direct filtering and aggregation with `statsby`

    ---

    ### Intervals (Spans, Resources)
    **Characteristics:**
    - Time-bounded with start and end timestamps
    - Have duration
    - Examples: Distributed traces (spans), Kubernetes pods, database connections

    **Interface:** `otel_span`, `resource`

    **Best for:** Latency analysis, request tracing, resource lifecycle tracking

    **Query approach:** Calculate duration, filter by time ranges, percentile analysis

    ---

    ### Metrics
    **Characteristics:**
    - Pre-aggregated data points
    - Collected at regular intervals (e.g., every 5 minutes)
    - Efficient for time-series analysis
    - Types: `gauge`, `counter`, `delta`, `tdigest`

    **Best for:** Performance dashboards, trending over time, efficient aggregations

    **Query approach:** MUST use `align` verb to work with time buckets

    ---

    ### Reference Tables
    **Characteristics:**
    - Static or slowly-changing lookup data
    - No timestamp typically (Table type datasets)
    - Used to enrich other datasets via joins
    - Examples: Product catalogs, user mappings, service metadata

    **Interface:** None (Table type)

    **Best for:** Data enrichment, ID-to-name mapping, dimensional lookups

    **Query approach:** Join with other datasets using `lookup` verb

    **Lookup Patterns:**

    **Pattern A: Explicit Join (Recommended)**
    ```opal
    # Join Product Logs with Product reference table using alias
    # Requires: dataset_aliases={"product": "42782294"}, secondary_dataset_ids=["42782294"]
    lookup @product.app_product_id=product_id, pname:@product.app_product_name
    | statsby count(), group_by(pname)
    | limit 10
    ```

    **Pattern B: Implicit Join (Requires Matching Column Names)**
    ```opal
    # Must have matching column name
    make_col app_product_id:product_id
    | lookup @product_ref
    | make_col pname:app_product_name
    | limit 10
    ```

    **Pattern C: Using on() with Column Bindings**
    ```opal
    # Full control over join conditions and retrieved columns
    lookup on(product_id=@product.app_product_id), product_name:@product.app_product_name
    | statsby count(), group_by(product_name)
    ```

    **Key Points:**
    - Explicit lookup allows different column names between datasets
    - Implicit lookup requires exact column name matching
    - Use `discover_context()` to find reference table fields
    - Reference tables typically have `primaryKey` defined

    ---

    ## OPAL Patterns by Data Type

    ### Pattern 1: Events (Logs)

    **Use `filter` → `make_col` → `statsby`**

    ```opal
    # Count errors by service
    filter body ~ "error"
    | make_col svc:string(resource_attributes."service.name")
    | statsby error_count:count(), group_by(svc)
    | sort desc(error_count)
    | limit 20

    # Search with multiple conditions
    filter contains(body, "error") or contains(body, "exception")
    | filter string(resource_attributes."k8s.namespace.name") = "production"
    | statsby count(), group_by(string(resource_attributes."service.name"))
    ```

    **Key points:**
    - Use `statsby` for aggregations (NOT `aggregate`)
    - Quote nested field names with dots: `resource_attributes."k8s.namespace.name"`
    - Results: One row per group across entire time range

    ---

    ### Pattern 2: Intervals (Spans)

    **Use `filter` → `make_col` (calculate duration) → `statsby`**

    ```opal
    # Service latency percentiles
    make_col svc:service_name, dur_ms:float64(duration)/1000000
    | statsby p50:percentile(dur_ms, 0.50),
              p95:percentile(dur_ms, 0.95),
              p99:percentile(dur_ms, 0.99),
              group_by(svc)
    | sort desc(p95)
    | limit 20

    # Count requests by service
    make_col svc:service_name
    | statsby request_count:count(), group_by(svc)
    | sort desc(request_count)

    # Error analysis
    filter error = true
    | make_col svc:service_name, error_msg:string(error_message)
    | statsby error_count:count(), group_by(svc, error_msg)
    | sort desc(error_count)
    ```

    **Key points:**
    - Duration is typically in nanoseconds - divide by 1,000,000 for milliseconds
    - Use `percentile()` function for latency analysis
    - `statsby` aggregates across the entire time range
    - Results: Summary statistics, one row per group

    ---

    ### Pattern 2.5: Formatting Timestamps for Display

    **⚠️ IMPORTANT: Only needed for user-facing output, NOT for analysis/filtering**

    Timestamp fields (`start_time`, `end_time`) are already `timestamp` type in OPAL - no conversion needed for filtering, sorting, or arithmetic. Use `format_time()` ONLY when you need human-readable output.

    ```opal
    # Format timestamps for user display (Snowflake format syntax)
    filter error = true
    | make_col svc:service_name,
             error_time:format_time(start_time, 'YYYY-MM-DD HH24:MI:SS'),
             error_msg:string(error_message)
    | sort desc(start_time)
    | limit 20

    # Common Snowflake format patterns:
    # - 'YYYY-MM-DD' - Date only (2025-11-11)
    # - 'HH24:MI:SS' - 24-hour time (17:18:13)
    # - 'YYYY-MM-DD HH24:MI:SS' - Full datetime (2025-11-11 17:18:13)
    # - 'YYYY-MM-DD"T"HH24:MI:SS' - ISO 8601 format

    # For analysis, use timestamps directly (no formatting needed!)
    filter start_time > @"2025-11-11T00:00:00Z"
    | make_col svc:service_name, dur_ms:float64(duration)/1000000
    | statsby avg_latency:avg(dur_ms), group_by(svc)
    ```

    **Key points:**
    - `start_time` and `end_time` are native `timestamp` types - NOT int64 nanoseconds
    - Use `format_time(start_time, 'format_string')` for display only
    - Use raw timestamps for filtering, sorting, and time arithmetic
    - Format strings use Snowflake datetime format syntax (NOT strftime)
    - Do NOT use `from_nanoseconds()` - timestamps are already the correct type

    ---

    ### Pattern 3: Metrics (Pre-aggregated Data)

    **CRITICAL: Metrics require `align` verb**

    Metrics queries produce different output based on binning strategy:

    #### Option A: Summary Output (One Row Per Service)
    **Use `align options(bins: 1)` for single summary across time range**

    ```opal
    # Total request count per service
    align options(bins: 1), rate:sum(m("span_call_count_5m"))
    aggregate total_requests:sum(rate), group_by(service_name)
    fill total_requests:0

    # Average error rate per service
    align options(bins: 1), errors:sum(m("span_error_count_5m"))
    aggregate total_errors:sum(errors), group_by(service_name)
    filter total_errors > 0
    ```

    **Result:** One row per service (summary across entire time window)

    **Note:** No pipe `|` between `align` and `aggregate` when using `options(bins: 1)`

    #### Option B: Time-Series Output (Multiple Rows Per Service)
    **Use `align 5m` or `align` (auto bins) for trending over time**

    ```opal
    # Request rate trending over time
    align 5m, rate:sum(m("span_call_count_5m"))
    | aggregate total_requests:sum(rate), group_by(service_name)
    | sort desc(total_requests)
    ```

    **Result:** Multiple rows per service (one per time bucket)

    **Output includes:**
    - `_c_bucket` - Time bucket identifier
    - `valid_from`, `valid_to` - Time bucket boundaries
    - One row per (service, time_bucket) combination

    ---

    ## Working with Metrics

    ### Metric Types and Functions

    **1. Counter/Gauge/Delta Metrics**
    Use `m()` function:
    ```opal
    # Summary (single row per service)
    align options(bins: 1), total:sum(m("span_call_count_5m"))
    aggregate total_calls:sum(total), group_by(service_name)

    # Time-series (multiple rows)
    align total:sum(m("span_call_count_5m"))
    | aggregate total_calls:sum(total), group_by(service_name)
    ```

    **2. TDigest Metrics (Percentile/Latency)**
    Use `m_tdigest()` with special combine/quantile pattern:

    ```opal
    # Summary (single row per service)
    align options(bins: 1), combined:tdigest_combine(m_tdigest("span_duration_tdigest_5m"))
    aggregate p50:tdigest_quantile(tdigest_combine(combined), 0.50),
              p95:tdigest_quantile(tdigest_combine(combined), 0.95),
              p99:tdigest_quantile(tdigest_combine(combined), 0.99),
              group_by(service_name)
    make_col p50_ms:p50/1000000, p95_ms:p95/1000000, p99_ms:p99/1000000
    ```

    **Critical pattern for tdigest:**
    1. `align` → `tdigest_combine(m_tdigest("metric"))`
    2. `aggregate` → `tdigest_quantile(tdigest_combine(column), percentile)`
    3. Note: `tdigest_combine` appears TWICE - once in align, once nested in aggregate

    **How to know which function to use:**
    ```bash
    # Check metric type in discover_context() output:
    # - type: "tdigest" → use m_tdigest()
    # - type: "gauge", "counter", "delta" → use m()
    ```

    ---

    ## Time Bucketing and Aggregation

    ### Understanding align options(bins: N)

    | Pattern | Output | Use Case |
    |---------|--------|----------|
    | `align options(bins: 1)` | One row per group | Summary reports, totals, single percentiles |
    | `align 5m` | Many rows per group | Time-series charts, trending |
    | `align 1h` | Many rows per group | Hourly trends |
    | `align` (default) | Auto-sized buckets | Dashboards (Observe picks optimal size) |

    **Important syntax note:** When using `options(bins: 1)`, do NOT use pipe `|` between `align` and `aggregate`

    ### Decision Tree

    ```
    ┌─────────────────────────────────────┐
    │ What do you need?                   │
    └─────────────────────────────────────┘
               │
               ├─ Single summary per service (e.g., "total requests in 24h")
               │  └─> Use: Metrics + align options(bins: 1)
               │      Result: 1 row per service
               │
               ├─ Trends over time (e.g., "requests per hour")
               │  └─> Use: Metrics + align 5m + aggregate
               │      Result: Multiple rows per service (time-series)
               │
               └─ Raw detailed analysis (no metrics available)
                  └─> Use: Raw dataset + statsby (no align)
                      Result: 1 row per group
    ```

    ---

    ## Complete Examples

    ### Example 1: RED Methodology (Summary)

    **Goal:** Get Rate, Error, Duration summary for all services over 24 hours

    ```opal
    # RATE - Total requests per service
    align options(bins: 1), rate:sum(m("span_call_count_5m"))
    aggregate total_requests:sum(rate), group_by(service_name)
    fill total_requests:0

    # ERRORS - Total errors per service
    align options(bins: 1), errors:sum(m("span_error_count_5m"))
    aggregate total_errors:sum(errors), group_by(service_name)
    filter total_errors > 0

    # DURATION - Latency percentiles per service
    align options(bins: 1), combined:tdigest_combine(m_tdigest("span_sn_service_node_duration_tdigest_5m"))
    aggregate p50:tdigest_quantile(tdigest_combine(combined), 0.50),
              p95:tdigest_quantile(tdigest_combine(combined), 0.95),
              p99:tdigest_quantile(tdigest_combine(combined), 0.99),
              group_by(service_name)
    make_col p50_ms:p50/1000000, p95_ms:p95/1000000, p99_ms:p99/1000000
    ```

    **Output:** One row per service with summary statistics

    **Important:** No pipe `|` between verbs when using `options(bins: 1)`

    ---

    ### Example 2: RED Methodology (Alternative - Raw Spans)

    **When to use:** Metrics don't exist, or you need span-level details

    ```opal
    # RATE - Request count
    make_col svc:service_name
    | statsby request_count:count(), group_by(svc)
    | sort desc(request_count)

    # ERRORS - Error count
    filter error = true
    | make_col svc:service_name
    | statsby error_count:count(), group_by(svc)
    | sort desc(error_count)

    # DURATION - Latency percentiles
    make_col svc:service_name, dur_ms:float64(duration)/1000000
    | statsby p50:percentile(dur_ms, 0.50),
              p95:percentile(dur_ms, 0.95),
              p99:percentile(dur_ms, 0.99),
              group_by(svc)
    | sort desc(p95)
    ```

    **Note:** Slower than metrics approach but works on raw data

    ---

    ### Example 3: Top Errors with Details

    ```opal
    # Find top errors from spans with full details
    filter error = true
    | make_col svc:service_name,
              error_msg:string(error_message),
              span:span_name,
              status:string(status_code)
    | statsby error_count:count(), group_by(svc, error_msg, span)
    | sort desc(error_count)
    | limit 20
    ```

    ---

    ### Example 4: Time-Series for Dashboard

    ```opal
    # Request rate over time (for charting)
    align 5m, rate:sum(m("span_call_count_5m"))
    | aggregate requests_per_5min:sum(rate), group_by(service_name)

    # Error rate over time
    align 5m, errors:sum(m("span_error_count_5m"))
    | aggregate errors_per_5min:sum(errors), group_by(service_name)
    | filter errors_per_5min > 0
    ```

    **Result:** Time-series data suitable for line charts

    ---

    ## Common Patterns

    ### Pattern: Conditional Counting (No count_if!)

    OPAL doesn't have `count_if()`. Use this pattern instead:

    ```opal
    # Count errors vs total requests
    make_col svc:service_name, is_error:if(error = true, 1, 0)
    | statsby total:count(), error_count:sum(is_error), group_by(svc)
    | make_col error_rate:float64(error_count)/float64(total)
    | sort desc(error_rate)
    ```

    ---

    ### Pattern: Nested Field Access

    ```opal
    # Fields with dots MUST be quoted
    make_col namespace:string(resource_attributes."k8s.namespace.name"),
             service:string(resource_attributes."service.name")
    | filter namespace = "production"
    ```

    **Rule:** `object."field.with.dots"` - quote only the field name, not the whole path

    ---

    ### Pattern: Time Unit Conversion

    ```opal
    # Nanoseconds to milliseconds
    make_col dur_ms:duration/1000000

    # Nanoseconds to seconds
    make_col dur_sec:duration/1000000000

    # Check field samples in discover_context() to identify units!
    # 19 digits (1760201545280843522) = nanoseconds
    # 13 digits (1758543367916) = milliseconds
    ```

    ---

    ## Troubleshooting

    ### Issue: "Same service appears multiple times!"

    **Cause:** Using metrics with `align` produces time-series data

    **Solution:**
    - For summary: Use `align options(bins: 1)`
    - For trends: This is correct behavior - each row is a time bucket

    ---

    ### Issue: "Only getting one service in results"

    **Diagnosis:**
    1. Check if metric has data for other services: `discover_context(metric_name="...")`
    2. Verify dimensions available in metric
    3. Try querying raw dataset to confirm other services exist

    **Solution:** You might be using a metric that only captures one service, or need to filter differently

    ---

    ### Issue: "Field not found" error

    **Cause:**
    - Field name spelled incorrectly (case-sensitive!)
    - Missing quotes around nested fields with dots
    - Using wrong dataset

    **Solution:**
    1. Run `discover_context(dataset_id="...")` to get exact field names
    2. Copy field names exactly as shown
    3. Quote nested fields: `resource_attributes."k8s.namespace.name"`

    ---

    ### Issue: "Percentiles look wrong"

    **Check:**
    1. **Time units** - Duration often in nanoseconds (divide by 1M for ms)
    2. **TDigest pattern** - Must use `tdigest_combine` twice (align + aggregate)
    3. **Correct syntax:**
       ```opal
       aggregate p95:tdigest_quantile(tdigest_combine(combined), 0.95)
       ```
       NOT:
       ```opal
       aggregate agg:tdigest_combine(combined)
       | make_col p95:tdigest_quantile(agg, 0.95)
       ```

    ---

    ### Issue: "Unknown function" error

    **Common mistakes:**
    - Using `count_if()` - doesn't exist, use `if()` + `sum()` pattern
    - Using `pick` - doesn't exist, use `make_col`
    - Using SQL syntax like `CASE/WHEN` - use `if(condition, true_val, false_val)`

    **Solution:** See OPAL documentation or use `get_relevant_docs()` to find correct syntax

    ---

    ### Issue: Metric query fails with "column has to be aggregated or grouped"

    **Cause:** Trying to use a column from `align` directly in `aggregate` without re-combining

    **Solution for tdigest:**
    ```opal
    # WRONG
    align combined:tdigest_combine(m_tdigest("metric"))
    | aggregate p95:tdigest_quantile(combined, 0.95)  ❌

    # CORRECT
    align combined:tdigest_combine(m_tdigest("metric"))
    | aggregate p95:tdigest_quantile(tdigest_combine(combined), 0.95)  ✓
    ```

    ---

    ## Parameters Reference

    ### Required Parameters

    **`query`** (string)
    - The OPAL query to execute
    - Must be valid OPAL syntax
    - See patterns above for examples

    **`primary_dataset_id`** (string)
    - Dataset ID from `discover_context()`
    - Use `dataset_id` for backward compatibility
    - Get from Phase 2 of discovery (detailed lookup)

    ### Optional Parameters

    **`time_range`** (string)
    - Relative time range: `"1h"`, `"24h"`, `"7d"`, `"30d"`
    - Defaults to `"1h"`
    - Alternative: Use `start_time` and `end_time`

    **`start_time`** / **`end_time`** (string)
    - ISO format: `"2024-01-20T16:20:00Z"`
    - For absolute time ranges
    - Overrides `time_range` if specified

    **`secondary_dataset_ids`** (string)
    - JSON array for joins: `'["44508111"]'`
    - Used with `dataset_aliases`

    **`dataset_aliases`** (string)
    - JSON object for joins: `'{"volumes": "44508111"}'`
    - Use with `@alias` in join syntax

    **`format`** (string)
    - `"csv"` (default) or `"ndjson"`
    - CSV limited to first 1000 rows

    **`timeout`** (number)
    - Seconds to wait for query completion
    - Default: 30s

    ---

    ## Best Practices Summary

    ### 1. Always discover_context() first
    ```
    Phase 1: Search for datasets/metrics
    Phase 2: Get detailed schema with field names and types
    Phase 3: Write query using exact field names
    ```

    ### 2. Choose the right approach

    | Need | Approach | Why |
    |------|----------|-----|
    | Summary stats | Metrics + `options(bins: 1)` | Fastest, one row per group |
    | Time trends | Metrics + `align 5m` | Efficient time-series |
    | Raw analysis | Dataset + `statsby` | Full details, slower |

    ### 3. Know your data type

    - **Events (logs):** `filter` → `statsby`
    - **Intervals (spans):** Calculate duration → `statsby`
    - **Metrics:** `align` → `aggregate` (REQUIRED)

    ### 4. Metric type matters

    - **Counter/Gauge:** `m("metric_name")`
    - **TDigest:** `m_tdigest("metric_name")` + double combine pattern

    ### 5. Field naming

    - Copy exactly from `discover_context()`
    - Quote nested fields with dots: `object."field.with.dots"`
    - Case-sensitive!

    ---

    ## Additional Resources

    - **Unknown syntax:** `get_relevant_docs("opal <keyword>")`
    - **Error debugging:** Check error message keywords in docs
    - **Examples:** Search docs for specific use cases (e.g., "OPAL join syntax")

    ---

    **Remember:** When in doubt about OPAL syntax or seeing unexpected results, use `get_relevant_docs()` to search official Observe documentation.
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
@trace_mcp_tool(tool_name="learn_observe_skill", record_args=True, record_result=False)
async def learn_observe_skill(ctx: Context, query: str, n_results: int = 5) -> str:
    """
    Search OPAL skill documentation using local BM25 search for OPAL syntax and best practices.

    This tool uses ParadeDB BM25 ranking to search curated OPAL skills documentation.
    No external API dependencies - all search happens locally in PostgreSQL.

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
    learn_observe_skill("error message keywords" or "feature name")
            ↓
    Review official syntax from skills documentation
            ↓
    Retry execute_opal_query() with corrected syntax

    SEARCH TIPS:
    ───────────────
    • Use specific keywords: "aggregation", "filtering", "percentile"
    • Search for OPAL verbs: "statsby", "filter", "make_col", "timechart"
    • Search for operations: "group by", "time series", "window functions"

    TYPICAL USE CASES
    ────────────────
    - "aggregation statsby" → Learn aggregation syntax with statsby
    - "filter logs" → Filtering event datasets
    - "percentile latency" → Analyzing tdigest metrics for percentiles
    - "time series" → Creating time-series charts
    - "window functions" → Using lag(), lead(), row_number()
    - "join datasets" → Subquery patterns and unions

    Args:
        query: Documentation search query describing what you need to learn
        n_results: Number of skills to return (default: 5, recommended: 3-10)

    Returns:
        Relevant skill documentation with:
        - Full skill content
        - Skill name and category
        - BM25 relevance score
        - Difficulty level and tags

    Examples:
        # Learn OPAL operations
        learn_observe_skill("aggregation")
        learn_observe_skill("filter events")

        # Advanced patterns
        learn_observe_skill("percentile metrics", n_results=3)
        learn_observe_skill("time series analysis")
        learn_observe_skill("window functions")

    Performance:
        - Search time: < 100ms (local BM25 index)
        - No external API calls or rate limits
        - Instant results from PostgreSQL
    """
    # Validate input sizes to prevent DoS attacks (H-INPUT-2)
    validate_input_size(query, "query", 1024)  # 1KB max for search queries

    try:
        # Log the skills search operation
        semantic_logger.info(f"skills search | query:'{query}' | n_results:{n_results}")

        # Search skills using BM25
        skill_results = await search_docs(query, n_results=n_results)

        if not skill_results:
            return f"No relevant skills found for: '{query}'"

        # Check for error results
        if len(skill_results) == 1 and skill_results[0].get("id") == "error":
            return f"Search error: {skill_results[0].get('text', 'Unknown error')}"

        response = f"Found {len(skill_results)} relevant OPAL skills for: '{query}'\\n\\n"

        # Format each skill result
        for i, result in enumerate(skill_results, 1):
            title = result.get("title", "Untitled Skill")
            score = result.get("score", 0.0)
            content = result.get("text", "")
            metadata = result.get("metadata", {})

            # Extract metadata
            category = metadata.get("category", "General")
            difficulty = metadata.get("difficulty", "intermediate")
            tags = metadata.get("tags", [])
            description = metadata.get("description", "")

            # Format skill output
            response += f"### Skill {i}: {title}\\n"
            response += f"Category: {category} | Difficulty: {difficulty}\\n"
            response += f"BM25 Score: {score:.2f}\\n"

            if tags:
                response += f"Tags: {', '.join(tags[:10])}\\n"

            if description:
                response += f"\\n**Description:** {description}\\n"

            response += f"\\n{content}\\n\\n"
            response += "----------------------------------------\\n\\n"

        # Log successful skills search
        semantic_logger.info(f"skills search complete | found:{len(skill_results)} skills")

        return response
    except Exception as e:
        error_msg = f"Error searching skills: {str(e)}. Make sure skills database is populated (run scripts/skills_intelligence.py)."
        semantic_logger.error(f"skills search error | {error_msg}")
        return error_msg


@mcp.tool()
@requires_scopes(['admin', 'read'])
@trace_mcp_tool(tool_name="discover_context", record_args=True, record_result=False)
async def discover_context(
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
      discover_context("error service") → Returns names, IDs, purposes
      NO field names, NO dimensions shown - context efficient!

    Phase 2: DETAIL MODE (complete schema) - ⚠️ REQUIRED BEFORE QUERIES
      discover_context(dataset_id="...") → ALL fields with types and samples
      discover_context(metric_name="...") → ALL dimensions with cardinality
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
        discover_context("error service")          # See what exists
        discover_context("latency", result_type="metric")  # Only metrics
        discover_context("kubernetes", business_category_filter="Infrastructure")

        # PHASE 2: Detail mode (REQUIRED before queries - get complete schema)
        discover_context(dataset_id="42161740")    # ALL fields for this dataset
        discover_context(metric_name="span_error_count_5m")  # ALL dimensions for this metric

        # Typical workflow:
        # 1. discover_context("errors") → browse options
        # 2. discover_context(dataset_id="42161740") → get field list
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
discover_context("error service")
discover_context(dataset_id="42161740")
discover_context(metric_name="span_error_count_5m")
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
discover_context("error")          # Broad search
discover_context("kubernetes")     # Infrastructure search
discover_context("latency")        # Performance metrics
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
💡 **Remember**: Get complete schema before querying → `discover_context(dataset_id="...")` or `discover_context(metric_name="...")`
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
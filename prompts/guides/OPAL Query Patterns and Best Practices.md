# OPAL Query Patterns and Best Practices Guide

This guide provides essential patterns and syntax rules for generating correct OPAL queries, designed to minimize common errors and reduce query failures.

## Table of Contents

1. [Field Reference Patterns](#field-reference-patterns)
2. [Metric Query Patterns](#metric-query-patterns)
3. [Time Function Patterns](#time-function-patterns)
4. [Data Type Handling](#data-type-handling)
5. [Common Syntax Rules](#common-syntax-rules)
6. [Query Structure Best Practices](#query-structure-best-practices)
7. [Error Prevention Checklist](#error-prevention-checklist)

---

## Field Reference Patterns

### Basic Field References
```opal
// ✅ CORRECT: Direct field access
filter service_name = "frontend"
make_col cluster: k8s_cluster_name

// ❌ INCORRECT: Don't use @ prefix for direct fields
filter @.service_name = "frontend"  // Wrong!
```

### Label Field References (Metrics Datasets)
```opal
// ✅ CORRECT: Access labels in metrics datasets
filter labels.service_name = "frontend"
make_col cluster: string(labels.k8s_cluster_name)

// ❌ INCORRECT: Direct access to label fields
filter service_name = "frontend"  // Will fail if field is in labels
```

### Object Field References
```opal
// ✅ CORRECT: JSON object field access
make_col cpu_usage: float64(FIELDS.cpu.utilization)
filter path_exists(temperatureMeasurement, "current.dt")

// ✅ CORRECT: Special characters in field names
make_col temp_display: @."🌡️ temp"

// ❌ INCORRECT: Missing quotes for special characters
make_col temp_display: @.🌡️ temp  // Syntax error!
```

---

## Metric Query Patterns

### Pattern 1: Align → Aggregate (Recommended for Time-Series)
```opal
// ✅ CORRECT: Proper align → aggregate flow
align 5m, duration_combined: tdigest_combine(m_tdigest("span_duration_5m"))
| make_col p95_ms: tdigest_quantile(duration_combined, 0.95) / 1000000
| aggregate
    avg_p95: avg(p95_ms),
    max_p95: max(p95_ms),
    group_by(service_name)

// ✅ CORRECT: Simple metric aggregation
align 5m, error_total: sum(m("span_error_count_5m"))
| aggregate total_errors: sum(error_total), group_by(service_name)
```

### Pattern 2: Filter → Statsby (Faster for Ad-hoc Queries)
```opal
// ✅ CORRECT: Direct aggregation without time alignment
filter metric = "span_duration_5m"
| make_col p95_ms: tdigest_quantile(tdigestValue, 0.95) / 1000000
| statsby
    avg_p95: avg(p95_ms),
    sample_count: count(),
    group_by(service_name)
```

### Pattern 3: TDigest Handling
```opal
// ✅ CORRECT: TDigest metric processing
align 5m, combined_latency: tdigest_combine(m_tdigest("span_duration_5m"))
| make_col p50: tdigest_quantile(combined_latency, 0.5)
| make_col p95: tdigest_quantile(combined_latency, 0.95)
| make_col p99: tdigest_quantile(combined_latency, 0.99)

// ❌ INCORRECT: Missing tdigest_combine
align 5m, p95: tdigest_quantile(m_tdigest("span_duration_5m"), 0.95)  // Will fail!

// ❌ INCORRECT: Wrong percentile format
make_col p95: tdigest_quantile(duration_combined, 95)  // Should be 0.95!
```

---

## Time Function Patterns

### Window Functions
```opal
// ✅ CORRECT: Window function with proper frame (use with make_event)
align 5m, avg_latency: avg(response_time_ms)
| make_event
| make_col running_avg: window(avg(avg_latency), frame(back:1h))
| make_col rolling_sum: window(sum(avg_latency), frame(back:30m))

// ✅ CORRECT: Multiple window functions
align 5m, request_count: sum(m("request_total"))
| make_event
| make_col avg_1h: window(avg(request_count), frame(back:1h))
| make_col avg_24h: window(avg(request_count), frame(back:24h))

// ❌ INCORRECT: Missing frame specification
make_col running_avg: window(avg(latency_ms))  // Will fail!
```

### Timeshift Operations
```opal
// ✅ CORRECT: Timeshift with proper time format
@yesterday <- @ {
  timeshift 24h
  make_col series: "yesterday"
}
union @yesterday

// ✅ CORRECT: Multiple timeshift periods
@one_hour_ago <- @ { timeshift 1h }
@six_hours_ago <- @ { timeshift 6h }
union @one_hour_ago, @six_hours_ago

// ❌ INCORRECT: Invalid time format
timeshift 1day  // Should be "1d"!
timeshift 60min  // Should be "1h"!
```

### Make Event Usage
```opal
// ✅ CORRECT: Use make_event before window functions
align 5m, value: avg(metric_value)
| make_event
| make_col trend: window(avg(value), frame(back:1h))

// ❌ INCORRECT: Window functions without make_event on aggregated data
align 5m, value: avg(metric_value)
| make_col trend: window(avg(value), frame(back:1h))  // May fail!
```

---

## Data Type Handling

### Type Conversion Patterns
```opal
// ✅ CORRECT: Explicit type conversions
make_col cluster: string(labels.k8s_cluster_name)
make_col cpu_pct: float64(cpu_usage) * 100
make_col request_count: int64(request_total)
make_col duration_sec: duration_sec(duration_ms / 1000)

// ✅ CORRECT: Safe null handling
make_col safe_value: if_null(potentially_null_field, 0)
make_col has_data: not is_null(required_field)
```

### Case vs If Functions
```opal
// ✅ CORRECT: Using case for multiple conditions
make_col status: case(
    response_time > 1000, "Slow",
    response_time > 500, "Medium",
    response_time > 0, "Fast",
    true, "Unknown")

// ✅ CORRECT: Using if for simple conditions
make_col is_error: if(status_code >= 400, true, false)
make_col category: if(is_premium, "Premium", "Standard")

// ❌ INCORRECT: Wrong case syntax
make_col status: case(
    when response_time > 1000 then "Slow",  // SQL-style syntax!
    else "Fast")
```

---

## Common Syntax Rules

### Sorting and Ordering
```opal
// ✅ CORRECT: Sort with desc/asc functions
sort desc(latency_ms)
sort asc(service_name), desc(request_count)

// ❌ INCORRECT: Direct field reference in sort
sort desc latency_ms      // Missing parentheses!
sort -latency_ms         // Wrong syntax!
sort latency_ms desc     // Wrong order!
```

### Filtering Patterns
```opal
// ✅ CORRECT: Boolean expressions
filter service_name = "frontend" and error_rate > 0.01
filter status_code >= 400 or response_time > 5000
filter service_name in ("frontend", "backend", "api")

// ✅ CORRECT: String operations
filter contains(error_message, "timeout")
filter starts_with(service_name, "api-")
filter not is_null(user_id)

// ❌ INCORRECT: Assignment instead of comparison
filter service_name := "frontend"  // Should be =
filter error_rate => 0.01         // Should be >=
```

### String Operations
```opal
// ✅ CORRECT: String concatenation and formatting
make_col display_name: concat_strings(service_name, " (", environment, ")")
make_col formatted_latency: concat_strings(string(round(latency_ms, 2)), "ms")

// ✅ CORRECT: String extraction
extract_regex log_message, /Error: (?P<error_type>\w+)/, "i"
make_col domain: split_part(url, ".", 1)
```

---

## Query Structure Best Practices

### Query Building Pattern
```opal
// ✅ RECOMMENDED: Step-by-step query building
// Step 1: Data selection and basic filtering
filter metric = "span_duration_5m"
| filter service_name = "checkout-service"

// Step 2: Data transformation
| make_col latency_ms: tdigest_quantile(tdigestValue, 0.95) / 1000000

// Step 3: Aggregation
| statsby
    avg_latency: avg(latency_ms),
    request_count: count(),
    group_by(service_name, environment)

// Step 4: Final filtering and formatting
| filter request_count >= 10
| make_col display_latency: concat_strings(string(round(avg_latency, 2)), "ms")
| sort desc(avg_latency)
```

### Multi-Dataset Operations
```opal
// ✅ CORRECT: Subquery pattern
@current_metrics <- @ {
  align 5m, latency: avg(response_time_ms)
  statsby avg_latency: avg(latency), group_by(service_name)
}

@historical_metrics <- @ {
  timeshift 24h
  align 5m, latency: avg(response_time_ms)
  statsby historical_latency: avg(latency), group_by(service_name)
}

<- @current_metrics {
  join service_name = @historical_metrics.service_name,
       baseline: @historical_metrics.historical_latency
  make_col change_pct: ((avg_latency - baseline) / baseline) * 100
}
```

### Union Operations
```opal
// ✅ CORRECT: Union with consistent column structure
make_col data_source: "primary"
@secondary_data <- @other_dataset {
  make_col data_source: "secondary"
  // Ensure same column structure
}
union @secondary_data
```

---

## Error Prevention Checklist

### Before Running Queries
- [ ] **Field names verified** - Check schema or use discovery queries
- [ ] **Data types confirmed** - Use appropriate type conversion functions
- [ ] **Time ranges appropriate** - Ensure sufficient data for time-based operations
- [ ] **Syntax validated** - Check parentheses, quotes, and operators

### For Metric Queries
- [ ] **TDigest handling** - Use `tdigest_combine()` before `tdigest_quantile()`
- [ ] **Align vs Statsby** - Choose appropriate aggregation pattern
- [ ] **Field references** - Use `labels.field_name` for metric datasets
- [ ] **Time alignment** - Use consistent alignment periods (5m, 1h, etc.)

### For Time-Based Queries
- [ ] **Make event usage** - Add before window functions on aggregated data
- [ ] **Frame specification** - Always specify `frame(back:duration)` for windows
- [ ] **Timeshift format** - Use proper time format (1h, 24h, 7d)
- [ ] **Union compatibility** - Ensure consistent schemas across time periods

### For Complex Queries
- [ ] **Subquery syntax** - Proper `@name <- @source { }` format
- [ ] **Join conditions** - Correct field mapping between datasets
- [ ] **Null handling** - Use `if_null()` and `is_null()` appropriately
- [ ] **Performance consideration** - Avoid unnecessary data reads

---

## Common Error Messages and Solutions

### Field Not Found Errors
```
Error: "the field 'service_name' does not exist"
Solution: Check if field is in labels object → use labels.service_name
```

### Syntax Errors
```
Error: "expected one of: ',', ':'"
Solution: Check for missing commas in make_col, statsby, or function calls
```

### Type Mismatch Errors
```
Error: "cannot convert string to float64"
Solution: Add explicit type conversion → float64(field_name)
```

### Time Function Errors
```
Error: "cannot use window function in non-aggregate context"
Solution: Add make_event before window functions on aggregated data
```

### TDigest Errors
```
Error: "tdigest_quantile expects tdigest type"
Solution: Use tdigest_combine() first → tdigest_combine(m_tdigest("metric"))
```

---

## Performance Tips

### Query Optimization
1. **Filter early**: Apply filters before expensive operations
2. **Use appropriate time windows**: Don't query more data than needed
3. **Leverage acceleration**: Use accelerated datasets when possible
4. **Avoid unnecessary columns**: Use `pick_col` to select only needed fields

### Credit Cost Optimization
1. **Choose efficient aggregation**: `statsby` vs `align → aggregate` based on use case
2. **Minimize timeshift operations**: Use shorter time ranges when possible
3. **Use sampling**: For exploratory queries, add `limit` clauses
4. **Cache results**: Save complex transformations as datasets for reuse

This guide serves as a reference for generating syntactically correct and performant OPAL queries. Always validate field names and data types before running complex queries.
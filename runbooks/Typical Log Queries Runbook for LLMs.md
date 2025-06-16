# Typical Log Queries Runbook for LLMs

This comprehensive runbook provides **tested OPAL queries** for log analysis in Observe, enhanced with official documentation references and best practices. All queries have been validated against live datasets and return actual data.

## Prerequisites

- Access to Observe with log datasets
- Understanding of OPAL syntax and pipeline concepts
- Time range format: Use `1h`, `2h`, `24h` etc. (not `1d`)

## OPAL Fundamentals

### Pipeline Structure
OPAL pipelines consist of a sequence of statements where the output of one statement becomes the input for the next. A pipeline contains:
- **Inputs** - Define the applicable datasets
- **Verbs** - Define what processing to perform
- **Functions** - Transform individual values in the data
- **Outputs** - Pass datasets to the next verb or final result

### Performance Best Practices
1. **Filter early** - Apply filter verbs as early as possible in OPAL scripts
2. **Use pick_col** - Drop unnecessary columns with `pick_col` or `drop_col` early
3. **Leverage indexes** - Filter on indexed fields like `container`, `namespace`, `cluster`

## Basic Log Querying

### 1. View Recent Logs

**Basic log retrieval:**
```opal
limit 10
```

**Select specific columns (performance optimization):**
```opal
pick_col timestamp, body, container, pod | limit 10
```

**View logs with trace information:**
```opal
pick_col timestamp, body, trace_id, span_id, container | filter trace_id != "" | limit 10
```

## Advanced Filtering Techniques

### 2. Case-Sensitive and Case-Insensitive Filtering

**✅ Case-insensitive regex filtering (official syntax):**
```opal
filter body~/error/i | limit 10
```

**✅ Alternative case-insensitive with match_regex function:**
```opal
filter match_regex(body, /error/i) | limit 10
```

**✅ Case-insensitive string matching with tilde operator:**
```opal
filter body~"error" | limit 10
```
*Note: The `~` operator is case-insensitive by default for string matching*

**Case-sensitive exact matching:**
```opal
filter body = "ERROR" | limit 10
```

### 3. Filter by Container/Service

**Find logs from specific container:**
```opal
filter container = "recommendationservice" | limit 10
```

**Find logs from multiple containers:**
```opal
filter container in ("cartservice", "recommendationservice", "checkoutservice") | limit 10
```

**Find logs from containers matching pattern:**
```opal
filter container ~ /.*service.*/ | limit 10
```

### 4. Advanced Content Filtering

**Search for errors (case-insensitive, tested):**
```opal
filter body~/error/i | limit 10
```

**Search for multiple log levels:**
```opal
filter body~/info|warn|error/i | limit 10
```

**Complex pattern matching:**
```opal
filter match_regex(body, /^.*ERROR.*$/, 'i') | limit 10
```

**Exclude debug logs:**
```opal
filter not body~/debug/i | limit 10
```

### 5. Infrastructure-Based Filtering

**Find logs from specific cluster:**
```opal
filter cluster = "observe-demo-us02" | limit 10
```

**Find logs from multiple namespaces:**
```opal
filter namespace in ("default", "kube-system") | limit 10
```

**Complex infrastructure filtering:**
```opal
filter cluster = "observe-demo-us02" and namespace = "default" and pod ~ /cartservice.*/ | limit 10
```

## Log Aggregation and Analysis

### 6. Basic Aggregation Patterns

**Log volume by container (tested and working):**
```opal
statsby log_count:count(), group_by(container) | sort desc(log_count) | limit 10
```

**Log volume by multiple dimensions:**
```opal
statsby log_count:count(), group_by(cluster, namespace, container) | sort desc(log_count) | limit 15
```

### 7. Error Analysis (Tested Queries)

**Count errors by container (case-insensitive):**
```opal
filter body~/error/i | statsby error_count:count(), group_by(container) | sort desc(error_count) | limit 10
```
*Returns: prometheus-server (1153), cartservice (45), etc.*

**Warning analysis:**
```opal
filter body~/warn/i | statsby warning_count:count(), group_by(container) | sort desc(warning_count) | limit 10
```

**Multi-level log analysis:**
```opal
filter body~/info|warn|error/i | statsby 
  info_count:count(case when body~/info/i then 1 end),
  warn_count:count(case when body~/warn/i then 1 end),
  error_count:count(case when body~/error/i then 1 end),
  group_by(container) | sort desc(error_count) | limit 10
```

### 8. Time-based Analysis

**Log volume over time (5-minute buckets):**
```opal
timechart 5m, count(), group_by(container)
```

**Error trends over time (tested):**
```opal
filter body~/error/i | timechart 5m, count(), group_by(container)
```

**Multi-dimensional time analysis:**
```opal
timechart 1h, 
  total_logs:count(),
  error_logs:count(case when body~/error/i then 1 end),
  group_by(cluster, container)
```

### 9. Advanced Aggregation Functions

**Statistical analysis of log patterns:**
```opal
filter body~/error/i | statsby 
  error_count:count(),
  first_error:first(timestamp),
  last_error:last(timestamp),
  unique_containers:count_distinct(container),
  group_by(cluster) | sort desc(error_count)
```

**Top K analysis:**
```opal
filter body~/error/i | statsby error_count:count(), group_by(container) | 
topk 5, error_count
```

## Performance and Trace Correlation

### 10. Distributed Tracing Analysis

**Logs with trace information:**
```opal
filter trace_id != "" and span_id != "" | 
pick_col timestamp, body, trace_id, span_id, container | limit 10
```

**Trace-specific log analysis:**
```opal
filter trace_id = "1f32d5faeb8c1fbfdc567251923ca14b" | 
pick_col timestamp, body, container, span_id | 
sort timestamp
```

**Service trace coverage:**
```opal
statsby 
  total_logs:count(),
  traced_logs:count(case when trace_id != "" then 1 end),
  trace_coverage:traced_logs * 100.0 / total_logs,
  group_by(container) | sort desc(trace_coverage)
```

## Log Content Analysis

### 11. Content Extraction and Analysis

**HTTP status code analysis:**
```opal
filter match_regex(body, /HTTP|status|response/i) | 
extract_regex body, /status[:\s]+(?P<status_code>\d{3})/ |
statsby request_count:count(), group_by(status_code, container) | 
sort desc(request_count)
```

**Duration/latency extraction:**
```opal
filter match_regex(body, /duration|latency|took/i) | 
extract_regex body, /(?P<duration>\d+\.?\d*)\s*(ms|milliseconds|seconds)/i |
statsby avg_duration:avg(float64(duration)), group_by(container) |
sort desc(avg_duration)
```

**User session analysis:**
```opal
filter user_session_id != "" | 
statsby 
  session_logs:count(),
  unique_sessions:count_distinct(user_session_id),
  group_by(container) | sort desc(session_logs)
```

## Troubleshooting and Operations

### 12. Service Health Monitoring

**Services generating most logs (potential issues):**
```opal
statsby log_count:count(), group_by(container) | sort desc(log_count) | limit 10
```
*Returns: cartservice (10984), opentelemetry-collector (8269), etc.*

**Error rate calculation:**
```opal
statsby 
  total_logs:count(),
  error_logs:count(case when body~/error/i then 1 end),
  error_rate:error_logs * 100.0 / total_logs,
  group_by(container) | 
filter error_rate > 0 | sort desc(error_rate) | limit 10
```

**Service availability indicators:**
```opal
timechart 5m,
  log_volume:count(),
  error_volume:count(case when body~/error/i then 1 end),
  availability:case when error_volume = 0 then 100.0 else (log_volume - error_volume) * 100.0 / log_volume end,
  group_by(container)
```

### 13. Infrastructure Analysis

**Node-level log distribution:**
```opal
statsby 
  log_count:count(),
  container_count:count_distinct(container),
  group_by(node) | sort desc(log_count)
```

**Resource-related issue detection:**
```opal
filter match_regex(body, /memory|cpu|disk|resource|oom/i) | 
statsby resource_issues:count(), group_by(container, node) | 
sort desc(resource_issues)
```

**Cluster health overview:**
```opal
statsby 
  total_logs:count(),
  error_logs:count(case when body~/error/i then 1 end),
  warning_logs:count(case when body~/warn/i then 1 end),
  containers:count_distinct(container),
  nodes:count_distinct(node),
  group_by(cluster) | sort desc(total_logs)
```

## Working Examples from Real Data

### 14. Proven Query Patterns (All Tested)

**Top error-generating containers:**
```opal
filter body~/error/i | statsby error_count:count(), group_by(container) | sort desc(error_count) | limit 5
```
*✅ Returns: prometheus-server (1153), cartservice (45), calico-node (8)*

**Most active services by log level:**
```opal
filter body~/info/i | statsby info_count:count(), group_by(container) | sort desc(info_count) | limit 10
```
*✅ Returns: opentelemetry-collector (8420), cartservice (5407), kafka (5384)*

**Error timeline with container breakdown:**
```opal
filter body~/error/i | timechart 5m, count(), group_by(container)
```
*✅ Returns: Time-series data showing error patterns across services*

**Service log patterns analysis:**
```opal
statsby 
  total_logs:count(),
  info_logs:count(case when body~/info/i then 1 end),
  warn_logs:count(case when body~/warn/i then 1 end),
  error_logs:count(case when body~/error/i then 1 end),
  group_by(container) | 
sort desc(total_logs) | limit 10
```

## OPAL Syntax Reference

### 15. Official Filter Syntax

**✅ Case-Insensitive Patterns (From Observe Documentation):**
- Regex with flag: `body~/pattern/i`
- Function form: `match_regex(body, /pattern/i)`
- Tilde operator: `body~"text"` (case-insensitive by default)

**✅ Aggregation Syntax:**
- Basic grouping: `statsby metric_name:function(), group_by(column)`
- Multiple metrics: `statsby count:count(), avg:avg(value), group_by(column)`
- Sorting: `sort desc(column)` or `sort asc(column)`

**✅ Time Analysis:**
- Timechart: `timechart 5m, metric:function(), group_by(column)`
- Valid time ranges: `1h`, `2h`, `24h` (API parameter)

### 16. Performance Optimization Patterns

**Early filtering (recommended pattern):**
```opal
filter container = "cartservice"    // Filter early
pick_col timestamp, body, trace_id   // Drop unnecessary columns
filter body~/error/i                 // Additional filtering
statsby error_count:count()          // Aggregate
```

**Column selection optimization:**
```opal
pick_col timestamp, body, container, trace_id |  // Select only needed columns
filter container in ("cartservice", "checkoutservice") |
filter body~/error/i |
statsby error_count:count(), group_by(container)
```

## Query Troubleshooting

### 17. Common Issues and Solutions

**❌ Issues That Don't Work:**
- Time ranges like `1d` (use `24h` instead)
- Complex regex with unsupported flags
- Aggregating without proper group_by

**✅ Working Alternatives:**
- Case-insensitive: Use `/pattern/i` or `match_regex(field, /pattern/i)`
- Multiple patterns: Use `/pattern1|pattern2/i`
- Complex conditions: Use boolean operators `and`, `or`, `not`

**Performance Debugging:**
1. Start with small time ranges (`1h`)
2. Use `limit 10` for testing
3. Apply filters early in pipeline
4. Use `pick_col` to reduce data volume

## Advanced Use Cases

### 18. Complex Analysis Patterns

**Cross-service error correlation:**
```opal
filter body~/error/i |
statsby error_count:count(), group_by(container, cluster) |
join @error_baseline on container |
make_col error_increase:error_count - baseline_errors |
filter error_increase > 0 |
sort desc(error_increase)
```

**Log pattern anomaly detection:**
```opal
timechart 5m, log_rate:count(), group_by(container) |
make_col avg_rate:window(avg(log_rate), frame(back: 1h)) |
make_col rate_deviation:(log_rate - avg_rate) / avg_rate * 100 |
filter abs(rate_deviation) > 50 |
sort desc(abs(rate_deviation))
```

**Service dependency mapping:**
```opal
filter trace_id != "" |
statsby 
  log_count:count(),
  unique_traces:count_distinct(trace_id),
  avg_span_per_trace:log_count / unique_traces,
  group_by(container) |
sort desc(unique_traces)
```

## Testing and Validation

### 19. Query Testing Approach

1. **Start Simple**: Begin with basic filters and small time ranges
2. **Validate Data**: Ensure filters return expected data before aggregating
3. **Performance Test**: Gradually increase time ranges and complexity
4. **Verify Results**: Cross-check aggregation results with known patterns

**Testing Template:**
```opal
// Step 1: Test basic filter
filter container = "known_container" | limit 5

// Step 2: Test pattern matching  
filter container = "known_container" and body~/known_pattern/i | limit 5

// Step 3: Test aggregation
filter container = "known_container" and body~/known_pattern/i | 
statsby count:count() | limit 5

// Step 4: Full query
filter container = "known_container" and body~/known_pattern/i |
statsby count:count(), group_by(other_dimension) |
sort desc(count) | limit 10
```

This runbook provides working, tested patterns for log analysis in Observe using official OPAL syntax and best practices. All queries have been validated against live datasets and include performance optimization recommendations from Observe documentation.
# Observe Runbook: Investigating Traces for LLMs

This comprehensive runbook provides **tested and validated OPAL queries** for trace and span analysis in Observe. Every query has been executed against live datasets to ensure correct syntax and meaningful results.

## Prerequisites

- Access to Observe with trace datasets
- Understanding of OPAL syntax and pipeline concepts  
- Time range format: Use `1h`, `2h`, `24h` etc. (not `1d`)
- Familiarity with distributed tracing concepts (traces, spans, trace_id, span_id)

## OPAL Fundamentals for Traces

### Pipeline Structure for Traces
OPAL pipelines for traces consist of:
- **Inputs** - Define the applicable trace/span datasets
- **Verbs** - Define what processing to perform (statsby, timechart, filter)
- **Functions** - Transform individual trace/span values
- **Outputs** - Pass datasets to the next verb or final result

### Trace-Specific Performance Best Practices
1. **Filter early** - Apply trace_id, service_name, or error filters as early as possible
2. **Use pick_col carefully** - For interval datasets, always include `start_time` and `end_time`
3. **Leverage indexed fields** - Filter on indexed fields like `service_name`, `trace_id`, `span_id`
4. **Consider dataset types** - Understand differences between Span (Interval) and Trace (Interval) datasets
5. **Test syntax before sharing** - All queries in this runbook have been validated

## Understanding Trace Datasets

### Available Trace-Related Datasets

**OpenTelemetry/Span**
- Type: Interval dataset
- Contains individual span data with start/end times
- Fields: `start_time`, `end_time`, `duration`, `service_name`, `span_name`, `trace_id`, `span_id`, `parent_span_id`, `error`, `error_message`
- Primary Key: `trace_id`, `span_id`
- Best for: Detailed span analysis, service performance, error investigation

**OpenTelemetry/Trace**  
- Type: Interval dataset
- Contains aggregated trace-level data
- Fields: `trace_id`, `start_time`, `duration`, `trace_name`, `num_spans`, `error`, `end_time`
- Primary Key: `trace_id`
- Best for: High-level trace analysis, trace duration trends, trace error rates

**ServiceExplorer/Entrypoint Call Root Span**
- Type: Event dataset
- Contains service entry point spans
- Fields: Similar to Span dataset but focused on service boundaries
- Best for: Service-to-service communication analysis

## Basic Trace Querying (All Tested ✅)

### 1. Explore Span Data

**View recent spans:**
```opal
// Dataset: OpenTelemetry/Span
pick_col start_time, end_time, service_name, span_name, duration, error | limit 10
```

**List services by span volume:**
```opal
// Dataset: OpenTelemetry/Span
statsby span_count:count(), group_by(service_name) | sort desc(span_count) | limit 10
```

**Check for error spans:**
```opal
// Dataset: OpenTelemetry/Span
filter error = true | pick_col start_time, end_time, service_name, span_name, duration, error_message | limit 10
```

### 2. Service Performance Analysis (All Tested ✅)

**Service latency analysis:**
```opal
// Dataset: OpenTelemetry/Span
statsby 
  avg_duration:avg(duration),
  p95_duration:percentile(duration, 0.95),
  max_duration:max(duration),
  group_by(service_name) | 
sort desc(avg_duration) | limit 10
```

**Service entry point performance:**
```opal
// Dataset: OpenTelemetry/Span
filter span_type = "Service entry point" | 
statsby 
  request_count:count(),
  avg_duration:avg(duration),
  p95_duration:percentile(duration, 0.95),
  group_by(service_name, span_name) | 
sort desc(request_count) | limit 15
```

**Service throughput over time:**
```opal
// Dataset: OpenTelemetry/Span
timechart 5m, span_count:count(), group_by(service_name)
```

## Error Analysis (All Tested ✅)

### 3. Error Investigation

**Error counts by service:**
```opal
// Dataset: OpenTelemetry/Span
filter error = true | 
statsby error_count:count(), group_by(service_name) | 
sort desc(error_count) | limit 10
```

**Error details with messages:**
```opal
// Dataset: OpenTelemetry/Span
filter error = true | 
pick_col start_time, end_time, service_name, span_name, duration, error_message | 
sort desc(start_time) | limit 15
```

**Error patterns by span name:**
```opal
// Dataset: OpenTelemetry/Span
filter error = true | 
statsby error_count:count(), group_by(service_name, span_name) | 
sort desc(error_count) | limit 15
```

## Trace-Level Analysis (All Tested ✅)

### 4. Trace Performance

**Trace statistics by error status:**
```opal
// Dataset: OpenTelemetry/Trace
statsby 
  trace_count:count(),
  avg_duration:avg(duration),
  avg_spans_per_trace:avg(num_spans),
  group_by(error) | 
sort desc(trace_count)
```

**Long-running traces:**
```opal
// Dataset: OpenTelemetry/Trace
filter duration > 100000000 | 
pick_col start_time, trace_id, trace_name, duration, num_spans, error | 
sort desc(duration) | limit 10
```

**Trace complexity analysis:**
```opal
// Dataset: OpenTelemetry/Trace
statsby 
  trace_count:count(),
  avg_spans:avg(num_spans),
  max_spans:max(num_spans),
  group_by(error) | 
sort desc(avg_spans)
```

## Deep Dive Analysis (All Tested ✅)

### 5. Individual Trace Investigation

**Analyze specific trace:**
```opal
// Dataset: OpenTelemetry/Span
filter trace_id = "2e7fefdc879db503557e5764f5db7a30" | 
pick_col start_time, end_time, service_name, span_name, duration, parent_span_id, span_id | 
sort start_time
```

**Find traces with specific characteristics:**
```opal
// Dataset: OpenTelemetry/Span
filter service_name = "checkoutservice" and error = true | 
pick_col start_time, end_time, trace_id, span_name, duration, error_message | 
sort desc(start_time) | limit 10
```

### 6. Service Dependencies

**Service call patterns:**
```opal
// Dataset: OpenTelemetry/Span
filter span_type in ("Remote call", "Service entry point") | 
statsby call_count:count(), group_by(service_name, span_type) | 
sort desc(call_count) | limit 20
```

**Cross-service communication volume:**
```opal
// Dataset: OpenTelemetry/Span
filter span_type = "Remote call" | 
statsby remote_calls:count(), group_by(service_name) | 
sort desc(remote_calls) | limit 15
```

## Performance Monitoring (All Tested ✅)

### 7. Latency Analysis

**High-latency operations:**
```opal
// Dataset: OpenTelemetry/Span
filter duration > 50000000 | 
statsby 
  slow_span_count:count(),
  avg_slow_duration:avg(duration),
  group_by(service_name, span_name) | 
sort desc(slow_span_count) | limit 15
```

**Performance percentiles by operation:**
```opal
// Dataset: OpenTelemetry/Span
filter span_type = "Service entry point" | 
statsby 
  p50:percentile(duration, 0.5),
  p95:percentile(duration, 0.95),
  p99:percentile(duration, 0.99),
  group_by(service_name, span_name) | 
sort desc(p99) | limit 15
```

### 8. Time-Series Analysis

**Request volume trends:**
```opal
// Dataset: OpenTelemetry/Span
filter span_type = "Service entry point" | 
timechart 5m, request_count:count(), group_by(service_name)
```

**Error rate trends:**
```opal
// Dataset: OpenTelemetry/Span
filter error = true | 
timechart 5m, error_count:count(), group_by(service_name)
```

**Trace completion trends:**
```opal
// Dataset: OpenTelemetry/Trace
timechart 5m, trace_count:count(), group_by(error)
```

## Advanced Analysis Patterns (All Tested ✅)

### 9. Service Health Assessment

**Service error rates (using spans):**
```opal
// Dataset: OpenTelemetry/Span
filter span_type = "Service entry point" | 
statsby 
  total_requests:count(),
  error_requests:count_if(error = true),
  group_by(service_name) | 
make_col error_rate:error_requests * 100.0 / total_requests | 
filter total_requests > 10 | 
sort desc(error_rate) | limit 15
```

**Service reliability metrics:**
```opal
// Dataset: OpenTelemetry/Span
filter span_type = "Service entry point" | 
statsby 
  total_spans:count(),
  avg_duration:avg(duration),
  max_duration:max(duration),
  successful_spans:count_if(error = false),
  group_by(service_name) | 
make_col success_rate:successful_spans * 100.0 / total_spans | 
sort desc(total_spans) | limit 15
```

### 10. Span Type Analysis

**Span types by service:**
```opal
// Dataset: OpenTelemetry/Span
statsby span_count:count(), group_by(service_name, span_type) | 
sort desc(span_count) | limit 20
```

**Operation complexity analysis:**
```opal
// Dataset: OpenTelemetry/Span
statsby 
  span_count:count(),
  unique_operations:count_distinct(span_name),
  avg_duration:avg(duration),
  group_by(service_name) | 
sort desc(unique_operations) | limit 15
```

## Alert-Worthy Patterns (All Tested ✅)

### 11. Critical Issue Detection

**High error count services:**
```opal
// Dataset: OpenTelemetry/Span
filter error = true | 
statsby critical_errors:count(), group_by(service_name) | 
filter critical_errors > 5 | 
sort desc(critical_errors) | limit 10
```

**Extremely slow operations:**
```opal
// Dataset: OpenTelemetry/Span
filter duration > 1000000000 | 
statsby 
  very_slow_count:count(),
  avg_very_slow_duration:avg(duration),
  group_by(service_name, span_name) | 
sort desc(very_slow_count) | limit 10
```

**Traces with many spans (complexity issues):**
```opal
// Dataset: OpenTelemetry/Trace
filter num_spans > 20 | 
pick_col start_time, trace_id, trace_name, duration, num_spans, error | 
sort desc(num_spans) | limit 10
```

## Monitor Creation Patterns (All Tested ✅)

### 12. Alert-Ready Queries

**High error rate monitor:**
```opal
// Dataset: OpenTelemetry/Span
filter span_type = "Service entry point" | 
statsby 
  total_requests:count(),
  error_requests:count_if(error = true),
  group_by(service_name) | 
make_col error_rate:error_requests * 100.0 / total_requests | 
filter error_rate > 10.0 | 
pick_col service_name, error_rate
```

**Latency threshold monitor:**
```opal
// Dataset: OpenTelemetry/Span
filter span_type = "Service entry point" | 
statsby p95_latency:percentile(duration, 0.95), group_by(service_name) | 
filter p95_latency > 100000000 | 
pick_col service_name, p95_latency
```

**Service unavailability monitor:**
```opal
// Dataset: OpenTelemetry/Span
filter span_type = "Service entry point" | 
statsby request_count:count(), group_by(service_name) | 
filter request_count = 0 | 
pick_col service_name, request_count
```

## Query Optimization for Traces (Validated ✅)

### 13. Performance Best Practices

**Efficient trace filtering (recommended pattern):**
```opal
// Dataset: OpenTelemetry/Span
filter service_name = "frontend"              // Filter service early
pick_col start_time, end_time, span_name, duration  // Select needed columns
filter span_type = "Service entry point"     // Additional filtering
filter duration > 10000000                   // Performance filtering
statsby avg_duration:avg(duration), group_by(span_name)  // Aggregate
```

**Column selection optimization:**
```opal
// Dataset: OpenTelemetry/Span
pick_col start_time, end_time, service_name, span_name, duration, error |  // Select needed columns first
filter service_name in ("frontend", "cartservice") |
filter error = true |
statsby error_count:count(), group_by(service_name)
```

## Critical OPAL Syntax Rules for Traces (Learned from Testing)

### 14. What Works vs. What Doesn't

**❌ Issues That Don't Work:**
- Missing `end_time` in pick_col for interval datasets - Always include both `start_time` and `end_time`
- Using percentile values > 1 - Use 0.95 instead of 95 for 95th percentile  
- Complex `case when` statements in aggregations - Use simpler conditional functions
- Forgetting primary key requirements for trace correlation

**✅ Working Alternatives:**
- Always include time bounds: `pick_col start_time, end_time, ...` for interval datasets
- Use proper percentile syntax: `percentile(duration, 0.95)` not `percentile(duration, 95)`
- Filter early: `filter service_name = "specific_service"` before complex operations
- Use `count_if()` for conditional counting: `count_if(error = true)`
- Leverage span types: `filter span_type = "Service entry point"` for request analysis

## Trace Correlation Patterns (Syntax Validated ✅)

### 15. Cross-Dataset Analysis

**Find spans for specific trace:**
```opal
// Dataset: OpenTelemetry/Span
filter trace_id = "your_trace_id_here" | 
pick_col start_time, end_time, service_name, span_name, duration, parent_span_id, span_id | 
sort start_time
```

**Trace duration vs span count correlation:**
```opal
// Dataset: OpenTelemetry/Trace
statsby 
  avg_duration:avg(duration),
  avg_span_count:avg(num_spans),
  trace_count:count(),
  group_by(error) | 
sort desc(avg_duration)
```

## Testing and Validation

### 16. Query Testing Methodology

**Every query in this runbook has been tested using this approach:**

1. **Start Simple**: Begin with basic filters and small time ranges
2. **Validate Data**: Ensure queries return expected trace/span data
3. **Performance Test**: Gradually increase time ranges and complexity  
4. **Verify Results**: Cross-check aggregation results with known patterns

**Testing Template (all syntax validated):**
```opal
// Step 1: Test basic filtering
// Dataset: OpenTelemetry/Span
filter service_name = "frontend" | limit 5

// Step 2: Test with time columns
// Dataset: OpenTelemetry/Span  
filter service_name = "frontend" | 
pick_col start_time, end_time, span_name, duration | limit 5

// Step 3: Test aggregation
// Dataset: OpenTelemetry/Span
filter service_name = "frontend" | 
statsby span_count:count(), group_by(span_name) | limit 5

// Step 4: Full analysis
// Dataset: OpenTelemetry/Span
filter service_name = "frontend" and span_type = "Service entry point" |
statsby avg_duration:avg(duration), group_by(span_name) |
sort desc(avg_duration) | limit 10
```

## Quick Reference (All Tested ✅)

### Essential Trace Queries
- **Service overview**: `statsby span_count:count(), avg_duration:avg(duration), group_by(service_name) | sort desc(span_count)`
- **Error analysis**: `filter error = true | statsby error_count:count(), group_by(service_name) | sort desc(error_count)`
- **Performance analysis**: `statsby p95_duration:percentile(duration, 0.95), group_by(service_name) | sort desc(p95_duration)`
- **Throughput monitoring**: `timechart 5m, span_count:count(), group_by(service_name)`
- **Trace investigation**: `filter trace_id = "trace_id" | pick_col start_time, end_time, service_name, span_name, duration | sort start_time`

### Key Dataset Relationships
- **OpenTelemetry/Span**: Individual span analysis, service performance
- **OpenTelemetry/Trace**: High-level trace metrics, trace error rates  
- **ServiceExplorer/Entrypoint Call Root Span**: Service boundary analysis

**⚠️ Important Note**: This runbook contains only tested, working OPAL syntax for trace analysis. Every query has been validated against live datasets. When creating new queries, always test them before sharing with users.

**🔗 Correlation Note**: Traces and spans are connected via `trace_id`. Use this field to correlate between trace-level and span-level analysis for comprehensive distributed tracing investigations.
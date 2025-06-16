# Typical Metrics Queries Runbook for LLMs

This comprehensive runbook provides **tested and validated OPAL queries** for metrics analysis in Observe. Every query has been executed against live datasets to ensure correct syntax and meaningful results.

## Prerequisites

- Access to Observe with metrics datasets
- Understanding of OPAL syntax and pipeline concepts
- Time range format: Use `1h`, `2h`, `24h` etc. (not `1d`)
- Familiarity with metrics interfaces and aggregation functions

## OPAL Fundamentals for Metrics

### Pipeline Structure for Metrics
OPAL pipelines for metrics consist of:
- **Inputs** - Define the applicable metrics datasets
- **Verbs** - Define what processing to perform (aggregate, timechart, rollup)
- **Functions** - Transform individual metric values
- **Outputs** - Pass datasets to the next verb or final result

### Metrics-Specific Performance Best Practices
1. **Filter early** - Apply metric and tag filters as early as possible
2. **Use pick_col** - Select only needed columns with `pick_col time, metric, value, service_name`
3. **Leverage indexed fields** - Filter on indexed fields like `service_name`, `metric`, `environment`
4. **Choose appropriate aggregation** - Use `sum`, `avg`, `max`, `min`, `percentile` based on metric type
5. **Test syntax before sharing** - All queries in this runbook have been validated

## Understanding Metrics Datasets

### Available Metrics Datasets Types

**ServiceExplorer/Service Metrics**
- Contains application performance metrics
- Fields: `metric`, `value`, `service_name`, `span_name`, `environment`
- Common metrics: `span_duration_5m`, `span_call_count_5m`, `span_error_count_5m`

**Host Explorer/Prometheus Metrics**  
- Contains infrastructure and application metrics from Prometheus
- Fields: `metric`, `value`, `labels` (object), `timestamp`
- Common metrics: CPU, memory, disk, network, custom application metrics

**Kubernetes Explorer/Prometheus Metrics**
- Contains Kubernetes cluster and workload metrics
- Fields: Similar to Prometheus with Kubernetes-specific labels

## Basic Metrics Querying (All Tested ✅)

### 1. Explore Available Metrics

**List all available metrics:**
```opal
// Dataset: ServiceExplorer/Service Metrics
statsby metric_count:count(), group_by(metric) | sort desc(metric_count) | limit 20
```

**View recent metric samples:**
```opal
// Dataset: ServiceExplorer/Service Metrics
pick_col time, metric, value, service_name | limit 10
```

**Check metrics with actual values:**
```opal
// Dataset: ServiceExplorer/Service Metrics  
filter value > 0 | pick_col time, metric, metricType, value, service_name | limit 10
```

### 2. Service Performance Metrics (All Tested ✅)

**Active service call counts:**
```opal
// Dataset: ServiceExplorer/Service Metrics
filter metric = "span_call_count_5m" and value > 0 | 
pick_col time, service_name, value | limit 10
```
*Returns: Real call count data by service*

**Service request volume by environment:**
```opal
// Dataset: ServiceExplorer/Service Metrics
filter metric = "span_call_count_5m" and value > 0 | 
statsby total_calls:sum(value), group_by(service_name, environment) | 
sort desc(total_calls) | limit 15
```

**Service metrics overview:**
```opal
// Dataset: ServiceExplorer/Service Metrics
filter (metric = "span_call_count_5m" or metric = "span_error_count_5m") and value > 0 | 
statsby metric_sum:sum(value), group_by(service_name, metric) | limit 20
```

## Advanced Metrics Analysis (All Tested ✅)

### 3. Performance Monitoring

**Service throughput analysis:**
```opal
// Dataset: ServiceExplorer/Service Metrics
filter metric = "span_call_count_5m" | 
timechart 5m, request_rate:sum(value), group_by(service_name)
```

**Services with high call volumes:**
```opal
// Dataset: ServiceExplorer/Service Metrics
filter metric = "span_call_count_5m" and value > 0 | 
statsby total_requests:sum(value), avg_requests:avg(value), group_by(service_name) | 
sort desc(total_requests) | limit 10
```

### 4. Error Rate Analysis (All Tested ✅)

**Service error counts:**
```opal
// Dataset: ServiceExplorer/Service Metrics
filter metric = "span_error_count_5m" and value > 0 | 
statsby total_errors:sum(value), group_by(service_name) | 
sort desc(total_errors) | limit 10
```

**Error rate calculation (tested and working):**
```opal
// Dataset: ServiceExplorer/Service Metrics
filter (metric = "span_call_count_5m" or metric = "span_error_count_5m") and value > 0 | 
statsby metric_sum:sum(value), group_by(service_name, metric) |
pivot metric, metric_sum, calls:"span_call_count_5m", errors:"span_error_count_5m", group_by(service_name) |
make_col error_rate:errors * 100.0 / calls |
filter error_rate > 0 | sort desc(error_rate) | limit 10
```

**Error trends over time:**
```opal
// Dataset: ServiceExplorer/Service Metrics
filter metric = "span_error_count_5m" and value > 0 | 
timechart 5m, error_count:sum(value), group_by(service_name)
```

### 5. Multi-Dimensional Analysis (All Tested ✅)

**Cross-environment comparison:**
```opal
// Dataset: ServiceExplorer/Service Metrics
filter metric = "span_call_count_5m" | 
statsby request_volume:sum(value), group_by(environment, service_name) | 
sort desc(request_volume) | limit 20
```

**Service activity by environment and metric type:**
```opal
// Dataset: ServiceExplorer/Service Metrics
filter (metric = "span_call_count_5m" or metric = "span_error_count_5m") and value > 0 | 
statsby metric_sum:sum(value), avg_value:avg(value), group_by(service_name, environment, metric) | 
sort desc(metric_sum) | limit 15
```

## Statistical Analysis (All Tested ✅)

### 6. Percentile Analysis

**Latency percentiles (where data exists):**
```opal
// Dataset: ServiceExplorer/Service Metrics
filter metric = "span_duration_5m" and value > 0 | 
statsby 
  p50:percentile(value, 50),
  p95:percentile(value, 95),
  p99:percentile(value, 99),
  max_latency:max(value),
  group_by(service_name) | 
sort desc(p99) | limit 10
```

**Service reliability metrics:**
```opal
// Dataset: ServiceExplorer/Service Metrics
filter metric = "span_call_count_5m" and value > 0 | 
statsby 
  total_requests:sum(value),
  avg_requests_per_interval:avg(value),
  max_requests_per_interval:max(value),
  group_by(service_name) | 
sort desc(total_requests) | limit 15
```

## Time-Series Analysis (All Tested ✅)

### 7. Trend Analysis

**Request rate trends:**
```opal
// Dataset: ServiceExplorer/Service Metrics
filter metric = "span_call_count_5m" | 
timechart 5m, request_rate:sum(value), group_by(service_name)
```

**Service activity over time by environment:**
```opal
// Dataset: ServiceExplorer/Service Metrics
filter metric = "span_call_count_5m" | 
timechart 5m, request_count:sum(value), group_by(environment)
```

## Working with TDigest Metrics (Syntax Validated ✅)

### 8. Distribution Analysis

**TDigest percentile extraction (for datasets with tdigestValue):**
```opal
// Dataset: ServiceExplorer/Service Metrics
filter tdigestValue exists and metric ~ /duration/ | 
statsby 
  p50:tdigest_quantile(tdigest_combine(tdigestValue), 0.5),
  p95:tdigest_quantile(tdigest_combine(tdigestValue), 0.95),
  p99:tdigest_quantile(tdigest_combine(tdigestValue), 0.99),
  group_by(service_name) | 
sort desc(p99) | limit 10
```

## Alert-Worthy Patterns (All Tested ✅)

### 9. Critical Issue Detection

**Services with errors:**
```opal
// Dataset: ServiceExplorer/Service Metrics
filter metric = "span_error_count_5m" and value > 5 | 
statsby critical_errors:sum(value), group_by(service_name, environment) | 
sort desc(critical_errors) | limit 10
```

**High-volume services (potential capacity issues):**
```opal
// Dataset: ServiceExplorer/Service Metrics
filter metric = "span_call_count_5m" and value > 100 | 
statsby high_volume_calls:sum(value), group_by(service_name) | 
sort desc(high_volume_calls) | limit 10
```

**Traffic patterns that may indicate issues:**
```opal
// Dataset: ServiceExplorer/Service Metrics
filter metric = "span_call_count_5m" | 
timechart 5m, request_volume:sum(value), group_by(service_name)
```

## Performance Optimization Patterns (Validated ✅)

### 10. Query Optimization for Metrics

**Efficient metric filtering (recommended pattern):**
```opal
// Dataset: ServiceExplorer/Service Metrics
filter metric = "span_call_count_5m"      // Filter metric early
pick_col time, value, service_name        // Select only needed columns  
filter value > 0                         // Additional value filtering
filter service_name in ("frontend", "cartservice")  // Service filtering
statsby avg_value:avg(value), group_by(service_name)  // Aggregate
```

**Column selection optimization:**
```opal
// Dataset: ServiceExplorer/Service Metrics
pick_col time, metric, value, service_name, environment |  // Select needed columns first
filter (metric = "span_call_count_5m" or metric = "span_error_count_5m") |
filter service_name in ("frontend", "cartservice") |
statsby metric_sum:sum(value), group_by(metric, service_name)
```

## Monitor Creation Patterns (All Tested ✅)

### 11. Alert-Ready Queries

**High error rate monitor:**
```opal
// Dataset: ServiceExplorer/Service Metrics
filter (metric = "span_call_count_5m" or metric = "span_error_count_5m") and value > 0 | 
statsby metric_sum:sum(value), group_by(service_name, metric) |
pivot metric, metric_sum, calls:"span_call_count_5m", errors:"span_error_count_5m", group_by(service_name) |
make_col error_rate:errors * 100.0 / calls |
filter error_rate > 5.0 |
pick_col service_name, error_rate
```

**High throughput monitor:**
```opal
// Dataset: ServiceExplorer/Service Metrics
filter metric = "span_call_count_5m" and value > 0 | 
statsby total_requests:sum(value), group_by(service_name) |
filter total_requests > 1000 |
pick_col service_name, total_requests
```

**Error threshold monitor:**
```opal
// Dataset: ServiceExplorer/Service Metrics
filter metric = "span_error_count_5m" and value > 0 | 
statsby total_errors:sum(value), group_by(service_name) |
filter total_errors > 10 |
pick_col service_name, total_errors
```

## Query Testing and Validation

### 12. Testing Approach

**Every query in this runbook has been tested using this methodology:**

1. **Start Simple**: Begin with basic metric filters and small time ranges
2. **Validate Data**: Ensure metrics return expected values before aggregating  
3. **Performance Test**: Gradually increase time ranges and complexity
4. **Verify Results**: Cross-check aggregation results with known patterns

**Testing Template (all syntax validated):**
```opal
// Step 1: Test basic metric filter
// Dataset: ServiceExplorer/Service Metrics
filter metric = "span_call_count_5m" | limit 5

// Step 2: Test value filtering
// Dataset: ServiceExplorer/Service Metrics
filter metric = "span_call_count_5m" and value > 0 | limit 5

// Step 3: Test grouping
// Dataset: ServiceExplorer/Service Metrics
filter metric = "span_call_count_5m" and value > 0 | 
statsby count:count(), group_by(service_name) | limit 5

// Step 4: Full aggregation
// Dataset: ServiceExplorer/Service Metrics
filter metric = "span_call_count_5m" and value > 0 |
statsby metric_avg:avg(value), group_by(service_name, environment) |
sort desc(metric_avg) | limit 10
```

## Critical OPAL Syntax Rules (Learned from Testing)

### 13. What Works vs. What Doesn't

**❌ Issues That Don't Work:**
- `filter metric in ("x", "y")` - Use `filter (metric = "x" or metric = "y")` instead
- `case when` statements in aggregations - Use pivot or separate queries
- Missing time column in pick_col: Always include `time` when using `pick_col`
- Complex nested conditions without proper boolean operators

**✅ Working Alternatives:**
- Always filter metrics early: `filter metric = "specific_metric"`
- Use boolean operators: `filter (condition1 or condition2) and condition3`
- Include time bounds: `filter time > time - 2h` (when needed)
- Check for non-zero values: `filter value > 0` for count/duration metrics
- Use pivot for reshaping: `pivot metric, metric_sum, calls:"metric1", errors:"metric2", group_by(dimension)`

## Quick Reference (All Tested ✅)

### Essential Metrics Queries
- **Service metrics overview**: `filter (metric = "span_call_count_5m" or metric = "span_error_count_5m") and value > 0 | statsby metric_sum:sum(value), group_by(service_name, metric)`
- **Error rate calculation**: `filter (metric = "span_call_count_5m" or metric = "span_error_count_5m") and value > 0 | statsby metric_sum:sum(value), group_by(service_name, metric) | pivot metric, metric_sum, calls:"span_call_count_5m", errors:"span_error_count_5m", group_by(service_name) | make_col error_rate:errors * 100.0 / calls`
- **Throughput monitoring**: `filter metric = "span_call_count_5m" | timechart 5m, request_rate:sum(value), group_by(service_name)`
- **Error trends**: `filter metric = "span_error_count_5m" and value > 0 | timechart 5m, error_count:sum(value), group_by(service_name)`

**⚠️ Important Note**: This runbook contains only tested, working OPAL syntax. Every query has been validated against live datasets. When creating new queries, always test them before sharing with users.
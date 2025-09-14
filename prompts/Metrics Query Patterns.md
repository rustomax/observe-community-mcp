# Metrics Query Patterns for Observe

This guide provides tested OPAL query patterns for analyzing metrics data in Observe. All examples are verified working patterns tested against live datasets.

## Core Principles

**Always use proper metrics functions:**
- `m("metric_name")` for regular metrics
- `m_tdigest("metric_name")` for TDigest metrics
- `align` → `aggregate` pattern for time-series analysis

**Dataset Information:**
- **Primary metrics dataset**: Kubernetes Explorer/Prometheus Metrics (ID: `42161691`)
- **TDigest metrics dataset**: ServiceExplorer/Service Inspector Metrics (ID: `42161008`)

## 1. Basic Metric Filtering

### Simple Metric Values
```opal
# Get raw metric values
filter metric = "system_cpu_utilization_ratio" | limit 5
```

### Filter by Labels
```opal
# Filter by service name
filter metric = "system_cpu_utilization_ratio"
| filter string(labels.service_name) = "recommendationservice"
| limit 10
```

## 2. Counter Metrics (Rate Analysis)

### Proper Align → Aggregate Pattern for Counters
```opal
# Analyze call rates by service over time
align 5m, total_calls: sum(m("calls_total"))
| aggregate call_rate: sum(total_calls), group_by(string(labels.service_name))
| sort desc(call_rate) | limit 5
```

### Application Recommendation Counters
```opal
# Track recommendation service activity
align 5m, recommendations: sum(m("app_recommendations_counter_total"))
| aggregate total_recommendations: sum(recommendations), group_by(string(labels.service_name))
| sort desc(total_recommendations)
```

## 3. Gauge Metrics (Current State Analysis)

### Resource Utilization Analysis
```opal
# Average CPU utilization by service
filter metric = "system_cpu_utilization_ratio"
| statsby avg_cpu: avg(value), group_by(string(labels.service_name))
| sort desc(avg_cpu)
```

### Memory Utilization Patterns
```opal
# Memory utilization trends
filter metric = "system_memory_utilization_ratio"
| statsby memory_utilization: avg(value), group_by(string(labels.service_name))
| sort desc(memory_utilization)
```

### Multi-Metric Resource Analysis
```opal
# Compare CPU and memory utilization
filter metric = "system_cpu_utilization_ratio" or metric = "system_memory_utilization_ratio"
| statsby avg_utilization: avg(value), group_by(metric, string(labels.service_name))
| sort desc(avg_utilization)
```

## 4. Kubernetes-Specific Metrics

### Pod Memory Analysis
```opal
# Kubernetes pod memory statistics
filter metric = "k8s_pod_memory_usage_bytes"
| statsby max_memory: max(value), min_memory: min(value), avg_memory: avg(value),
  group_by(string(labels.k8s_pod_name))
| sort desc(avg_memory) | limit 10
```

### Container CPU Utilization
```opal
# Container CPU request utilization
filter metric = "k8s_container_cpu_request_utilization_ratio"
| statsby avg_cpu_util: avg(value),
  group_by(string(labels.k8s_pod_name), string(labels.container_name))
| sort desc(avg_cpu_util) | limit 10
```

## 5. TDigest Metrics (Latency Percentiles)

### Proper TDigest Percentile Analysis
```opal
# Service latency P95 analysis using TDigest
align 5m, duration_combined: tdigest_combine(m_tdigest("span_sn_service_node_duration_tdigest_5m"))
| make_col duration_p95_ns: tdigest_quantile(duration_combined, 0.95)
| make_col duration_p95_ms: duration_p95_ns / 1000000
| aggregate avg_p95_ms: avg(duration_p95_ms), group_by(service_name)
| sort desc(avg_p95_ms) | limit 10
```

### Multiple Percentiles
```opal
# Multiple latency percentiles
align 5m, duration_combined: tdigest_combine(m_tdigest("span_sn_service_node_duration_tdigest_5m"))
| make_col p50_ns: tdigest_quantile(duration_combined, 0.50)
| make_col p95_ns: tdigest_quantile(duration_combined, 0.95)
| make_col p99_ns: tdigest_quantile(duration_combined, 0.99)
| make_col p50_ms: p50_ns / 1000000
| make_col p95_ms: p95_ns / 1000000
| make_col p99_ms: p99_ns / 1000000
| aggregate avg_p50: avg(p50_ms), avg_p95: avg(p95_ms), avg_p99: avg(p99_ms),
  group_by(service_name)
```

## 6. Histogram Metrics (Bucket Analysis)

### Histogram Data Exploration
```opal
# Explore histogram bucket structure
filter metric = "duration_milliseconds_bucket"
| statsby count: count(), group_by(string(labels.le), string(labels.service_name))
| sort desc(count) | limit 20
```

### Service Performance from Histograms
```opal
# Analyze histogram buckets for latency distribution
filter metric = "duration_milliseconds_bucket"
| filter string(labels.service_name) = "frontend"
| statsby bucket_count: sum(value), group_by(string(labels.le), string(labels.span_name))
| sort asc(string(labels.le))
```

## 7. Time-Series Analysis Patterns

### Time-Aligned Aggregation
```opal
# Proper time-aligned analysis for dashboards
align 5m, cpu_utilization: avg(m("system_cpu_utilization_ratio"))
| aggregate avg_cpu: avg(cpu_utilization), group_by(service_name)
| sort desc(avg_cpu)
```

### Rate of Change Analysis
```opal
# Rate of change for counters over time
align 5m, call_rate: rate(m("calls_total"))
| aggregate avg_call_rate: avg(call_rate), group_by(string(labels.service_name))
| sort desc(avg_call_rate)
```

## 8. Common Use Cases

### Service Health Dashboard
```opal
# Multi-metric service health overview
filter metric = "system_cpu_utilization_ratio" or metric = "system_memory_utilization_ratio"
| statsby avg_utilization: avg(value),
  group_by(metric, string(labels.service_name), string(labels.k8s_pod_name))
| sort desc(avg_utilization)
```

### Resource Capacity Planning
```opal
# Memory capacity analysis across pods
filter metric = "k8s_pod_memory_usage_bytes"
| statsby max_memory_gb: max(value) / 1073741824,
  group_by(string(labels.k8s_pod_name), string(labels.k8s_node_name))
| sort desc(max_memory_gb) | limit 20
```

### Error Rate Monitoring
```opal
# Application error tracking
filter metric = "calls_total"
| filter string(labels.status_code) = "STATUS_CODE_ERROR"
| align 5m, error_calls: sum(m("calls_total"))
| aggregate total_errors: sum(error_calls), group_by(string(labels.service_name))
| sort desc(total_errors)
```

## 9. Performance Optimization

### Query Performance Tips
1. **Use specific metric names** rather than broad filters
2. **Apply filters early** in the pipeline
3. **Limit results** appropriately to avoid large datasets
4. **Use align → aggregate** for time-series analysis
5. **Group by essential dimensions only**

### Example Optimized Query
```opal
# Optimized: Filter first, then aggregate
filter metric = "system_cpu_utilization_ratio"
| filter string(labels.service_name) in ("frontend", "recommendationservice")
| statsby avg_cpu: avg(value), group_by(string(labels.service_name))
| sort desc(avg_cpu)
```

## 10. Data Units and Conversions

### Memory Conversions
```opal
# Convert bytes to GB
filter metric = "k8s_pod_memory_usage_bytes"
| make_col memory_gb: value / 1073741824
| statsby avg_memory_gb: avg(memory_gb), group_by(string(labels.k8s_pod_name))
```

### Duration Conversions
```opal
# TDigest values are in nanoseconds, convert to milliseconds
align 5m, duration_combined: tdigest_combine(m_tdigest("span_sn_service_node_duration_tdigest_5m"))
| make_col duration_p95_ns: tdigest_quantile(duration_combined, 0.95)
| make_col duration_p95_ms: duration_p95_ns / 1000000  # ns to ms
```

## 11. Advanced Patterns

### Correlation Analysis
```opal
# Correlate CPU and memory utilization
filter metric = "system_cpu_utilization_ratio" or metric = "system_memory_utilization_ratio"
| make_col resource_type: if(metric = "system_cpu_utilization_ratio", "CPU", "Memory")
| statsby avg_utilization: avg(value),
  group_by(resource_type, string(labels.service_name))
```

### Anomaly Detection
```opal
# Find services with unusually high resource usage
filter metric = "system_memory_utilization_ratio"
| statsby avg_memory: avg(value), max_memory: max(value),
  group_by(string(labels.service_name))
| filter max_memory > 0.8  # Flag >80% memory usage
| sort desc(max_memory)
```

## Dataset Reference

### Available Datasets
- **Kubernetes Explorer/Prometheus Metrics** (`42161691`): Counter, gauge, and histogram metrics
- **ServiceExplorer/Service Inspector Metrics** (`42161008`): TDigest latency metrics

### Common Metric Types
- **Counters**: `calls_total`, `app_recommendations_counter_total`, `kafka_request_count_total`
- **Gauges**: `system_cpu_utilization_ratio`, `system_memory_utilization_ratio`, `k8s_pod_memory_usage_bytes`
- **Histograms**: `duration_milliseconds_bucket`, `jaeger_latency_bucket`
- **TDigest**: `span_sn_service_node_duration_tdigest_5m`, `span_sn_service_edge_duration_tdigest_5m`

---

All patterns in this guide have been tested against live Observe datasets and are confirmed working as of September 2025.
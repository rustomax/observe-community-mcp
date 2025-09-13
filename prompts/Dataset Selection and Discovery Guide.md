# Dataset Selection and Discovery Guide

This guide helps LLMs select the correct datasets and understand their schemas to generate successful OPAL queries, reducing failures from incorrect dataset usage.

## Table of Contents

1. [Dataset Classification](#dataset-classification)
2. [Common Dataset Types](#common-dataset-types)
3. [Field Discovery Patterns](#field-discovery-patterns)
4. [Dataset Selection Logic](#dataset-selection-logic)
5. [Schema Exploration Queries](#schema-exploration-queries)
6. [Data Quality Validation](#data-quality-validation)

---

## Dataset Classification

### By Data Source Type
```
ServiceExplorer/* - Pre-aggregated service metrics (FASTEST)
├── Service Metrics - Span duration, error counts, throughput
├── Service Inspector Metrics - Service-to-service metrics
└── Database Metrics - Database operation metrics

OpenTelemetry/* - Raw telemetry data (DETAILED)
├── Span - Individual request traces
├── Logs - Application logs
└── Metrics - Raw metric data points

Kubernetes Explorer/* - Container orchestration data
├── Kubernetes Logs - Container logs
├── OpenTelemetry Logs - OTel logs from K8s
└── Prometheus Metrics - Container/node metrics

Raw Event Streams - Original ingested data (MOST FLEXIBLE)
├── Application logs
├── Infrastructure metrics
└── Custom telemetry
```

### By Query Performance
```
🚀 FASTEST: ServiceExplorer (pre-aggregated, accelerated)
⚡ FAST: Kubernetes Explorer/Prometheus Metrics
🔄 MEDIUM: OpenTelemetry/Span (indexed)
🐌 SLOW: Raw event streams (full scan)
```

---

## Common Dataset Types

### ServiceExplorer/Service Metrics (ID: 42160988)
**Best for**: Service performance analysis, SLA monitoring, dashboard metrics

**Key Fields**:
```
service_name (string) - Service identifier
span_name (string) - Operation name
environment (string) - Deployment environment
status_code (int64) - HTTP/gRPC status codes
k8s_cluster_uid, k8s_namespace_name, k8s_pod_name - Kubernetes context
```

**Available Metrics**:
```
span_duration_5m (tdigest) - Request latencies
span_error_count_5m (gauge) - Error counts
span_call_count_5m (gauge) - Request counts
span_database_duration_5m (tdigest) - Database operation latencies
```

**Typical Query Pattern**:
```opal
align 5m, duration_combined: tdigest_combine(m_tdigest("span_duration_5m"))
| make_col p95_ms: tdigest_quantile(duration_combined, 0.95) / 1000000
| aggregate avg_p95: avg(p95_ms), group_by(service_name)
```

### OpenTelemetry/Span (ID: 42160967)
**Best for**: Request tracing, detailed error analysis, custom attribute investigation

**Key Fields**:
```
service_name (string) - Service identifier
span_name (string) - Operation name
duration (int64) - Span duration in nanoseconds
error (bool) - Error indicator
status_code (int64) - Response status
attributes (object) - Custom span attributes
resource_attributes (object) - Resource metadata
```

**Typical Query Pattern**:
```opal
filter service_name = "frontend" and error = true
| statsby
    error_count: count(),
    avg_duration_ms: avg(duration) / 1000000,
    group_by(service_name, span_name)
```

### Kubernetes Explorer/Kubernetes Logs (ID: 42161740)
**Best for**: Container log analysis, error investigation, troubleshooting

**Key Fields**:
```
cluster (string) - K8s cluster name
namespace (string) - K8s namespace
container (string) - Container name
pod (string) - Pod name
node (string) - Node name
body (string) - Log message content
stream (string) - stdout/stderr
```

**Typical Query Pattern**:
```opal
filter contains(body, "ERROR") or contains(body, "error")
| statsby
    error_count: count(),
    sample_message: any(body),
    group_by(cluster, namespace, container)
```

### Kubernetes Explorer/Prometheus Metrics (ID: 42161691)
**Best for**: Container metrics, resource utilization, K8s cluster monitoring

**Key Fields**:
```
metric (string) - Metric name
value (float64) - Metric value
labels (object) - Metric labels containing:
  ├── k8s_cluster_name
  ├── k8s_namespace_name
  ├── k8s_pod_name
  ├── container_id
  └── [metric-specific labels]
```

**Common Metrics**:
```
container_cpu_usage - CPU utilization
container_memory_usage_bytes - Memory usage
k8s_container_restarts - Container restart count
k8s_container_ready - Container readiness status
```

**Typical Query Pattern**:
```opal
filter metric = "container_cpu_usage"
| make_col cluster: string(labels.k8s_cluster_name)
| make_col pod: string(labels.k8s_pod_name)
| statsby avg_cpu: avg(value), group_by(cluster, pod)
```

---

## Field Discovery Patterns

### Schema Exploration Query
```opal
// Discover available fields in any dataset
limit 1
| pick_col *
```

### Label Field Discovery (for Metrics)
```opal
// Discover available labels in metrics datasets
filter metric = "your_metric_name"
| limit 5
| make_col label_keys: object_keys(labels)
```

### Metric Name Discovery
```opal
// Find available metrics in a metrics dataset
statsby metric_count: count(), group_by(metric)
| sort desc(metric_count)
| limit 20
```

### Service Discovery
```opal
// Find available services
statsby
  span_count: count(),
  operations: count_distinct(span_name),
  group_by(service_name)
| sort desc(span_count)
```

### Field Value Sampling
```opal
// Sample values for a specific field
statsby
  sample_count: count(),
  sample_values: string_agg(field_name, ", "),
  group_by()
| limit 1
```

---

## Dataset Selection Logic

### Use Case → Dataset Mapping

#### Service Performance Analysis
```
Goal: Analyze service latency, throughput, error rates
Primary: ServiceExplorer/Service Metrics (fast, pre-aggregated)
Secondary: OpenTelemetry/Span (detailed, custom attributes)
```

#### Error Investigation
```
Goal: Find specific error messages and root causes
Primary: Kubernetes Explorer/Kubernetes Logs (error messages)
Secondary: OpenTelemetry/Span (error context)
Tertiary: ServiceExplorer/Service Metrics (error frequency)
```

#### Infrastructure Monitoring
```
Goal: Monitor container/node resource usage
Primary: Kubernetes Explorer/Prometheus Metrics
Secondary: Raw infrastructure metrics
```

#### Custom Attribute Analysis
```
Goal: Query custom span attributes or labels
Primary: OpenTelemetry/Span (rich attributes)
Secondary: Raw event streams (full flexibility)
```

#### Historical Trending
```
Goal: Long-term performance trends and comparisons
Primary: ServiceExplorer (accelerated, efficient)
Secondary: Aggregated custom datasets
```

### Decision Tree for Dataset Selection
```
1. Is this about service performance metrics?
   → YES: Use ServiceExplorer/Service Metrics
   → NO: Continue to #2

2. Do you need specific error messages or log content?
   → YES: Use Kubernetes Explorer/Kubernetes Logs or OpenTelemetry/Logs
   → NO: Continue to #3

3. Do you need container/infrastructure metrics?
   → YES: Use Kubernetes Explorer/Prometheus Metrics
   → NO: Continue to #4

4. Do you need detailed span attributes or custom fields?
   → YES: Use OpenTelemetry/Span
   → NO: Continue to #5

5. Do you need raw, unprocessed data?
   → YES: Use appropriate raw event stream
   → NO: Start with ServiceExplorer and refine
```

---

## Schema Exploration Queries

### Complete Field Inventory
```opal
// Get comprehensive field list with types
limit 1
| make_col field_inventory: object_keys(@)
```

### Sample Data with Types
```opal
// Get sample data to understand field contents
limit 3
| pick_col timestamp, service_name, span_name, duration, error, attributes
```

### Nested Object Exploration
```opal
// Explore nested object structure (like attributes or labels)
limit 5
| make_col attribute_keys: object_keys(attributes)
| make_col label_keys: object_keys(labels)
```

### Value Distribution Analysis
```opal
// Understand value distributions for key fields
statsby
  unique_services: count_distinct(service_name),
  unique_operations: count_distinct(span_name),
  total_records: count(),
  date_range_start: min(timestamp),
  date_range_end: max(timestamp),
  group_by()
```

### Data Quality Assessment
```opal
// Check data completeness for ServiceExplorer
statsby
  total_records: count(),
  null_service_names: sum(if(is_null(service_name), 1, 0)),
  null_span_names: sum(if(is_null(span_name), 1, 0)),
  group_by()
| make_col service_name_completeness: ((total_records - null_service_names) / total_records) * 100
| make_col span_name_completeness: ((total_records - null_span_names) / total_records) * 100
```

---

## Data Quality Validation

### Field Existence Validation
```opal
// Validate required fields exist before complex queries
statsby
  has_service_name: sum(if(not is_null(service_name), 1, 0)),
  has_span_name: sum(if(not is_null(span_name), 1, 0)),
  total_records: count(),
  group_by()
| make_col service_field_coverage: (has_service_name / total_records) * 100
| make_col span_field_coverage: (has_span_name / total_records) * 100
| filter service_field_coverage > 90 and span_field_coverage > 90
```

### Time Range Validation
```opal
// Ensure sufficient data in time range
statsby
  record_count: count(),
  time_span_hours: (max(time) - min(time)) / 3600000000000,
  first_record: min(time),
  last_record: max(time),
  group_by()
| filter record_count >= 100  // Minimum records threshold
```

### Service Coverage Validation
```opal
// Validate service coverage for multi-service analysis
statsby
  service_count: count_distinct(service_name),
  total_services_expected: 10,  // Your expected service count
  group_by()
| make_col coverage_pct: (service_count / total_services_expected) * 100
| filter coverage_pct >= 80  // 80% service coverage threshold
```

---

## Common Field Name Variations

### Service Identification
```
ServiceExplorer: service_name
OpenTelemetry: service_name
Kubernetes: May be in labels.app or metadata
Prometheus: Usually in labels.service or labels.job
```

### Time Fields
```
Standard: timestamp
Metrics: time
Kubernetes: Usually timestamp
Custom: May be @timestamp, eventTime, etc.
```

### Error Indicators
```
OpenTelemetry Span: error (boolean)
ServiceExplorer: status_code >= 400
Kubernetes Logs: Look for "ERROR", "error", "FATAL" in body
HTTP Metrics: Usually status_code or response_code
```

### Duration Fields
```
OpenTelemetry Span: duration (nanoseconds)
ServiceExplorer: span_duration_5m (tdigest)
HTTP Metrics: response_time, latency, duration (various units)
Database: query_duration, execution_time
```

---

## Dataset Recommendation Patterns

### For Performance Questions
```
"How fast is my service?" → ServiceExplorer/Service Metrics
"What's the P95 latency?" → ServiceExplorer/Service Metrics
"Show me slow requests" → OpenTelemetry/Span (with duration filter)
```

### For Error Analysis
```
"What errors am I seeing?" → Kubernetes Explorer/Kubernetes Logs
"Which services have errors?" → ServiceExplorer/Service Metrics (error_count)
"Show me error details" → OpenTelemetry/Span (error = true)
```

### For Infrastructure Questions
```
"CPU usage by container" → Kubernetes Explorer/Prometheus Metrics
"Memory consumption" → Kubernetes Explorer/Prometheus Metrics
"Container restart counts" → Kubernetes Explorer/Prometheus Metrics
```

### For Troubleshooting
```
"Debug a specific request" → OpenTelemetry/Span (trace analysis)
"Application logs" → Kubernetes Explorer/Kubernetes Logs
"Service dependencies" → Multiple datasets with joins
```

---

## Best Practices for Dataset Selection

### Start Simple, Then Drill Down
1. **Begin with ServiceExplorer** for service-level metrics
2. **Move to OpenTelemetry/Span** for detailed analysis
3. **Use Kubernetes logs** for error messages
4. **Combine datasets** only when necessary

### Performance Considerations
1. **ServiceExplorer is fastest** - use for dashboards and alerts
2. **Limit time ranges** for raw data queries
3. **Use filters early** to reduce data volume
4. **Consider data acceleration** for frequently accessed patterns

### Data Freshness
1. **ServiceExplorer** - 5-minute freshness
2. **OpenTelemetry** - Near real-time
3. **Kubernetes** - 1-2 minute freshness
4. **Raw streams** - Real-time but may need processing

This guide should significantly reduce dataset selection errors and improve query success rates by providing clear decision paths and validation patterns.
# Common Log Search Patterns for Observe

This guide provides practical OPAL query patterns for log analysis using Observe's log datasets. All queries have been tested against live data and demonstrate real-world log search scenarios.

> **Note**: Dataset names shown here are examples. Your environment may have different dataset names, but the OPAL patterns remain the same.

## Available Log Datasets

Based on discovery analysis, common log datasets include:
- **Kubernetes Explorer/OpenTelemetry Logs** - Application and infrastructure logs from OpenTelemetry sources
- **Kubernetes Explorer/Kubernetes Logs** - Native Kubernetes container and pod logs

## Core Log Search Syntax

### Basic Text Search

```opal
# Simple keyword search in log body
filter body ~ error

# Case-insensitive search for multiple terms (order doesn't matter)
filter body ~ <error message>

# Exact phrase search (order matters)
filter body ~ "error message"
```

### Wildcard and Pattern Matching

```opal
# Substring search - matches words containing "error"
filter body ~ *error*

# Prefix search - matches words starting with "error"
filter body ~ error*

# Suffix search - matches words ending with "error"
filter body ~ *error

# Search across all fields (slower but comprehensive)
filter * ~ error
```

## Common Log Analysis Patterns

### 1. Error Investigation

```opal
# Find recent errors across all log fields
filter body ~ error
| limit 50

# Search for specific error patterns
filter body ~ <timeout connection failed>

# Find errors by severity level
filter body ~ "level=error"

# Multiple error keywords
filter body ~ <error exception failure>
```

**Real Example Result:**
```
2025-09-14T02:50:23.494Z Error translating OTLP metrics to Prometheus write request
2025-09-14 02:47:58.092 Watch error received from Upstream error=too old resource version
```

### 2. Kubernetes-Specific Log Patterns

```opal
# Extract Kubernetes metadata for context
make_col
    namespace:resource_attributes.k8s.namespace.name,
    pod:resource_attributes.k8s.pod.name,
    container:resource_attributes.k8s.container.name
| filter body ~ error

# Filter by specific namespace
make_col namespace:resource_attributes.k8s.namespace.name
| filter namespace = "kube-system"
| filter body ~ <error warn>

# Find pod restart issues
filter resource_attributes.k8s.container.restart_count != "0"
| make_col
    pod:resource_attributes.k8s.pod.name,
    restarts:resource_attributes.k8s.container.restart_count
```

### 3. Application Log Patterns

```opal
# Search for HTTP errors
filter body ~ <http status 500 404 error>

# Database connection issues
filter body ~ <database connection timeout>

# Memory/resource issues
filter body ~ <memory oom killed>

# Authentication problems
filter body ~ <auth login failed unauthorized>
```

### 4. Time-Based Analysis

```opal
# Recent errors in last hour
filter body ~ error
| filter timestamp > @"1 hour ago"

# Group errors by time intervals
filter body ~ error
| statsby count:count(), group_by(bin(timestamp, 5m))
| sort asc(timestamp)

# Find error spikes
filter body ~ <error exception>
| statsby error_count:count(), group_by(bin(timestamp, 1m))
| filter error_count > 10
```

### 5. Service and Component Filtering

```opal
# Filter by log source/stream
filter stream = "stderr"
| filter body ~ error

# Container-specific logs
make_col container:resource_attributes.k8s.container.name
| filter container ~ "prometheus"
| filter body ~ error

# Node-specific analysis
make_col node:resource_attributes.k8s.node.name
| filter node = "observe-demo-eu01"
| filter body ~ <error warn>
```

## Advanced Search Patterns

### 6. Multi-Field Search with Context

```opal
# Search with rich context extraction
make_col
    timestamp_clean:parsedate(body, "2006-01-02T15:04:05.999Z"),
    level:extract_regex(body, /level=(\w+)/),
    message:extract_regex(body, /msg="([^"]+)"/),
    namespace:resource_attributes.k8s.namespace.name,
    pod:resource_attributes.k8s.pod.name
| filter body ~ error
| sort desc(timestamp)
```

### 7. Log Correlation Patterns

```opal
# Find logs from the same pod within time window
make_col pod:resource_attributes.k8s.pod.name
| filter pod ~ "prometheus-server"
| filter timestamp > @"30 minutes ago"
| sort desc(timestamp)

# Correlate errors with specific request IDs
filter body ~ "request_id"
| make_col request_id:extract_regex(body, /request_id=([a-f0-9]+)/)
| filter not is_null(request_id)
```

### 8. Statistical Analysis

```opal
# Error frequency by container
make_col container:resource_attributes.k8s.container.name
| filter body ~ error
| statsby
    error_count:count(),
    first_seen:min(timestamp),
    last_seen:max(timestamp),
    group_by(container)
| sort desc(error_count)

# Top error messages
filter body ~ error
| make_col error_msg:extract_regex(body, /"([^"]*error[^"]*)"/)
| statsby count:count(), group_by(error_msg)
| sort desc(count)
| limit 10
```

## Performance Optimization Tips

### Efficient Query Construction

```opal
# ✅ Good: Specific field search
filter body ~ error

# ❌ Avoid: Global search (slower)
filter * ~ error

# ✅ Good: Combined filters
filter body ~ error
| filter resource_attributes.k8s.namespace.name = "production"

# ✅ Good: Early filtering with limits
filter body ~ <critical error>
| limit 100
| make_col detailed_analysis:extract_regex(body, /complex_pattern/)
```

### Time Window Best Practices

```opal
# Use appropriate time windows
filter body ~ error
| filter timestamp > @"1 hour ago"  # Recent issues

# For historical analysis
filter body ~ error
| filter timestamp between(@"2024-01-01", @"2024-01-02")
```

## Real-World Troubleshooting Workflows

### Incident Investigation

```opal
# Step 1: Find the error
filter body ~ <service unavailable 503>
| limit 20

# Step 2: Get context around the time
make_col
    pod:resource_attributes.k8s.pod.name,
    namespace:resource_attributes.k8s.namespace.name
| filter timestamp between(@"2024-01-15 10:30:00", @"2024-01-15 10:35:00")
| sort asc(timestamp)

# Step 3: Correlate with other components
make_col service:extract_regex(body, /service[=:](\w+)/)
| filter not is_null(service)
| statsby count:count(), group_by(service)
```

### Performance Debugging

```opal
# Find slow operations
filter body ~ <slow timeout duration>
| make_col duration:extract_regex(body, /duration[=:]([0-9.]+)/)
| filter float64(duration) > 5.0
| sort desc(duration)

# Memory issues
filter body ~ <memory heap gc>
| statsby count:count(), group_by(bin(timestamp, 5m))
| sort desc(timestamp)
```

## Common Field Patterns

Based on tested queries, common log field structures include:

- **body**: Main log content (search target)
- **timestamp**: Log timestamp
- **stream**: stdout/stderr
- **resource_attributes.k8s.namespace.name**: Kubernetes namespace
- **resource_attributes.k8s.pod.name**: Pod name
- **resource_attributes.k8s.container.name**: Container name
- **resource_attributes.k8s.node.name**: Node name

## Query Testing Checklist

When building log searches:

1. ✅ Start with simple keyword searches
2. ✅ Add field extraction for context
3. ✅ Use appropriate time windows
4. ✅ Limit results for large datasets
5. ✅ Test with different search syntaxes
6. ✅ Validate extracted fields aren't null
7. ✅ Sort results appropriately

---

*This guide is generated using live data from Observe log datasets. Patterns are tested and validated against real log entries.*
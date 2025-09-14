# Gauge Metric Query Patterns

## Current Value
```opal
filter metric = "container_memory_usage_bytes"
| statsby current_memory: max(value), group_by(string(labels.k8s_pod_name))
| sort desc(current_memory)
```

## Average Over Time
```opal
filter metric = "container_memory_usage_bytes"
| statsby avg_memory: avg(value), group_by(string(labels.k8s_pod_name))
| sort desc(avg_memory)
```

## Time Series Gauge
```opal
filter metric = "container_memory_usage_bytes"
| align 5m, avg_memory_usage: avg(m("container_memory_usage_bytes"))
| sort asc(valid_from)
| limit 10
```

## Threshold Alerts
```opal
filter metric = "container_memory_usage_bytes"
| filter value > 100000000
| sort desc(value)
| limit 10
```
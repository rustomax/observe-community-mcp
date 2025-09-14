# Trace Dataset Query Patterns

## Basic Span Search
```opal
filter span_name ~ "GET"
| limit 10
```

## Service Performance Analysis
```opal
statsby avg_duration: avg(duration), group_by(service_name)
| sort desc(avg_duration)
```

## Error Spans
```opal
filter status_code != "OK"
| limit 10
```

## Trace by Service
```opal
filter service_name = "checkoutservice"
| sort desc(start_time)
| limit 10
```
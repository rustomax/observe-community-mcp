# Resource Dataset Query Patterns

## Basic Resource Listing
```opal
topk 10
```

## Filter by Service Name
```opal
filter service_name = "cartservice"
```

## Service Namespace Filter
```opal
filter service_namespace = "opentelemetry-demo"
```

## Parent Service Analysis
```opal
filter not is_null(parent_service_name)
| topk 10
```
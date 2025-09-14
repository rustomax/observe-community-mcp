# Field Not Found Error Patterns

## Check Dataset Schema First
```opal
# Use this to explore available fields
sort desc(timestamp) | limit 5
```

## Common Log Fields
```opal
# Try these common log field patterns:
make_col log_level: string(LogAttributes.level)
make_col container: string(resource_attributes."k8s.container.name")
make_col namespace: string(resource_attributes."k8s.namespace.name")
make_col pod: string(resource_attributes."k8s.pod.name")
```

## Common Metric Dimensions
```opal
# Metrics typically use labels for dimensions:
filter metric = "cpu_usage"
| statsby avg_cpu: avg(value), group_by(string(labels.instance))
```

## Nested Field Access
```opal
# For deeply nested fields, use dot notation with quotes:
make_col service: string(attributes."service.name")
make_col version: string(attributes."service.version")
```
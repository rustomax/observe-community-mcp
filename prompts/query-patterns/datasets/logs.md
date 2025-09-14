# Log Dataset Query Patterns

## Basic Error Search
```opal
filter body ~ error
| limit 10
```

## JSON Field Access
```opal
make_col namespace: string(resource_attributes."k8s.namespace.name")
| filter not is_null(namespace)
| limit 10
```

## Error Count by Container
```opal
filter body ~ error
| make_col container: string(resource_attributes."k8s.container.name")
| statsby error_count: count(), group_by(container)
| sort desc(error_count)
```

## Multiple Keyword Search
```opal
filter (body ~ "error" OR body ~ "exception" OR body ~ "failure")
| limit 10
```
# Common OPAL Syntax Error Fixes

## Use ~ for Text Search (not LIKE)
**Wrong:**
```opal
filter body like "%error%"
```
**Correct:**
```opal
filter body ~ error
```

## Use string() for JSON Field Access
**Wrong:**
```opal
filter resource_attributes.k8s.namespace.name = "default"
```
**Correct:**
```opal
make_col namespace: string(resource_attributes."k8s.namespace.name")
| filter namespace = "default"
```

## Use make_col for New Columns (not =)
**Wrong:**
```opal
namespace = string(resource_attributes."k8s.namespace.name")
```
**Correct:**
```opal
make_col namespace: string(resource_attributes."k8s.namespace.name")
```

## Use sort desc() Function
**Wrong:**
```opal
sort -timestamp
```
**Correct:**
```opal
sort desc(timestamp)
```
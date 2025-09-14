# Counter Metric Query Patterns

## Basic Counter Query
```opal
filter metric = "rpc_server_requests_per_rpc_count"
| statsby total_requests: sum(value), group_by(string(labels.job))
| sort desc(total_requests)
```

## Rate Calculation
```opal
filter metric = "rpc_server_requests_per_rpc_count"
| align 1m, request_rate: rate(m("rpc_server_requests_per_rpc_count"))
| sort desc(request_rate)
| limit 10
```

## Counter by Status Code
```opal
filter metric = "rpc_server_requests_per_rpc_count"
| statsby requests: sum(value), group_by(string(labels.job), string(labels.rpc_grpc_status_code))
| sort desc(requests)
```

## Time Series Counter
```opal
filter metric = "rpc_server_requests_per_rpc_count"
| align 1m, requests_per_minute: sum(m("rpc_server_requests_per_rpc_count"))
| sort asc(valid_from)
| limit 10
```
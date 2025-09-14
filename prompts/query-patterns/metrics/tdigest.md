# TDigest Metric Query Patterns

## Percentile Analysis
```opal
align 5m, duration_combined: tdigest_combine(m_tdigest("response_time_tdigest"))
| make_col duration_p95: tdigest_quantile(duration_combined, 0.95)
| make_col duration_p99: tdigest_quantile(duration_combined, 0.99)
| aggregate avg_p95: avg(duration_p95), avg_p99: avg(duration_p99), group_by(service_name)
```

## Latency Distribution
```opal
align 1m, latency_combined: tdigest_combine(m_tdigest("request_duration_tdigest"))
| make_col p50: tdigest_quantile(latency_combined, 0.50)
| make_col p95: tdigest_quantile(latency_combined, 0.95)
| make_col p99: tdigest_quantile(latency_combined, 0.99)
```

## Unit Conversion (ns to ms)
```opal
align 5m, duration_combined: tdigest_combine(m_tdigest("span_duration_tdigest"))
| make_col duration_p95_ns: tdigest_quantile(duration_combined, 0.95)
| make_col duration_p95_ms: duration_p95_ns / 1000000
```
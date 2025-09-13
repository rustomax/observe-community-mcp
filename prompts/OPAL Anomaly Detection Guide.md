# OPAL Anomaly Detection Guide for Microservices

This guide provides comprehensive patterns and examples for implementing anomaly detection monitors in Observe using OPAL, with special focus on microservice latency monitoring.

## Table of Contents

1. [Basic Anomaly Detection Patterns](#basic-anomaly-detection-patterns)
2. [Enhanced Patterns with Timeshift](#enhanced-patterns-with-timeshift)
3. [Advanced Subquery Patterns](#advanced-subquery-patterns)
4. [Implementation Guidelines](#implementation-guidelines)
5. [Monitor Configuration Examples](#monitor-configuration-examples)
6. [Troubleshooting and Best Practices](#troubleshooting-and-best-practices)

---

## Basic Anomaly Detection Patterns

### 1. Statistical Z-Score Anomaly Detection
**Best for: Detecting statistical outliers in service latency**

```opal
align 5m, duration_combined: tdigest_combine(m_tdigest("span_duration_5m"))
| make_col p95_ms: tdigest_quantile(duration_combined, 0.95) / 1000000
| filter service_name = "your-service-name"
| make_event
| make_col running_avg: window(avg(p95_ms), frame(back:2h))
| make_col running_stddev: window(stddev(p95_ms), frame(back:2h))
| make_col z_score: abs(p95_ms - running_avg) / running_stddev
| make_col is_outlier: z_score > 2.5
| make_col alert_message: concat_strings("Latency anomaly detected for ", service_name, " - P95: ", string(round(p95_ms, 2)), "ms (", string(round(z_score, 2)), " std devs)")
| filter is_outlier = true
```

**Key Parameters:**
- `frame(back:2h)`: Historical window size
- `z_score > 2.5`: Sensitivity threshold (2.0 = more sensitive, 3.0 = less sensitive)
- Time range: Use 6h+ for sufficient historical data

**Monitor Configuration:**
- **Alert condition**: `is_outlier = true`
- **Notification**: Include `alert_message` for context

### 2. Percentile-Based Anomaly Detection
**Best for: Detecting when latency exceeds historical norms**

```opal
align 5m, duration_combined: tdigest_combine(m_tdigest("span_duration_5m"))
| make_col p95_ms: tdigest_quantile(duration_combined, 0.95) / 1000000
| make_event
| make_col historical_p95: window(percentile(p95_ms, 0.95), frame(back:24h))
| make_col is_anomaly: p95_ms > historical_p95 * 2
| make_col severity: if(p95_ms > historical_p95 * 3, "Critical", if(p95_ms > historical_p95 * 2, "Warning", "Normal"))
| filter is_anomaly = true
| statsby
    anomaly_count: count(),
    max_latency: max(p95_ms),
    avg_latency: avg(p95_ms),
    group_by(service_name, severity)
```

**Key Parameters:**
- `historical_p95 * 2`: Warning threshold (2x historical P95)
- `historical_p95 * 3`: Critical threshold (3x historical P95)
- `frame(back:24h)`: 24-hour baseline window

### 3. Multi-Service Latency Drift Detection
**Best for: Detecting when multiple services show latency issues simultaneously**

```opal
align 5m, duration_combined: tdigest_combine(m_tdigest("span_duration_5m"))
| make_col p95_ms: tdigest_quantile(duration_combined, 0.95) / 1000000
| make_event
| make_col running_avg: window(avg(p95_ms), frame(back:1h))
| make_col drift_ratio: p95_ms / running_avg
| make_col is_drift: drift_ratio > 1.8
| filter is_drift = true
| statsby
    affected_services: count_distinct(service_name),
    max_drift: max(drift_ratio),
    avg_drift: avg(drift_ratio),
    group_by()
| make_col is_widespread_issue: affected_services >= 3
| make_col alert_message: concat_strings("Infrastructure Alert: ", string(affected_services), " services showing high latency (avg ", string(round(avg_drift, 2)), "x normal)")
| filter is_widespread_issue = true
```

**Use Case:** Detect infrastructure-wide latency issues affecting multiple services
**Key Change:** Uses `count_distinct(service_name)` and higher threshold (1.8x) to reduce noise

### 4. EWMA (Exponentially Weighted Moving Average) Detection
**Best for: Real-time anomaly detection with adaptive baselines**

```opal
align 5m, duration_combined: tdigest_combine(m_tdigest("span_duration_5m"))
| make_col p95_ms: tdigest_quantile(duration_combined, 0.95) / 1000000
| filter service_name = "critical-service"
| make_event
| make_col ewma_baseline: window(ewma(p95_ms, 12), frame(back:2h))
| make_col deviation_pct: ((p95_ms - ewma_baseline) / ewma_baseline) * 100
| make_col is_anomaly: abs(deviation_pct) > 50
| make_col alert_level: if(abs(deviation_pct) > 100, "Critical", if(abs(deviation_pct) > 50, "Warning", "Normal"))
| filter is_anomaly = true
```

**Key Parameters:**
- `ewma(p95_ms, 12)`: 12-period EWMA (1 hour with 5-minute alignment)
- `deviation_pct > 50`: 50% deviation threshold

---

## Enhanced Patterns with Timeshift

### 5. Multi-Timeframe Trend Analysis
**Best for: Distinguishing between recent spikes vs. sustained performance degradation**

```opal
make_col time_period: "current"
@one_hour_ago <- @ {
  timeshift 1h
  make_col time_period: "1h_ago"
}
@six_hours_ago <- @ {
  timeshift 6h
  make_col time_period: "6h_ago"
}
union @one_hour_ago, @six_hours_ago
| align 5m, duration_combined: tdigest_combine(m_tdigest("span_duration_5m"))
| make_col p95_ms: tdigest_quantile(duration_combined, 0.95) / 1000000
| filter service_name = "your-service"
| statsby
    avg_p95: avg(p95_ms),
    group_by(service_name, time_period)
| make_col current_baseline: if(time_period = "current", avg_p95, 0)
| make_col one_hour_baseline: if(time_period = "1h_ago", avg_p95, 0)
| make_col six_hour_baseline: if(time_period = "6h_ago", avg_p95, 0)
| statsby
    current_latency: sum(current_baseline),
    one_hour_latency: sum(one_hour_baseline),
    six_hour_latency: sum(six_hour_baseline),
    group_by(service_name)
| filter current_latency > 0 and one_hour_latency > 0 and six_hour_latency > 0
| make_col short_term_change: ((current_latency - one_hour_latency) / one_hour_latency) * 100
| make_col long_term_change: ((current_latency - six_hour_latency) / six_hour_latency) * 100
| make_col trend_classification: if(short_term_change > 20 and long_term_change > 20, "Sustained Increase",
                                if(short_term_change > 20 and long_term_change < 5, "Recent Spike",
                                if(abs(short_term_change) < 10 and abs(long_term_change) < 10, "Stable",
                                "Variable")))
| make_col alert_message: concat_strings("Trend Alert: ", service_name, " - ", trend_classification, " (", string(round(short_term_change, 1)), "% short-term, ", string(round(long_term_change, 1)), "% long-term)")
| filter trend_classification != "Stable"
```

**Trend Classifications:**
- **Sustained Increase**: Problem getting worse over time
- **Recent Spike**: Sudden spike but historically normal
- **Variable**: Inconsistent patterns needing investigation

### 6. Day-over-Day Baseline Comparison
**Best for: Detecting when current performance significantly deviates from same time yesterday**

```opal
make_col series: "current"
@yesterday <- @ {
  timeshift 24h
  make_col series: "yesterday"
}
union @yesterday
| align 5m, duration_combined: tdigest_combine(m_tdigest("span_duration_5m"))
| make_col p95_ms: tdigest_quantile(duration_combined, 0.95) / 1000000
| filter service_name = "your-service"
| statsby
    current_p95: avg(if(series = "current", p95_ms, 0)),
    yesterday_p95: avg(if(series = "yesterday", p95_ms, 0)),
    current_count: sum(if(series = "current", 1, 0)),
    yesterday_count: sum(if(series = "yesterday", 1, 0)),
    group_by(service_name)
| filter current_count > 0 and yesterday_count > 0
| make_col latency_change_pct: ((current_p95 - yesterday_p95) / yesterday_p95) * 100
| make_col is_anomaly: abs(latency_change_pct) > 30
| make_col severity: if(latency_change_pct > 75, "Critical Increase",
                     if(latency_change_pct > 30, "Warning Increase",
                     if(latency_change_pct < -30, "Significant Decrease", "Normal")))
| make_col alert_message: concat_strings("Day-over-Day Alert: ", service_name, " latency changed ", string(round(latency_change_pct, 1)), "% vs yesterday (", string(round(yesterday_p95, 2)), "ms → ", string(round(current_p95, 2)), "ms)")
| filter is_anomaly = true
```

**Benefits:**
- Accounts for daily traffic patterns
- Provides contextual comparison with actual values
- Effective for services with predictable daily cycles

---

## Advanced Subquery Patterns

### 7. Statistical Confidence with Subqueries
**Best for: High-confidence anomaly detection using statistical rigor**

```opal
@current_metrics <- @ {
  align 5m, duration_combined: tdigest_combine(m_tdigest("span_duration_5m"))
  make_col p95_ms: tdigest_quantile(duration_combined, 0.95) / 1000000
  statsby
      current_p95: avg(p95_ms),
      current_stddev: stddev(p95_ms),
      current_count: count(),
      group_by(service_name)
  make_col time_period: "current"
}

@historical_baseline <- @ {
  timeshift 24h
  align 5m, duration_combined: tdigest_combine(m_tdigest("span_duration_5m"))
  make_col p95_ms: tdigest_quantile(duration_combined, 0.95) / 1000000
  statsby
      baseline_p95: avg(p95_ms),
      baseline_stddev: stddev(p95_ms),
      baseline_count: count(),
      group_by(service_name)
  make_col time_period: "baseline"
}

<- @current_metrics {
  join service_name = @historical_baseline.service_name,
       baseline_p95: @historical_baseline.baseline_p95,
       baseline_stddev: @historical_baseline.baseline_stddev,
       baseline_count: @historical_baseline.baseline_count
  make_col z_score: (current_p95 - baseline_p95) / baseline_stddev
  make_col is_significant_anomaly: abs(z_score) > 2.0 and current_count >= 10 and baseline_count >= 10
  make_col anomaly_type: if(z_score > 2.0, "Performance Degradation",
                         if(z_score < -2.0, "Performance Improvement", "Normal"))
  make_col confidence: if(abs(z_score) > 3.0, "Very High",
                       if(abs(z_score) > 2.5, "High",
                       if(abs(z_score) > 2.0, "Medium", "Low")))
  make_col abs_z_score: abs(z_score)
  make_col alert_message: concat_strings("Statistical Anomaly: ", service_name, " - ", anomaly_type, " (Z-score: ", string(round(z_score, 2)), ", Confidence: ", confidence, ")")
  filter is_significant_anomaly = true
  sort desc(abs_z_score)
}
```

**Key Features:**
- **Statistical rigor**: Uses Z-scores for confidence levels
- **Data quality checks**: Requires minimum sample sizes (>=10)
- **Confidence scoring**: Very High/High/Medium confidence levels
- **Sample size validation**: Ensures statistical significance

### 8. Multi-Service Correlation Detection
**Best for: Detecting infrastructure-wide issues vs isolated service problems**

```opal
make_col series: "current"
@baseline <- @ {
  timeshift 2h
  make_col series: "baseline"
}
union @baseline
| align 5m, duration_combined: tdigest_combine(m_tdigest("span_duration_5m"))
| make_col p95_ms: tdigest_quantile(duration_combined, 0.95) / 1000000
| statsby
    current_avg: avg(if(series = "current", p95_ms, 0)),
    baseline_avg: avg(if(series = "baseline", p95_ms, 0)),
    current_samples: sum(if(series = "current", 1, 0)),
    baseline_samples: sum(if(series = "baseline", 1, 0)),
    group_by(service_name)
| filter current_samples > 0 and baseline_samples > 0
| make_col latency_increase_pct: ((current_avg - baseline_avg) / baseline_avg) * 100
| make_col is_degraded: latency_increase_pct > 25
| statsby
    total_services: count(),
    degraded_services: sum(if(is_degraded, 1, 0)),
    avg_degradation: avg(if(is_degraded, latency_increase_pct, 0)),
    worst_service: any(if(is_degraded, service_name, "")),
    group_by()
| make_col degradation_ratio: degraded_services / total_services
| make_col incident_type: if(degradation_ratio >= 0.5, "Infrastructure Issue",
                          if(degraded_services >= 3, "Multi-Service Issue",
                          if(degraded_services >= 1, "Isolated Service Issue", "Normal")))
| make_col severity: if(degradation_ratio >= 0.7, "Critical",
                     if(degradation_ratio >= 0.4, "Major",
                     if(degraded_services >= 2, "Minor", "Info")))
| make_col alert_message: concat_strings("Correlation Alert: ", incident_type, " detected - ", string(degraded_services), "/", string(total_services), " services affected (", string(round(avg_degradation, 1)), "% avg increase)")
| filter incident_type != "Normal"
```

**Incident Classifications:**
- **Infrastructure Issue**: ≥50% of services affected (likely platform/network)
- **Multi-Service Issue**: ≥3 services affected (possible shared dependency)
- **Isolated Service Issue**: Single service (application-specific)

### 9. Adaptive Threshold with Historical Windows
**Best for: Services with varying traffic patterns that need dynamic thresholds**

```opal
@short_window <- @ {
  align 5m, duration_combined: tdigest_combine(m_tdigest("span_duration_5m"))
  make_col p95_ms: tdigest_quantile(duration_combined, 0.95) / 1000000
  statsby
      recent_avg: avg(p95_ms),
      recent_stddev: stddev(p95_ms),
      group_by(service_name)
  make_col window_type: "recent"
}

@long_window <- @ {
  timeshift 4h
  align 5m, duration_combined: tdigest_combine(m_tdigest("span_duration_5m"))
  make_col p95_ms: tdigest_quantile(duration_combined, 0.95) / 1000000
  statsby
      historical_avg: avg(p95_ms),
      historical_stddev: stddev(p95_ms),
      historical_p95: percentile(p95_ms, 0.95),
      group_by(service_name)
  make_col window_type: "historical"
}

<- @short_window {
  join service_name = @long_window.service_name,
       historical_avg: @long_window.historical_avg,
       historical_stddev: @long_window.historical_stddev,
       historical_p95: @long_window.historical_p95
  make_col adaptive_upper_threshold: historical_avg + (historical_stddev * 2.5)
  make_col adaptive_critical_threshold: historical_p95 * 1.5
  make_col is_warning_anomaly: recent_avg > adaptive_upper_threshold
  make_col is_critical_anomaly: recent_avg > adaptive_critical_threshold
  make_col severity: if(is_critical_anomaly, "Critical",
                     if(is_warning_anomaly, "Warning", "Normal"))
  make_col deviation_from_normal: ((recent_avg - historical_avg) / historical_avg) * 100
  make_col alert_message: concat_strings("Adaptive Threshold Alert: ", service_name, " - ", severity, " (", string(round(recent_avg, 2)), "ms vs ", string(round(adaptive_upper_threshold, 2)), "ms threshold, ", string(round(deviation_from_normal, 1)), "% deviation)")
  filter severity != "Normal"
  sort desc(deviation_from_normal)
}
```

**Benefits:**
- **Dynamic thresholds**: Automatically adapts to service behavior patterns
- **Dual threshold system**: Warning (statistical) + Critical (percentile-based)
- **Reduces false positives**: Accounts for natural variation in service performance

---

## Implementation Guidelines

### Service Tier Recommendations

| Service Tier | Pattern Recommendations | Thresholds | Time Windows |
|-------------|------------------------|------------|--------------|
| **Tier 1 (Critical)** | Statistical Confidence + Adaptive Threshold | Z-score > 2.0, 30%+ change | 24h baseline |
| **Tier 2 (Important)** | Multi-Timeframe + Day-over-Day | Z-score > 2.5, 50%+ change | 8h windows |
| **Tier 3 (Standard)** | Percentile-Based + EWMA | Z-score > 3.0, 75%+ change | 4h windows |
| **Infrastructure** | Multi-Service Correlation | 3+ services, 25%+ degradation | 2h baseline |

### Query Time Windows and Performance

| Pattern Type | Minimum Time Range | Recommended Range | Performance Impact |
|-------------|-------------------|------------------|-------------------|
| **Basic Statistical** | 6h | 12h | Low |
| **Timeshift (24h)** | 48h | 72h | Medium |
| **Multi-timeframe** | 8h | 12h | Medium |
| **Subqueries** | 24h | 48h | High |
| **Correlation** | 4h | 8h | Medium |

### Alert Threshold Guidelines

#### Latency Thresholds by Service Type:
```
API Services: P95 > 200ms (Warning), P95 > 500ms (Critical)
Database Services: P95 > 50ms (Warning), P95 > 100ms (Critical)
Background Jobs: P95 > 5s (Warning), P95 > 15s (Critical)
Frontend Services: P95 > 1s (Warning), P95 > 3s (Critical)
```

#### Statistical Thresholds:
```
Z-score > 2.0: Medium confidence (95% certainty)
Z-score > 2.5: High confidence (99% certainty)
Z-score > 3.0: Very high confidence (99.7% certainty)
```

---

## Monitor Configuration Examples

### Example 1: Critical Service Monitor (Tier 1)
```yaml
Monitor Name: "Critical Service Latency Anomaly - Statistical"
Dataset: ServiceExplorer/Service Metrics
OPAL Query: [Pattern #7 - Statistical Confidence]
Alert Condition: is_significant_anomaly = true AND confidence IN ("High", "Very High")
Time Range: 48h
Refresh: 5m
Notifications:
  - Slack: #critical-alerts
  - Email: oncall-team@company.com
  - PagerDuty: P1 escalation
```

### Example 2: Multi-Service Infrastructure Monitor
```yaml
Monitor Name: "Multi-Service Correlation Detection"
Dataset: ServiceExplorer/Service Metrics
OPAL Query: [Pattern #8 - Multi-Service Correlation]
Alert Condition: incident_type IN ("Infrastructure Issue", "Multi-Service Issue") AND severity IN ("Critical", "Major")
Time Range: 8h
Refresh: 2m
Notifications:
  - Slack: #infrastructure-alerts
  - Email: platform-team@company.com
```

### Example 3: Standard Service Monitor (Tier 3)
```yaml
Monitor Name: "Standard Service - Day over Day Comparison"
Dataset: ServiceExplorer/Service Metrics
OPAL Query: [Pattern #6 - Day-over-Day Baseline]
Alert Condition: is_anomaly = true AND severity IN ("Warning Increase", "Critical Increase")
Time Range: 48h
Refresh: 15m
Notifications:
  - Slack: #service-alerts
  - Email: dev-team@company.com
```

---

## Troubleshooting and Best Practices

### Common Issues and Solutions

#### 1. **False Positives**
**Problem**: Too many alerts during normal traffic variations
**Solutions:**
- Increase Z-score thresholds (2.0 → 2.5 → 3.0)
- Use longer historical windows (2h → 4h → 24h)
- Add minimum sample size requirements
- Use adaptive thresholds for variable services

#### 2. **Missed Anomalies**
**Problem**: Real issues not being detected
**Solutions:**
- Decrease Z-score thresholds (3.0 → 2.5 → 2.0)
- Reduce historical window size for faster detection
- Use multiple detection methods (combine patterns)
- Check data quality and completeness

#### 3. **Query Performance Issues**
**Problem**: Monitors taking too long or timing out
**Solutions:**
- Use shorter time ranges where possible
- Avoid complex subqueries for high-frequency monitors
- Consider data acceleration for frequently queried datasets
- Use simpler patterns for less critical services

#### 4. **Data Quality Problems**
**Problem**: Inconsistent or missing metrics
**Solutions:**
- Add data validation checks (minimum sample sizes)
- Filter out null/invalid values
- Use `if_null()` functions for missing data handling
- Monitor data ingestion separately

### Best Practices

#### Monitor Design
1. **Start Conservative**: Begin with higher thresholds and adjust down
2. **Layer Detection**: Use multiple patterns for critical services
3. **Context in Alerts**: Always include current vs baseline values
4. **Test with Historical Data**: Validate against known incidents

#### Performance Optimization
1. **Use Appropriate Time Windows**: Don't query more data than needed
2. **Leverage Data Acceleration**: For frequently accessed datasets
3. **Monitor Monitor Performance**: Track query execution times
4. **Batch Similar Monitors**: Group related alerts to reduce query load

#### Alert Management
1. **Progressive Alerting**: Warning → Critical → Emergency escalation
2. **Context-Rich Messages**: Include troubleshooting information
3. **Runbook Links**: Include investigation procedures
4. **Alert Fatigue Prevention**: Tune thresholds to maintain signal-to-noise ratio

### Performance Monitoring for Monitors
```opal
// Monitor your monitors - track execution times and success rates
statsby
  avg_execution_time: avg(execution_duration),
  success_rate: (sum(if(status = "success", 1, 0)) / count()) * 100,
  group_by(monitor_name)
| filter success_rate < 95 or avg_execution_time > 30000  // 30 second threshold
```

### Data Quality Checks
```opal
// Validate data completeness before anomaly detection
statsby
  total_services: count_distinct(service_name),
  total_samples: count(),
  null_latency_count: sum(if(is_null(p95_ms), 1, 0)),
  group_by()
| make_col data_quality_score: ((total_samples - null_latency_count) / total_samples) * 100
| filter data_quality_score < 95  // Alert if data quality drops below 95%
```

---

## Conclusion

This guide provides a comprehensive foundation for implementing anomaly detection in Observe. Start with basic patterns for standard services, then evolve to advanced patterns for critical systems. Remember to:

1. **Match patterns to service criticality** - Use sophisticated detection for important services
2. **Balance sensitivity vs noise** - Tune thresholds to maintain alert quality
3. **Include context in alerts** - Make alerts actionable with baseline comparisons
4. **Monitor your monitors** - Ensure detection systems are performing well
5. **Iterate and improve** - Continuously refine based on operational feedback

For additional support or advanced use cases, consult the Observe documentation or reach out to the community.
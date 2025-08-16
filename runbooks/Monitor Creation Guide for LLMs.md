# Observe Runbook: Comprehensive Monitor Creation Guide for LLMs

## Overview

This guide provides detailed instructions for creating monitors in Observe using the v2 monitoring system. It covers OPAL query requirements, common pitfalls, and step-by-step workflows for different monitor types.

## Tool Call Workflow

### 1. Investigation Phase (Always Start Here)
```
1. get_relevant_docs(query="monitor creation OPAL syntax") - Get syntax help
2. recommend_runbook(query="your monitoring objective") - Get strategy
3. list_datasets(match="relevant_term") - Find datasets
4. get_dataset_info(dataset_id="...") - Understand schema
```

### 2. Query Development Phase
```
5. execute_opal_query() - Test simple queries first
6. execute_opal_query() - Build complexity incrementally
7. execute_opal_query() - Validate final query structure
```

### 3. Monitor Creation Phase
```
8. create_monitor() - Create with validated query
9. get_monitor(monitor_id="...") - Verify creation
```

## Monitor Types and OPAL Requirements

### Threshold Monitors
**Purpose**: Alert when a numeric value crosses a threshold
**Required Output**: Must have a column named "count" containing the numeric value to compare

#### OPAL Structure Requirements:
```opal
// Basic structure - MUST output column named "count"
filter [conditions] 
| [aggregation producing numeric result] 
| make_col count:[your_calculated_value]
```

#### Common Patterns:

**Error Rate Monitoring**:
```opal
filter service_name = "servicename" 
| filter metric = "span_error_count_5m" or metric = "span_call_count_5m" 
| timechart 5m, 
    error_count:sum(case(metric="span_error_count_5m", value, true, 0)), 
    call_count:sum(case(metric="span_call_count_5m", value, true, 0)) 
| make_col count:case(call_count > 0, error_count/call_count*100, true, 0)
```

**Simple Metric Threshold**:
```opal
filter metric = "cpu_utilization" and host = "server1" 
| timechart 5m, count:avg(value)
```

**Error Count Monitoring**:
```opal
filter service_name = "servicename" and body ~ "error" 
| timechart 5m, count()
```

### Count Monitors
**Purpose**: Alert when the number of matching records crosses a threshold
**Required Output**: Uses built-in count() function or row counting

```opal
filter [conditions]
| timechart [interval], count()
```

### Promote Monitors
**Purpose**: Send matching data as alerts (each row becomes an alert)
**Required Output**: All relevant data columns for the alert

```opal
filter [conditions]
| [optional transformations]
| pick_col [relevant_columns]
```

## Critical OPAL Syntax Rules

### ✅ Correct Syntax Patterns

**Filtering**:
```opal
filter field = "value"
filter field > 100
filter field = "value1" or field = "value2"  // NOT: field in ("value1", "value2")
// NEVER: filter timestamp > timestamp - 1h  (time filtering via API parameters only)
```

**Aggregations**:
```opal
timechart 5m, count()
timechart 5m, avg_value:avg(metric_value)
statsby total:sum(value), group_by(service_name)
```

**Conditional Logic**:
```opal
case(condition, true_value, false_condition, false_value, true, default_value)
sum(case(metric="error_count", value, true, 0))  // Must use with aggregation functions
```

**Column Creation**:
```opal
make_col new_column:expression
make_col count:calculated_value  // Required for threshold monitors
```

**Time Operations**:
```opal
timechart 5m, aggregation  // Creates time buckets
// NEVER: filter time > time - 4h  (time filtering via API parameters only)
```

### ❌ Avoid These Antipatterns

**DO NOT USE**:
- **Time filtering in OPAL**: `filter timestamp >`, `filter time >` → Use API parameters instead
- SQL syntax: `SELECT`, `GROUP BY`, `HAVING`
- `filter field in ("val1", "val2")` → Use: `filter field = "val1" or field = "val2"`
- `sort desc column` → Use: `topk n, column`
- `pick column` → Use: `pick_col column` 
- `latest()` function → Use: `max()`, `avg()`, or similar
- Complex nested queries without testing components first

## Common Error Patterns and Solutions

### Error: "column reference count doesn't exist"
**Cause**: Threshold monitors require a column named "count"
**Solution**: Add `| make_col count:your_calculated_value` at the end

### Error: "align verb: column has to be aggregation or grouping column"
**Cause**: Using `align` with columns that aren't part of aggregation
**Solution**: Use `statsby` or `timechart` for aggregations first

### Error: "unknown function/verb"
**Cause**: Using non-existent OPAL functions
**Solution**: Check documentation, use correct OPAL syntax

### Error: "expected boolean expression"
**Cause**: Filter conditions not properly formatted
**Solution**: Use correct comparison operators and syntax

## Step-by-Step Monitor Creation Workflow

### Phase 1: Dataset Discovery and Validation (2-3 minutes)
```
1. list_datasets(match="service", interface="metric") // Find relevant datasets
2. get_dataset_info(dataset_id="...") // Check schema and field names
3. execute_opal_query(query="limit 5") // Verify data exists (time via API params)
```

### Phase 2: Query Development (5-10 minutes)
```
4. Start simple: execute_opal_query(query="filter service_name = 'target' | limit 10")
5. Add filters: execute_opal_query(query="filter service_name = 'target' | limit 10")
6. Add aggregations: execute_opal_query(query="filter... | timechart 5m, count()")
7. Build final query with "count" column for threshold monitors
```

### Phase 3: Monitor Creation (1-2 minutes)
```
8. create_monitor(
     name="Descriptive Monitor Name",
     description="Clear description of what triggers alert",
     query="validated_opal_query",
     dataset_id="target_dataset_id",
     threshold=numeric_value,
     window="5m",
     frequency="5m"
   )
9. get_monitor(monitor_id="returned_id") // Verify successful creation
```

## Monitor Configuration Best Practices

### Naming Convention
- **Format**: `[Service] [Metric Type] [Condition] [Threshold]`
- **Examples**: 
  - "CartService Error Rate Monitor 2%"
  - "Frontend Latency Alert P95 500ms"
  - "Database Connection Count Critical 100"

### Threshold Selection
- **Error Rates**: 1-5% depending on service criticality
- **Latency**: Based on SLA requirements (P95/P99)
- **Resource Usage**: 80-90% for warnings, 95%+ for critical
- **Count Thresholds**: Based on historical baselines + margin

### Timing Configuration
- **Frequency**: 5m for most applications, 1m for critical services
- **Window**: Match frequency to avoid gaps (5m window for 5m frequency)
- **Stabilization Delay**: Use only if data arrives out of order

### Description Template
```
Alert when [service] [metric] exceeds [threshold] for [duration]. 
[Brief explanation of calculation method].
Monitors [specific metric names] and alerts when [specific condition].
```

## Example Monitor Configurations

### Error Rate Monitor
```
Name: "CartService Error Rate Monitor 2%"
Description: "Alert when cartservice error rate exceeds 2% for sustained periods. Calculates error rate as percentage by dividing error count by call count over 5-minute intervals."
Query: "filter service_name = 'cartservice' | filter metric = 'span_error_count_5m' or metric = 'span_call_count_5m' | timechart 5m, error_count:sum(case(metric='span_error_count_5m', value, true, 0)), call_count:sum(case(metric='span_call_count_5m', value, true, 0)) | make_col count:case(call_count > 0, error_count/call_count*100, true, 0)"
Threshold: 2.0
Window: "5m"
Frequency: "5m"
```

### Latency Monitor
```
Name: "API Response Time P95 Alert"
Description: "Alert when API P95 response time exceeds 500ms over 5-minute period"
Query: "filter service_name = 'api-service' | filter metric = 'span_duration_5m' | align latency:tdigest_quantile(tdigest_combine(m_tdigest('span_duration_5m')), 0.95) | timechart 5m, count:avg(latency)"
Threshold: 500000000  // 500ms in nanoseconds
Window: "5m"
Frequency: "5m"
```

### Count Monitor
```
Name: "High Error Volume Alert"
Description: "Alert when error log count exceeds 50 errors in 5 minutes"
Query: "filter level = 'ERROR' | filter service_name = 'critical-service' | timechart 5m, count()"
Threshold: 50
Window: "5m"
Frequency: "5m"
```

## Troubleshooting Checklist

### Before Creating Monitor:
- [ ] Dataset schema checked with `get_dataset_info()`
- [ ] Field names verified in actual data
- [ ] Simple query tested with `limit 5`
- [ ] Time filtering confirmed working
- [ ] Aggregation logic validated
- [ ] Final query produces "count" column for threshold monitors

### If Monitor Creation Fails:
1. **Check Error Message**: Look for specific field or syntax issues
2. **Validate Query**: Re-run OPAL query with `execute_opal_query()`
3. **Verify Column Names**: Ensure "count" column exists for threshold monitors
4. **Check Data Types**: Ensure numeric values for thresholds
5. **Simplify Query**: Start with basic version and add complexity

### Common Query Testing Pattern:
```opal
// Test 1: Basic data access
limit 5  // Time range via API parameters

// Test 2: Add service filter  
filter time > time - 1h | filter service_name = "target" | limit 5

// Test 3: Add metric filter
filter time > time - 1h | filter service_name = "target" | filter metric = "target_metric" | limit 5

// Test 4: Add aggregation
filter time > time - 1h | filter service_name = "target" | filter metric = "target_metric" | timechart 5m, count()

// Test 5: Final monitor query with count column
[full_query] | make_col count:[calculated_value]
```

## Integration with Actions

### Adding Notification Actions
After monitor creation, you can add actions using the Observe UI or by creating shared actions:
- **Email**: Direct email notifications
- **Slack**: Channel notifications with rich formatting
- **PagerDuty**: Incident management integration
- **Webhook**: Custom integrations

### Action Configuration Tips
- Use different severity levels for different thresholds
- Configure reminder frequencies for persistent issues
- Set up end notifications for incident closure
- Use Mustache templating for dynamic alert content

## Performance Considerations

### Query Optimization
- Start with time filters to reduce data volume
- Use appropriate row limits during development
- Avoid complex nested aggregations
- Test with small time windows first

### Monitor Resource Usage
- Balance freshness vs. cost with appropriate frequencies
- Use acceleration manager to monitor transform costs
- Consider data retention policies for historical analysis
- Monitor the monitors themselves for performance impact

This guide should be referenced whenever creating monitors to ensure consistent, reliable alerting across your Observe implementation.
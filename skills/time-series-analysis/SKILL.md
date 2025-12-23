---
name: time-series-analysis
description: Analyze event datasets (logs) and intervals over time using OPAL timechart. Use when you need to visualize trends, track metrics over time, or create time-series charts. Covers timechart for temporal binning, bin duration options (1h, 5m, 1d), options(bins:N) for controlling bin count, and understanding temporal output columns (_c_valid_from, _c_valid_to, _c_bucket). Returns multiple rows per group for time-series visualization. For single summaries, see aggregating-event-datasets skill.
---

# Time-Series Analysis with timechart

The `timechart` verb bins data over time and applies aggregation functions to create time-series visualizations. This skill teaches you how to analyze trends and patterns in your data over specific time periods using OPAL.

## When to Use This Skill

- Visualizing trends over time (error rate by hour, request volume trends)
- Creating time-series charts for dashboards
- Tracking how metrics change throughout the day/week/month
- Comparing behavior across time periods
- Identifying spikes or anomalies in temporal data

**Note**: `timechart` returns **multiple rows per group** (one per time bin) for time-series visualization. For single summary rows, see the `aggregating-event-datasets` skill.

## Prerequisites

- Access to Observe tenant via MCP
- Understanding of event or interval datasets
- Familiarity with aggregation concepts (see aggregating-event-datasets skill)

## Key Concepts

### timechart - Temporal Binning

`timechart` groups data into time buckets (bins) and aggregates within each bucket:
- Returns **multiple rows per group** (one row per time bin)
- Adds temporal columns: `_c_valid_from`, `_c_valid_to`, `_c_bucket`
- Default: 300 bins (Observe picks optimal size)
- Can specify bin duration: `1h`, `5m`, `1d`, `30s`, etc.
- Can control bin count: `options(bins: N)`

**Syntax**:
```opal
timechart [bin_duration], aggregation_function(), group_by(dimension1, dimension2, ...)
```

### timechart vs statsby

| Verb | Output | Use Case |
|------|--------|----------|
| `statsby` | 1 row per group (total across time range) | Summary reports, totals |
| `timechart` | Multiple rows per group (time-series) | Trending, charts, dashboards |

**Example comparison**:

**statsby** (summary):
```opal
statsby count(), group_by(namespace)
# Output: 1 row per namespace
```

**timechart** (time-series):
```opal
timechart 1h, count(), group_by(namespace)
# Output: 24 rows per namespace (for 24h query)
```

### Temporal Output Columns

`timechart` adds three columns to output:
- `_c_valid_from` - Start of time bin (nanosecond timestamp)
- `_c_valid_to` - End of time bin (nanosecond timestamp)
- `_c_bucket` - Bucket identifier (integer)

## Discovery Workflow

Same as other event/interval skills:

**Step 1: Find dataset**
```
discover_context("kubernetes logs")
```

**Step 2: Get schema**
```
discover_context(dataset_id="YOUR_DATASET_ID")
```

Note fields for filtering, grouping, and aggregating.

## Basic Patterns

### Pattern 1: Fixed Bin Duration

**Use case**: Hourly error count over 24 hours

```opal
filter contains(body, "error")
| timechart 1h, count()
```

**Explanation**: Bins data into 1-hour buckets, counts errors in each bucket. For 24h time range, returns 24 rows.

**Output**:
```csv
_c_valid_from,_c_valid_to,count,_c_bucket
1763110800000000000,1763114400000000000,4,489753
1763107200000000000,1763110800000000000,5,489752
...
```

### Pattern 2: Time-Series by Dimension

**Use case**: Error count per hour, grouped by namespace

```opal
filter contains(body, "error")
| make_col namespace:string(resource_attributes."k8s.namespace.name")
| timechart 1h, count(), group_by(namespace)
```

**Explanation**: Returns multiple rows per namespace - one row for each hour. Suitable for multi-line chart showing errors over time per namespace.

**Output**:
```csv
_c_valid_from,_c_valid_to,namespace,count,_c_bucket
1763110800000000000,1763114400000000000,kube-system,4,489753
1763107200000000000,1763110800000000000,kube-system,5,489752
1763100000000000000,1763103600000000000,observe,16,489750
1763100000000000000,1763103600000000000,kube-system,5,489750
...
```

### Pattern 3: Controlling Bin Count

**Use case**: Get exactly 10 data points across time range

```opal
filter contains(body, "error")
| make_col namespace:string(resource_attributes."k8s.namespace.name")
| timechart options(bins: 10), count(), group_by(namespace)
```

**Explanation**: Observe automatically calculates bin duration to produce at most 10 bins across the query time range.

### Pattern 4: Multiple Aggregations

**Use case**: Track multiple metrics over time

```opal
make_col namespace:string(resource_attributes."k8s.namespace.name")
| timechart 1h,
    total_logs:count(),
    group_by(namespace)
```

**Explanation**: Calculate multiple aggregations per time bin. Each metric becomes a column in the output.

### Pattern 5: Default Auto-Binning

**Use case**: Let Observe pick optimal bin size

```opal
filter contains(body, "error")
| make_col namespace:string(resource_attributes."k8s.namespace.name")
| timechart count(), group_by(namespace)
```

**Explanation**: Without specifying duration or bins, Observe defaults to 300 bins with optimal size for the time range.

## Complete Example

End-to-end workflow for creating an error rate dashboard.

**Scenario**: Create a time-series chart showing error trends per namespace over the last 24 hours.

**Step 1: Discovery**

```
discover_context("kubernetes logs")
```

Found: Dataset "Kubernetes Explorer/Kubernetes Logs" (ID: 42161740)

**Step 2: Build query**

```opal
filter contains(body, "error") or contains(body, "ERROR")
| make_col namespace:string(resource_attributes."k8s.namespace.name")
| timechart 1h, error_count:count(), group_by(namespace)
```

**Step 3: Execute**

```
execute_opal_query(
    query="[query above]",
    primary_dataset_id="42161740",
    time_range="24h"
)
```

**Step 4: Interpret results**

```csv
_c_valid_from,_c_valid_to,namespace,error_count,_c_bucket
1763110800000000000,1763114400000000000,kube-system,4,489753
1763107200000000000,1763110800000000000,kube-system,5,489752
1763103600000000000,1763107200000000000,kube-system,5,489751
1763100000000000000,1763103600000000000,observe,16,489750
1763100000000000000,1763103600000000000,kube-system,5,489750
...
```

**Analysis**:
- Each row represents one hour for one namespace
- `kube-system` has relatively stable error rate (4-7 per hour)
- `observe` namespace shows a spike (16 errors in one hour)
- Data suitable for line chart with multiple series (one per namespace)

**Visualization**:
- X-axis: Time (`_c_valid_from` or `_c_valid_to`)
- Y-axis: `error_count`
- Series/Lines: One per `namespace`

## Advanced Patterns

### Pattern 6: Bin Duration Options

**Common bin durations**:

```opal
# Fine-grained (short time ranges)
timechart 30s, count()   # 30 second bins
timechart 1m, count()    # 1 minute bins
timechart 5m, count()    # 5 minute bins

# Medium (hours to days)
timechart 1h, count()    # 1 hour bins
timechart 6h, count()    # 6 hour bins

# Coarse (days to weeks)
timechart 1d, count()    # 1 day bins
timechart 1w, count()    # 1 week bins
```

**Choosing bin size**:
- Match your query time range: 1h range → 1m or 5m bins, 7d range → 1h or 6h bins
- Consider visualization: Too many bins = cluttered chart, too few = lost detail
- Start with auto-binning, adjust as needed

### Pattern 7: Rate Calculations

**Use case**: Calculate error rate (errors per second)

```opal
filter contains(body, "error")
| make_col namespace:string(resource_attributes."k8s.namespace.name")
| timechart 1h, error_count:count(), group_by(namespace)
| make_col error_rate:float64(error_count)/3600.0  # errors per second (1h = 3600s)
```

**Explanation**: Adds derived column calculating rate per second from hourly counts.

## Common Pitfalls

### Pitfall 1: Using statsby When You Want Time-Series

❌ **Wrong** (if you want trends):
```opal
statsby count(), group_by(namespace)
# Returns 1 row per namespace (no time dimension)
```

✅ **Correct**:
```opal
timechart 1h, count(), group_by(namespace)
# Returns multiple rows per namespace (time-series)
```

**Why**: `statsby` gives totals, `timechart` gives trends over time.

### Pitfall 2: Too Many Bins

❌ **Wrong**:
```opal
timechart 1s, count()  # For 24h range = 86,400 bins!
```

✅ **Correct**:
```opal
timechart 1m, count()  # For 24h range = 1,440 bins (manageable)
# OR
timechart options(bins: 100), count()  # Let Observe pick duration
```

**Why**: Too many bins overwhelm visualization and query performance.

### Pitfall 3: Confusing Timestamps

❌ **Wrong**:
```opal
# Trying to use timestamp field directly for binning
filter timestamp > 1763100000000000000
| statsby count(), group_by(timestamp)
```

✅ **Correct**:
```opal
# Use timechart for temporal binning
timechart 1h, count()
```

**Why**: `timechart` automatically handles time binning - don't need manual timestamp grouping.

### Pitfall 4: Expecting Single Summary

❌ **Wrong** (if you want total):
```opal
timechart 1h, count()
# Returns 24 rows for 24h range - need to sum them manually!
```

✅ **Correct** (for total):
```opal
statsby count()
# Returns 1 row with total
```

**Why**: `timechart` is for time-series, not totals. Use `statsby` for summaries.

## Tips and Best Practices

- **Start with defaults**: Use `timechart count()` first, adjust bin size after seeing results
- **Match bin to time range**: Short ranges (1h) → small bins (1m), long ranges (30d) → large bins (1d)
- **Name your metrics**: Use `error_count:count()` not just `count()`
- **Filter first**: Apply filters before `timechart` for better performance
- **Visualization-ready**: Output is designed for time-series charts
- **Test with small ranges**: Start with 1h or 24h, expand once query works
- **options(bins: N)**: Use when you want specific number of data points

## Bin Duration Reference

**Time Units**:
- `s` - seconds
- `m` - minutes
- `h` - hours
- `d` - days
- `w` - weeks

**Examples**:
- `30s` - 30 seconds
- `5m` - 5 minutes
- `1h` - 1 hour
- `6h` - 6 hours
- `1d` - 1 day
- `1w` - 1 week

**Default Behavior**:
- No duration specified: `options(bins: 300)` - Observe picks optimal size
- `options(bins: 1)` - Single bin (equivalent to statsby)
- `options(bins: N)` - At most N bins across time range

## Additional Resources

For more details, see:
- [RESEARCH.md](../../RESEARCH.md) - Tested patterns including timechart vs statsby comparison
- [OPAL Documentation](https://docs.observeinc.com/en/latest/content/query-language-reference/) - Official OPAL docs

## Related Skills

- [aggregating-event-datasets] - For single summary rows (statsby)
- [filtering-event-datasets] - For filtering before time-series aggregation
- [analyzing-interval-datasets] - timechart works on Intervals too (spans, resources)

---

**Last Updated**: November 14, 2025
**Version**: 1.0
**Tested With**: Observe OPAL v2.x

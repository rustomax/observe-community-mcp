# Investigating Textual Data in Event Datasets

Investigate and analyze textual data in logs, span events, and other event datasets using OPAL filtering and pattern matching. **Use when analyzing error messages, searching log patterns, troubleshooting application issues, or finding specific events in textual data.** Covers discovering textual datasets, error detection patterns, regex matching, wide net filtering strategies, aggregation with sampling, and context extraction from nested fields.

For pre-aggregated metrics, see **aggregating-gauge-metrics** skill. For distributed tracing analysis, see **analyzing-apm-data** skill. For time-series trends, see **time-series-analysis** skill.

---

## Table of Contents

1. [When to Use This Skill](#when-to-use-this-skill)
2. [Quick Reference](#quick-reference)
3. [Understanding Textual Datasets](#understanding-textual-datasets)
4. [Discovery Workflow](#discovery-workflow)
5. [Error Detection Patterns](#error-detection-patterns)
6. [Text Search vs Regex Matching](#text-search-vs-regex-matching)
7. [Wide Net Filtering Strategy](#wide-net-filtering-strategy)
8. [Aggregation and Sampling](#aggregation-and-sampling)
9. [Context Extraction](#context-extraction)
10. [Complete Examples](#complete-examples)
11. [Common Pitfalls](#common-pitfalls)
12. [Cross-References](#cross-references)

---

## When to Use This Skill

Use this skill when users ask questions like:

**Error Analysis**:
- "Show me errors in Kubernetes logs"
- "What are the top 10 error types in my containers?"
- "Find all Redis connection errors"
- "Which namespaces have the most errors?"

**Pattern Search**:
- "Search logs for timeout messages"
- "Find all database connection failures"
- "Show me warnings in stderr"
- "Get recent errors from CloudWatch logs"

**Troubleshooting**:
- "Are there any errors related to authentication?"
- "Show me error trends over the last 24 hours"
- "Find all exceptions in the frontend service"
- "What errors happened in the last hour?"

**When NOT to use this skill**:
- **Metrics queries** (error counts from metrics) → Use **aggregating-gauge-metrics**
- **APM/tracing analysis** (spans, traces) → Use **analyzing-apm-data**
- **Time-series trending** → Use **time-series-analysis**
- **Simple filtering** (known field values) → Use **filtering-event-datasets**

---

## Quick Reference

### Error Detection Patterns

| Pattern | OPAL Query | Use Case |
|---------|------------|----------|
| **Stream filtering** | `filter stream = "stderr"` | Container stderr logs |
| **Text search** | `filter contains(body, "error")` | Exact substring (case-sensitive) |
| **Case-insensitive regex** | `filter body ~ /error/i` | Flexible error matching |
| **Multiple patterns** | `filter body ~ /error\|exception\|failed/i` | Wide net approach |
| **Wide net** | `filter body ~ /error/i or stream = "stderr"` | Multiple conditions |
| **Recent errors** | `filter ... \| sort desc(timestamp) \| limit 20` | Latest events |

### Common Field Names by Dataset Type

| Dataset Type | Message Field | Severity Field | Context Fields |
|--------------|---------------|----------------|----------------|
| **K8s Logs** | `body` | `stream` | `namespace`, `pod`, `container` |
| **CloudWatch** | `message` | `level` | `logGroup`, `logStream` |
| **Spans** | `error_message` | `error` (bool) | `service_name`, `span_name` |
| **Span Events** | `event_name` | N/A | `trace_id`, `span_id` |

**Critical**: Always inspect dataset schema first to identify correct field names!

---

## Understanding Textual Datasets

### What Are Textual Event Datasets?

Event datasets contain **point-in-time log entries** with text messages. Each event has:
- **Single timestamp** (not a duration)
- **Text field** with log message (`body`, `message`, `log`, etc.)
- **Severity indicators** (`level`, `stream`, `severity`)
- **Context fields** (service, namespace, pod, container)

### Common Dataset Types

**1. Container Logs** (Kubernetes, Docker):
- Interface: `log`
- Message field: `body`
- Severity: `stream` ("stdout", "stderr")
- Context: Nested `resource_attributes.k8s.*`

**2. Cloud Provider Logs** (CloudWatch, Stackdriver):
- Interface: `log`
- Message field: `message` or `log`
- Severity: `level` or `severity`
- Context: `logGroup`, `logStream`, `resource.*`

**3. Span Events** (OpenTelemetry):
- Interface: `log`
- Message field: `event_name`
- Context: `trace_id`, `span_id`, `service_name`

**4. Application Logs** (Custom):
- Interface: `log`
- Varies by implementation

### Key Difference from Metrics

| Aspect | Event Datasets (Logs) | Metrics |
|--------|----------------------|---------|
| **Query approach** | `filter` → `statsby` | `align` → `aggregate` |
| **Data granularity** | Individual log entries | Pre-aggregated values |
| **Best for** | Detailed investigation, text search | Volume trends, counts |
| **Performance** | Slower for large volumes | Fast, optimized |

**Rule**: Use metrics for volume/trends, use logs for detailed investigation.

---

## Discovery Workflow

### Step 1: Identify User Intent

**Listen for dataset hints**:
- "kubernetes logs" → K8s container logs
- "cloudwatch" → AWS CloudWatch logs
- "stderr" → Container error stream
- "application logs" → Generic logs
- "span events" → OpenTelemetry events

**No specific hint?** Use discovery to find textual datasets.

### Step 2: Discover Textual Datasets

```python
# General search
discover_context("logs")

# Specific search
discover_context("kubernetes logs")
discover_context("cloudwatch")
discover_context("application errors")

# Filter by interface type
discover_context("", interface_filter="log")
```

**Look for**:
- Interface: `log` (event datasets with text)
- Category: "Logs", "Events"
- Dataset names with "Log", "Event", "CloudWatch", "K8s"

### Step 3: Get Detailed Schema

**CRITICAL**: Always get field names before writing queries!

```python
# Get complete field list
discover_context(dataset_id="42161740")

# Identify:
# 1. Message field: body, message, log, event_name
# 2. Severity field: stream, level, severity
# 3. Context fields: namespace, pod, service_name, etc.
```

### Step 4: Check Field Samples

**Pay attention to**:
- Field type: `text`, `string`, `keyword`
- Sample values: See actual field content
- Nested fields: `resource_attributes.*`, `attributes.*`

**Example schema output**:
```
body (text) - Sample: "Error: connection timeout to redis:6379"
stream (string) - Sample: "stderr"
namespace (string) - Sample: "default"
resource_attributes (object) - Nested fields:
  - k8s.namespace.name
  - k8s.pod.name
```

---

## Error Detection Patterns

### Pattern 1: Stream Filtering (Container Logs)

**When to use**: Kubernetes/Docker logs with `stream` field

**Assumption**: Container errors typically written to stderr

```opal
filter stream = "stderr"
| make_col namespace:string(resource_attributes."k8s.namespace.name"),
          pod, container
| statsby error_count:count(), group_by(namespace, pod, container)
| sort desc(error_count)
| limit 20
```

**Result**: Error volume by container (1h):
```
namespace          pod                              container                error_count
default            opentelemetry-collector-xyz      otel-collector          1422
default            recommendationservice-abc        server                  118
observe            cluster-metrics-def              metrics-agent           60
```

**Use case**: "Which containers are generating the most stderr output?"

**Limitation**: Not all errors go to stderr - some apps write errors to stdout

---

### Pattern 2: Text Search with contains()

**When to use**: Exact substring matching (case-sensitive)

```opal
filter contains(body, "error") or contains(body, "ERROR") or contains(body, "Error")
| make_col namespace:string(resource_attributes."k8s.namespace.name"),
          error_snippet:body
| sort desc(timestamp)
| limit 20
```

**Result**: Recent errors with exact text match

**Pros**:
- Simple syntax
- Fast for exact matches

**Cons**:
- Case-sensitive (must check "error", "ERROR", "Error")
- No pattern flexibility

**When to use instead of regex**: Known exact string, simple search

---

### Pattern 3: Case-Insensitive Regex

**When to use**: Flexible error matching with case variations

**CRITICAL SYNTAX**: Use `/pattern/i` with **forward slashes** (NOT string quotes)

```opal
filter body ~ /error/i
| make_col namespace:string(resource_attributes."k8s.namespace.name"),
          container
| statsby error_count:count(), group_by(namespace, container)
| sort desc(error_count)
| limit 20
```

**Result** (1h):
```
namespace          container                error_count
observe            cluster-metrics          59
default            prometheus-server        17
kube-system        calico-node             4
```

**Regex patterns**:
- `/error/i` - Matches "error", "ERROR", "Error"
- `/error|exception|failed/i` - Alternation (OR)
- `/[Ee]rror/` - Character class (case-sensitive)
- `/timeout.*error/i` - Sequence matching

**Syntax rules**:
- **CORRECT**: `body ~ /pattern/i`
- **WRONG**: `body ~ "pattern"` (string literal, not regex)
- **WRONG**: `body ~ "(?i)pattern"` (PCRE not supported)

---

### Pattern 4: Multiple Error Patterns (Wide Net)

**When to use**: Catch different error expressions

```opal
filter body ~ /error|exception|failed|failure/i
| make_col namespace:string(resource_attributes."k8s.namespace.name"),
          container
| statsby count:count(), group_by(namespace, container)
| sort desc(count)
```

**Result**: Catches more errors than single pattern
- "error" - Standard error messages
- "exception" - Java, Python exceptions
- "failed" - Command/operation failures
- "failure" - Alternative phrasing

**Regex alternation**: Use `|` for OR matching

---

### Pattern 5: Wide Net Strategy (Multiple Conditions)

**When to use**: Maximum error detection across different log formats

**Principle**: Combine text matching + severity fields + stream filtering

```opal
filter body ~ /error|exception|failed/i
    or stream = "stderr"
    or level = "error"
| make_col namespace:string(resource_attributes."k8s.namespace.name"),
          pod, container
| statsby error_count:count(), group_by(namespace, container)
| sort desc(error_count)
```

**Why this works**:
- `body ~ /error/i` - Catches text mentions
- `stream = "stderr"` - Catches stderr output (might not have "error" in text)
- `level = "error"` - Catches structured severity (CloudWatch, syslog)

**Result** (1h):
```
namespace          container                error_count    Source
default            opentelemetry-collector  1420           stderr (no "error" text)
observe            cluster-metrics          59             body matches /error/
default            prometheus-server        17             body matches /error/
```

**Best practice**: Always cast a wide net for error detection!

---

### Pattern 6: Recent Errors with Details

**When to use**: Troubleshooting recent issues, seeing actual error messages

```opal
filter body ~ /error/i or stream = "stderr"
| make_col namespace:string(resource_attributes."k8s.namespace.name"),
          pod,
          container,
          error_msg:body,
          error_time:format_time(timestamp, 'YYYY-MM-DD HH24:MI:SS')
| sort desc(timestamp)
| limit 20
```

**Result**: Latest 20 errors with full context and messages

**Use case**: "What are the most recent errors?"

**Note**: `format_time()` for human-readable timestamps (display only)

---

## Text Search vs Regex Matching

### Text Fields vs String Fields

**Text fields** (like `body`, `message`, `log`):
- Unstructured text content
- Use `contains()` for exact substring
- Use `~ /pattern/` for regex

**String fields** (like `stream`, `level`, `namespace`):
- Structured categorical values
- Use `=`, `!=` for exact match
- Use `~ /pattern/` for regex

### When to Use Each

| Scenario | Approach | Example |
|----------|----------|---------|
| **Exact substring** | `contains()` | `contains(body, "timeout")` |
| **Case-insensitive** | Regex with `/i` | `body ~ /timeout/i` |
| **Pattern matching** | Regex | `body ~ /error[0-9]+/i` |
| **Multiple patterns** | Regex alternation | `body ~ /error\|exception/i` |
| **Exact field value** | Equality | `stream = "stderr"` |

### OPAL Regex Syntax Reference

**CRITICAL**: OPAL uses **POSIX ERE** (Extended Regular Expressions), NOT PCRE

**Correct syntax**:
```opal
body ~ /pattern/         # Case-sensitive regex
body ~ /pattern/i        # Case-insensitive (i flag)
body ~ /error|exception/ # Alternation (OR)
body ~ /[Ee]rror/        # Character class
body ~ /timeout.*error/  # Sequence
```

**Incorrect syntax** (will fail or do literal string match):
```opal
body ~ "pattern"              # String literal, NOT regex
body ~ "(?i)pattern"          # PCRE inline modifiers not supported
body ~ "error[0-9]+"          # String matching, not regex
```

**Common regex patterns**:
- `.` - Any character
- `*` - Zero or more
- `+` - One or more
- `?` - Zero or one
- `[abc]` - Character class
- `[a-z]` - Range
- `|` - Alternation (OR)
- `^` - Start of line
- `$` - End of line

---

## Wide Net Filtering Strategy

### Why Wide Net Matters

**Problem**: Different logs express errors differently
- Some use "error" in text
- Some write to stderr (no "error" keyword)
- Some use structured `level` field
- Some use "exception", "failed", "failure"

**Solution**: Combine multiple conditions to catch all variations

### Wide Net Template

```opal
filter <text_patterns> or <severity_field> or <stream_field>
| make_col <context_fields>
| statsby count(), group_by(<group_fields>)
```

### Example 1: Kubernetes Logs

```opal
filter body ~ /error|exception|failed|failure/i
    or stream = "stderr"
| make_col namespace:string(resource_attributes."k8s.namespace.name"),
          container
| statsby error_count:count(), group_by(namespace, container)
| sort desc(error_count)
```

**Catches**:
- Body text: "Error connecting to database"
- Stderr: Container crashes (no "error" in text)

### Example 2: CloudWatch Logs

```opal
filter message ~ /error|exception/i
    or level = "ERROR"
    or level = "FATAL"
| make_col logGroup, logStream
| statsby error_count:count(), group_by(logGroup, logStream)
| sort desc(error_count)
```

**Catches**:
- Message text: "Connection error"
- Structured level: `{"level": "ERROR", "message": "..."}`

### Example 3: Application Logs (Generic)

```opal
filter body ~ /error|exception|failed|timeout|refused/i
    or stream = "stderr"
    or level = "error"
    or severity = "ERROR"
| make_col service:string(resource_attributes."service.name"),
          msg:body
| statsby count:count(), sample:any(msg), group_by(service)
| sort desc(count)
```

**Principle**: Check all possible error indicators in the dataset

---

## Aggregation and Sampling

### Pattern 7: Error Counts by Group

**When to use**: "Which namespaces/services have most errors?"

```opal
filter body ~ /error/i or stream = "stderr"
| make_col namespace:string(resource_attributes."k8s.namespace.name"),
          container
| statsby error_count:count(), group_by(namespace, container)
| sort desc(error_count)
| limit 20
```

**Result**: Top 20 error sources

**Aggregation**: `statsby count()` counts all matching events per group

---

### Pattern 8: Error Counts with Sample Messages

**When to use**: "Show me top errors WITH example messages"

**Critical function**: `any()` - Returns one sample value from the group

```opal
filter body ~ /error/i
| make_col namespace:string(resource_attributes."k8s.namespace.name"),
          container,
          error_snippet:body
| statsby top_errors:count(),
          sample_msg:any(error_snippet),
          group_by(namespace, container)
| sort desc(top_errors)
| limit 10
```

**Result** (1h):
```
namespace   container              top_errors  sample_msg
default     prometheus-server      17          "Error translating OTLP metrics to Prometheus write request"
kube-system calico-node           4           "Watch error received from Upstream"
default     frontend              2           "Error: 8 RESOURCE_EXHAUSTED"
default     cartservice           1           "Can't access cart storage... connect to redis"
```

**Use case**: See error counts AND understand what the errors look like

**Why `any()`**: Provides context without listing all error messages

---

### Pattern 9: Error Trends Over Time

**When to use**: "Show me error trends in the last 24 hours"

**Use `timechart`** for time-series aggregation (NOT `statsby`)

```opal
filter body ~ /error/i or stream = "stderr"
| make_col namespace:string(resource_attributes."k8s.namespace.name")
| timechart 1h, error_count:count(), group_by(namespace)
```

**Result**: Time-series data (multiple rows per namespace)
```
_c_bucket    namespace    error_count
2025-11-14T00:00:00Z    default    145
2025-11-14T01:00:00Z    default    132
2025-11-14T02:00:00Z    default    89
...
```

**Output includes**:
- `_c_bucket` - Time bucket
- `_c_valid_from`, `_c_valid_to` - Bucket boundaries
- One row per (namespace, time_bucket)

**For trending**: See **time-series-analysis** skill

---

### Pattern 10: Targeted Component Search

**When to use**: "Find all Redis connection errors"

**Use specific regex** targeting component names

```opal
filter body ~ /redis.*error|connection.*redis|redis.*timeout/i
| make_col namespace:string(resource_attributes."k8s.namespace.name"),
          pod,
          error_msg:body,
          error_time:format_time(timestamp, 'YYYY-MM-DD HH24:MI:SS')
| sort desc(timestamp)
| limit 20
```

**Result**: Only Redis-related errors

**Common targeted searches**:
- Database: `/postgres|mysql|database.*error/i`
- Network: `/timeout|connection.*refused|network.*error/i`
- Authentication: `/auth.*failed|unauthorized|403|401/i`
- Resources: `/out of memory|resource exhausted|disk full/i`

---

## Context Extraction

### Handling Nested Fields

**Problem**: Kubernetes metadata often nested in `resource_attributes.*`

**Correct syntax**: Quote fields with dots

```opal
# CORRECT
make_col namespace:string(resource_attributes."k8s.namespace.name"),
         pod:string(resource_attributes."k8s.pod.name"),
         node:string(resource_attributes."k8s.node.name")

# WRONG (will fail)
make_col namespace:resource_attributes.k8s.namespace.name
```

**Rule**: `object."field.with.dots"` - quote only the field name

### Common Nested Field Patterns

**Kubernetes**:
```opal
resource_attributes."k8s.namespace.name"
resource_attributes."k8s.pod.name"
resource_attributes."k8s.container.name"
resource_attributes."k8s.node.name"
resource_attributes."k8s.deployment.name"
```

**OpenTelemetry**:
```opal
resource_attributes."service.name"
resource_attributes."service.version"
resource_attributes."deployment.environment"
attributes."http.status_code"
attributes."db.name"
```

**CloudWatch**:
```opal
resource."aws.region"
resource."aws.account_id"
```

### Extracting Context Fields

**Template**:
```opal
make_col service:string(resource_attributes."service.name"),
         namespace:string(resource_attributes."k8s.namespace.name"),
         pod:string(resource_attributes."k8s.pod.name"),
         container:container,                    # Top-level field
         error_msg:body
```

**Type casting**: Use `string()` for nested variant/object fields

---

## Complete Examples

### Example 1: Top 10 Error Types in K8s Logs

**User question**: "Give me top 10 error types in Kubernetes container logs. Tell me which namespaces have most errors."

**Step 1: Discovery**
```python
discover_context("kubernetes logs")
# Result: Kubernetes Explorer/Kubernetes Logs (ID: 42161740)

discover_context(dataset_id="42161740")
# Fields: body (text), stream (string), namespace, pod, container
# Nested: resource_attributes.k8s.*
```

**Step 2: Query**
```opal
filter body ~ /error|exception|failed/i or stream = "stderr"
| make_col namespace:string(resource_attributes."k8s.namespace.name"),
          container,
          error_snippet:body
| statsby error_count:count(),
          sample_error:any(error_snippet),
          group_by(namespace, container)
| sort desc(error_count)
| limit 10
```

**Step 3: Result**
```
namespace   container                error_count  sample_error
default     opentelemetry-collector  1420         "Exporting failed..."
default     recommendationservice    118          "gRPC connection timeout"
observe     cluster-metrics          59           "Error translating metrics"
...
```

**Explanation**:
- Wide net filter catches text + stderr
- Extract namespace from nested field
- Count + sample message per group
- Sort by volume, limit to top 10

---

### Example 2: Recent Errors in Production Namespace

**User question**: "Show me recent errors from the production namespace in the last hour"

**Step 1: Query**
```opal
filter body ~ /error|exception/i or stream = "stderr"
| filter string(resource_attributes."k8s.namespace.name") = "production"
| make_col pod:string(resource_attributes."k8s.pod.name"),
          container,
          error_msg:body,
          error_time:format_time(timestamp, 'YYYY-MM-DD HH24:MI:SS')
| sort desc(timestamp)
| limit 20
```

**Step 2: Result**
```
pod                        container    error_time           error_msg
frontend-abc123           server       2025-11-14 17:45:32  "Error: RESOURCE_EXHAUSTED"
cartservice-def456        cart         2025-11-14 17:42:18  "Can't connect to redis:6379"
...
```

**Explanation**:
- Wide net filter for errors
- Second filter for specific namespace
- Format timestamp for readability
- Sort by time (most recent first)

---

### Example 3: Database Connection Errors

**User question**: "Find all database connection errors across all services"

**Step 1: Query**
```opal
filter body ~ /database.*error|db.*connection|postgres.*error|mysql.*failed/i
| make_col service:string(resource_attributes."service.name"),
          namespace:string(resource_attributes."k8s.namespace.name"),
          error_msg:body
| statsby error_count:count(),
          sample:any(error_msg),
          group_by(service, namespace)
| sort desc(error_count)
```

**Step 2: Result**
```
service          namespace   error_count  sample
payment-service  production  24           "PostgreSQL connection timeout to db:5432"
user-service     production  12           "MySQL error: Too many connections"
...
```

**Explanation**:
- Targeted regex for database-related errors
- Extract service and namespace context
- Count + sample per service
- Identify which services have DB issues

---

### Example 4: Error Volume Comparison

**User question**: "Compare error volumes between production and staging namespaces over the last 24 hours"

**Step 1: Query**
```opal
filter body ~ /error|exception|failed/i or stream = "stderr"
| make_col namespace:string(resource_attributes."k8s.namespace.name")
| filter namespace = "production" or namespace = "staging"
| timechart 1h, error_count:count(), group_by(namespace)
```

**Step 2: Result** (time-series)
```
_c_bucket              namespace    error_count
2025-11-13T18:00:00Z  production   342
2025-11-13T18:00:00Z  staging      89
2025-11-13T19:00:00Z  production   298
2025-11-13T19:00:00Z  staging      102
...
```

**Explanation**:
- Wide net error detection
- Filter to specific namespaces
- Time-series aggregation (hourly buckets)
- Compare error trends visually

---

### Example 5: Authentication Failures

**User question**: "Show me all authentication failures in the last hour"

**Step 1: Query**
```opal
filter body ~ /auth.*failed|unauthorized|403|401|authentication.*error/i
| make_col service:string(resource_attributes."service.name"),
          namespace:string(resource_attributes."k8s.namespace.name"),
          pod:string(resource_attributes."k8s.pod.name"),
          error_msg:body,
          error_time:format_time(timestamp, 'YYYY-MM-DD HH24:MI:SS')
| sort desc(timestamp)
| limit 50
```

**Step 2: Result**
```
service        namespace   pod              error_time           error_msg
api-gateway    production  api-gw-abc123   2025-11-14 17:52:14  "HTTP 401: Unauthorized"
auth-service   production  auth-xyz789     2025-11-14 17:48:32  "Auth failed: invalid token"
...
```

**Explanation**:
- Targeted regex for auth-related errors
- Full context extraction
- Recent errors first
- Higher limit (50) to catch patterns

---

## Common Pitfalls

### Pitfall 1: Using String Quotes for Regex

**WRONG**:
```opal
filter body ~ "error"           # String literal matching
filter body ~ "(?i)error"       # PCRE syntax not supported
filter body ~ "error|exception" # String matching, not regex alternation
```

**CORRECT**:
```opal
filter body ~ /error/           # Regex (case-sensitive)
filter body ~ /error/i          # Regex (case-insensitive)
filter body ~ /error|exception/ # Regex alternation
```

**Symptom**: Query returns 0 results or unexpected matches

**Fix**: Use forward slashes `/pattern/` for regex, NOT string quotes

---

### Pitfall 2: Not Quoting Nested Fields

**WRONG**:
```opal
make_col namespace:resource_attributes.k8s.namespace.name
```

**CORRECT**:
```opal
make_col namespace:string(resource_attributes."k8s.namespace.name")
```

**Symptom**: "Field not found" error

**Fix**: Quote field names with dots: `object."field.with.dots"`

---

### Pitfall 3: Assuming Field Names

**WRONG**:
```opal
# Assuming all logs have "message" field
filter message ~ /error/i
```

**CORRECT**:
```opal
# Check schema first!
# K8s logs use "body", CloudWatch uses "message"
discover_context(dataset_id="...")
# Then use correct field
filter body ~ /error/i
```

**Symptom**: "Column not found: message" error

**Fix**: ALWAYS run `discover_context(dataset_id="...")` to get exact field names

---

### Pitfall 4: Case-Sensitive Text Search

**WRONG**:
```opal
filter contains(body, "error")  # Misses "Error", "ERROR"
```

**CORRECT**:
```opal
# Option 1: Multiple contains
filter contains(body, "error") or contains(body, "ERROR") or contains(body, "Error")

# Option 2: Regex (better)
filter body ~ /error/i
```

**Symptom**: Missing errors that use different capitalization

**Fix**: Use regex with `/i` flag for case-insensitive matching

---

### Pitfall 5: Narrow Error Detection

**WRONG**:
```opal
filter stream = "stderr"  # Misses stdout errors
```

**CORRECT**:
```opal
filter body ~ /error|exception|failed/i
    or stream = "stderr"
```

**Symptom**: Missing errors that don't match single condition

**Fix**: Use wide net strategy - combine multiple error indicators

---

### Pitfall 6: Using statsby for Time-Series

**WRONG**:
```opal
# Trying to get hourly trends
filter body ~ /error/i
| statsby count(), group_by(namespace)  # Returns ONE row per namespace
```

**CORRECT**:
```opal
# Use timechart for time-series
filter body ~ /error/i
| timechart 1h, count(), group_by(namespace)  # Returns multiple rows (time buckets)
```

**Symptom**: Getting summary instead of trends

**Fix**: Use `timechart` for time-series, `statsby` for single summary

---

### Pitfall 7: Forgetting Type Casting

**WRONG**:
```opal
make_col namespace:resource_attributes."k8s.namespace.name"
# Might be variant type, causes issues in group_by
```

**CORRECT**:
```opal
make_col namespace:string(resource_attributes."k8s.namespace.name")
```

**Symptom**: Aggregation errors or unexpected grouping

**Fix**: Cast nested fields to expected type: `string()`, `int64()`, etc.

---

## Cross-References

### Related Skills

**filtering-event-datasets**:
- Basic filtering syntax (`contains()`, `~`, comparison operators)
- When to use `filter` vs aggregation
- Use for: Simple known-value filtering

**aggregating-event-datasets**:
- `statsby` for aggregations
- `make_col` for derived columns
- Aggregation functions (`count()`, `sum()`, `any()`)
- Use for: Counting, grouping, summarizing

**time-series-analysis**:
- `timechart` for temporal trending
- Time bucket configuration
- Use for: Error trends over time

**analyzing-apm-data**:
- Span-based error analysis (`error` field, `error_message`)
- Service-level error tracking
- Use for: APM/tracing error investigation

**aggregating-gauge-metrics**:
- Error count metrics (`error_count_5m`)
- Volume trending with metrics
- Use for: High-level error volume (fast)

---

### When to Use Which Skill

| User Question | Skill to Use | Why |
|---------------|--------------|-----|
| "Show me errors in K8s logs" | **investigating-textual-data** | Text search in logs |
| "What's the error rate for my service?" | **analyzing-apm-data** | APM metrics |
| "Count errors by service (metrics)" | **aggregating-gauge-metrics** | Pre-aggregated metrics |
| "Show error trends over 24h" | **time-series-analysis** | Time-series aggregation |
| "Filter logs for namespace=production" | **filtering-event-datasets** | Simple filtering |
| "Count errors by container" | **aggregating-event-datasets** | Event aggregation |

---

### Decision Matrix

```
User asks about errors
        |
        v
    From what source?
        |
    +---+---+---+
    |   |   |   |
Logs Spans Metrics No source specified
    |   |   |   |
    |   |   |   v
    |   |   |   Discover textual datasets
    |   |   |   (kubernetes logs, cloudwatch, etc.)
    |   |   |   |
    v   v   v   v
    |   |   |
Textual APM  Volume
investigation     |
    |   |        v
    |   |   aggregating-gauge-metrics
    |   |   (error_count_5m)
    |   |
    |   v
    | analyzing-apm-data
    | (spans, error field)
    |
    v
investigating-textual-data
(logs, events, regex, wide net)
```

---

## Summary

**Key Takeaways**:

1. **Always discover schema first** - Field names vary by dataset
2. **Use regex with `/pattern/i`** - Forward slashes, NOT string quotes
3. **Cast wide net** - Combine text patterns + severity + stream
4. **Quote nested fields** - `resource_attributes."k8s.namespace.name"`
5. **Sample with `any()`** - Get error counts WITH example messages
6. **Metrics vs logs** - Metrics for volume, logs for details
7. **`statsby` vs `timechart`** - Summary vs time-series

**Common workflow**:
```
1. discover_context("user intent keywords")
2. discover_context(dataset_id="...")  # Get schema
3. Write wide net filter (regex + severity + stream)
4. Extract context (namespace, service, pod)
5. Aggregate with samples (count + any())
6. Sort and limit results
```

**For more**:
- OPAL syntax → **filtering-event-datasets**
- Aggregations → **aggregating-event-datasets**
- Trends → **time-series-analysis**
- APM errors → **analyzing-apm-data**
- Pattern discovery → **analyzing-text-patterns**

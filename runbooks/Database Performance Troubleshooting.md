# Observe Troubleshooting Runbook: Database Performance Troubleshooting

Analyze database call performance and identify slow queries, connection pool issues, and database-related bottlenecks. Uses database call resources, service metrics, and span analysis to correlate application performance with database behavior.

**Investigation Context:** Database performance issues often manifest as increased application latency, timeouts, and resource contention. Common problems include inefficient queries lacking proper indexing, connection pool exhaustion under load, lock contention from concurrent operations, and resource constraints on database servers. Database issues can cascade to multiple application services, making them critical to identify quickly. Performance problems may be gradual (growing data volumes, query plan changes) or sudden (schema changes, index drops, parameter modifications). Distinguishing between application-side issues (connection management, query patterns) and database-side problems (server resources, storage I/O) is crucial for effective resolution.

**Key Investigation Areas:** Focus on query execution times, connection pool utilization, and database error patterns. Look for queries with dramatically increased execution time or frequency. Connection pool metrics reveal if applications are overwhelming database capacity. Examine lock wait times, deadlocks, and transaction durations for concurrency issues. Database server metrics (CPU, memory, disk I/O) help identify resource constraints. Compare current performance against historical baselines to detect gradual degradation. Check for recent schema changes, index modifications, or query plan updates that might impact performance. Transaction log growth and backup operations can also affect database responsiveness.

## Implementation Tasks

### Task 1: Assess Overall Database Performance Impact
- **Dataset**: ServiceExplorer/Service Metrics
- **Metrics to Query**: span_database_duration_5m, span_database_call_count_5m, span_database_error_count_5m
- **Analysis**: Calculate database operation latency percentiles and error rates across all services
- **Goal**: Establish scope of database performance impact and identify most affected services

### Task 2: Identify Slow Database Operations
- **Dataset**: ServiceExplorer/Database Call (Resource)
- **Cross-reference**: OpenTelemetry/Span
- **Analysis**: Find database operations with highest latency and execution time increases
- **Goal**: Pinpoint specific queries, tables, or operations causing performance bottlenecks

### Task 3: Analyze Database Connection Patterns
- **Dataset**: ServiceExplorer/Service Metrics
- **Metrics to Query**: span_database_call_count_5m, connection pool metrics
- **Analysis**: Examine connection usage patterns, pool exhaustion, and connection errors
- **Goal**: Identify if connection management issues are contributing to database performance problems

### Task 4: Correlate Database Performance with Service Latency
- **Dataset**: ServiceExplorer/Service Metrics
- **Analysis**: Compare span_database_duration_5m with overall span_duration_5m
- **Goal**: Determine what percentage of service latency is attributable to database operations

### Task 5: Examine Database Error Patterns and Types
- **Dataset**: Service Logs
- **Cross-reference**: ServiceExplorer/Service Metrics (span_database_error_count_5m)
- **Analysis**: Identify database error types (timeouts, connection failures, query errors)
- **Goal**: Understand the nature of database failures and their frequency patterns

### Task 6: Investigate Query-Level Performance
- **Dataset**: OpenTelemetry/Span
- **Analysis**: Examine database spans for query details, execution plans, and parameter patterns
- **Goal**: Identify specific queries or query patterns causing performance degradation

### Task 7: Check for Database Infrastructure Issues
- **Dataset**: Host Quickstart/Metrics
- **Focus**: Database server hosts
- **Analysis**: Examine CPU, memory, disk I/O, and network metrics on database servers
- **Goal**: Determine if database server resource constraints are causing performance issues

### Task 8: Analyze Concurrent Operations and Lock Contention
- **Dataset**: Service Logs
- **Cross-reference**: OpenTelemetry/Span
- **Analysis**: Look for lock wait times, deadlocks, and concurrent transaction patterns
- **Goal**: Identify if database concurrency issues are causing performance problems

### Task 9: Timeline Correlation with Database Changes
- **Dataset**: Service Logs
- **Analysis**: Check for recent schema changes, index modifications, or database configuration updates
- **Goal**: Determine if recent database changes triggered performance degradation

### Task 10: Generate Database Performance Assessment
- **Synthesis Task**: Correlate all database performance findings
- **Key Analysis**:
  - Primary performance bottlenecks (queries, connections, resources)
  - Impact on application services and user experience
  - Root cause identification (application vs database-side issues)
  - Performance trends and degradation patterns
- **Output**: Database performance optimization recommendations
- **Recommendations**: Immediate performance improvements and long-term database optimization strategies
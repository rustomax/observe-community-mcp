# Oberve Troubleshooting Runbook: Service Latency Investigation

Investigate elevated response times and performance degradation across services using distributed tracing, service metrics, and span analysis. This runbook helps identify bottlenecks in service-to-service communication, database queries, and external API calls by correlating OpenTelemetry traces with service metrics and deployment events.

**Investigation Context:** Service latency issues typically manifest as increased response times affecting user experience and system throughput. Common root causes include resource contention (CPU, memory, disk I/O), inefficient database queries, network connectivity problems, dependency failures, code regressions from recent deployments, and external service degradation. Latency can propagate through service dependencies, making it crucial to distinguish between symptoms and actual root causes.

**Key Investigation Areas:** Look for patterns in latency spikes - are they affecting all services uniformly (infrastructure issue) or specific services (application issue)? Examine if latency correlates with increased error rates, deployment timing, or resource utilization. Database operations are frequent culprits, especially slow queries, connection pool exhaustion, or deadlocks. External dependencies can introduce unpredictable latency, while service-to-service communication issues may indicate network problems or cascading failures. Recent code changes, configuration updates, or infrastructure modifications often coincide with performance degradation.

## Implementation Tasks:

### Task 1: Identify Affected Services and Establish Baseline
- **Dataset**: ServiceExplorer/Service Metrics
- **Metrics to Query**: span_duration_5m (p50, p95, p99 percentiles), span_call_count_5m
- **Analysis**: Compare current latency percentiles with 24h baseline for each service
- **Goal**: Establish which services show latency degradation and by how much

### Task 2: Calculate Error Rates and Service Health
- **Dataset**: ServiceExplorer/Service Metrics
- **Metrics to Query**: span_error_count_5m, span_call_count_5m
- **Analysis**: Calculate error rates per service and identify correlation with latency spikes
- **Goal**: Identify services with elevated error rates that correlate with latency issues

### Task 3: Analyze Service Dependency Impact
- **Dataset**: ServiceExplorer/Service Edge
- **Cross-reference**: ServiceExplorer/Service Map
- **Analysis**: Examine latency propagation through service communication paths
- **Goal**: Identify if latency is propagating through service dependencies and find upstream sources

### Task 4: Analyze Database Performance Impact
- **Dataset**: ServiceExplorer/Service Metrics
- **Metrics to Query**: span_database_duration_5m, span_database_call_count_5m, span_database_error_count_5m
- **Cross-reference**: ServiceExplorer/Database Call (Resource)
- **Goal**: Determine if database performance is contributing to service latency

### Task 5: Deep Dive into Distributed Traces
- **Dataset**: OpenTelemetry/Trace
- **Secondary Dataset**: OpenTelemetry/Span
- **Analysis**: Filter traces with duration > p95 baseline and examine span details
- **Goal**: Identify specific traces and transaction flows contributing to latency increase

### Task 6: Identify Slowest Spans and Operations
- **Dataset**: OpenTelemetry/Span
- **Analysis**: Analyze spans within slow traces to find bottleneck operations
- **Focus Areas**: Database operations, external API calls, internal service calls
- **Goal**: Pinpoint specific operations causing latency bottlenecks

### Task 7: Analyze External Service Dependencies
- **Dataset**: ServiceExplorer/External Service Call
- **Analysis**: Review response times, error rates, and timeout patterns for external dependencies
- **Goal**: Identify external dependencies causing latency issues

### Task 8: Check for Deployment Correlation
- **Dataset**: ServiceExplorer/Deployment
- **Analysis**: Correlate recent deployments with latency spike timing
- **Goal**: Determine if recent deployments contributed to latency issues

### Task 9: Resource Constraint Analysis
- **Dataset**: Host Quickstart/Metrics
- **Metrics to Query**: CPU, memory, disk I/O, network metrics for affected service hosts
- **Goal**: Identify infrastructure bottlenecks affecting service performance

### Task 10: Log Pattern Analysis for Errors
- **Primary Dataset**: Service Logs
- **Secondary Dataset**: OpenTelemetry/Span Event
- **Analysis**: Search for error patterns, timeouts, retries during latency period
- **Goal**: Correlate log events with performance degradation

### Task 11: Generate Root Cause Summary
- **Synthesis Task**: Correlate findings from all previous tasks
- **Key Correlations**: 
  - Deployment timing vs latency spikes
  - Resource constraints vs service performance  
  - External dependencies vs internal latency
  - Database performance vs overall service latency
  - Error rate patterns vs latency degradation
- **Output**: Prioritized list of probable root causes with supporting evidence
- **Recommendations**: Immediate mitigation steps and long-term fixes
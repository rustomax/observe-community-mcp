# Observe Troubleshooting Runbook: Service Error Rate Spike Investigation

Investigate sudden increases in service error rates by correlating service logs, span events, and service metrics. This runbook helps identify whether errors are isolated to specific endpoints, caused by deployment changes, or result from external dependencies failing.

**Investigation Context:** Error rate spikes can indicate various underlying issues from code bugs and configuration errors to infrastructure failures and dependency problems. The key is determining whether errors represent new failures, increased load exposing existing weaknesses, or cascading effects from upstream issues. Error patterns often reveal the root cause: uniform error increases suggest infrastructure or deployment issues, while endpoint-specific errors point to code problems. Timing correlation with deployments, traffic spikes, or external events provides crucial context. Some errors may be expected during auto-scaling or failover scenarios, while others indicate genuine system problems requiring immediate attention.

**Key Investigation Areas:** Examine error types and HTTP status codes to understand failure modes - 5xx errors typically indicate server-side issues while 4xx errors suggest client or configuration problems. Look for error clustering by service, endpoint, or user segment. Database connection errors, timeout exceptions, and circuit breaker activations often signal infrastructure problems. Compare error rates against normal baselines and traffic volume to determine if errors are proportional to load. Check if errors correlate with specific deployments, configuration changes, or external service degradation. Memory leaks, resource exhaustion, and dependency failures often manifest as gradual error rate increases.

## Implementation Tasks:

### Task 1: Quantify Error Rate Increase and Affected Services
- **Dataset**: ServiceExplorer/Service Metrics
- **Metrics to Query**: span_error_count_5m, span_call_count_5m
- **Analysis**: Calculate current vs. baseline error rates for all services to identify most affected services
- **Goal**: Establish scope and severity of error rate spike across the service ecosystem

### Task 2: Analyze Error Types and HTTP Status Patterns
- **Dataset**: ServiceExplorer/Service Metrics
- **Cross-reference**: Service Logs
- **Metrics to Query**: span_error_count_with_status_5m, status_code patterns
- **Analysis**: Break down errors by HTTP status codes (4xx vs 5xx) and error types
- **Goal**: Understand the nature of failures and distinguish client vs server-side issues

### Task 3: Correlate Error Spikes with Traffic Volume
- **Dataset**: ServiceExplorer/Service Metrics
- **Metrics to Query**: span_call_count_5m, span_error_count_5m over time
- **Analysis**: Determine if error increases are proportional to traffic increases or represent degraded service quality
- **Goal**: Identify whether errors are load-related or indicative of actual service degradation

### Task 4: Investigate Endpoint-Specific Error Patterns
- **Dataset**: OpenTelemetry/Span
- **Cross-reference**: Service Logs
- **Analysis**: Examine error distribution across different endpoints and operations
- **Goal**: Determine if errors are concentrated in specific operations or spread across all functionality

### Task 5: Timeline Correlation with Deployments and Changes
- **Dataset**: ServiceExplorer/Deployment
- **Cross-reference**: Service Logs for configuration changes
- **Analysis**: Correlate error spike timing with recent deployments, configuration updates, or infrastructure changes
- **Goal**: Identify if recent changes triggered the error increase

### Task 6: Analyze Database and External Dependency Errors
- **Dataset**: ServiceExplorer/Service Metrics
- **Cross-reference**: ServiceExplorer/External Service Call
- **Metrics to Query**: span_database_error_count_5m, external service response codes
- **Analysis**: Examine database connection errors, query failures, and external service error responses
- **Goal**: Determine if errors originate from data layer or external dependency issues

### Task 7: Examine Error Logs for Exception Patterns
- **Dataset**: Service Logs
- **Secondary Dataset**: OpenTelemetry/Span Event
- **Analysis**: Search for specific exception types, stack traces, and error messages
- **Goal**: Identify common error patterns and root cause indicators in application logs

### Task 8: Check Infrastructure and Resource Constraints
- **Dataset**: Host Quickstart/Metrics
- **Cross-reference**: Kubernetes Explorer/Kubernetes Logs
- **Analysis**: Examine resource utilization, OOM kills, and infrastructure events during error spike
- **Goal**: Determine if infrastructure constraints are causing service failures

### Task 9: Investigate User and Request Context
- **Dataset**: CDP/User Session
- **Cross-reference**: Service Logs
- **Analysis**: Analyze if errors affect specific user segments, geographic regions, or request types
- **Goal**: Understand if errors have user-facing impact patterns or are randomly distributed

### Task 10: Generate Error Spike Root Cause Analysis
- **Synthesis Task**: Correlate all error patterns and findings
- **Key Analysis**:
  - Primary error types and their distribution across services
  - Timeline correlation with deployments, traffic, and infrastructure events
  - Affected user segments and business impact assessment
  - Error propagation patterns through service dependencies
- **Output**: Root cause identification and error spike characterization
- **Recommendations**: Immediate error mitigation strategies and preventive measures
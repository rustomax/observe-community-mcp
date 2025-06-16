# Observe Troubleshooting Runbook: Service Dependency Mapping & Root Cause Analysis

Analyze service dependencies and communication patterns to identify cascade failures and upstream/downstream impact analysis. Uses service maps, service edges, and trace correlation to understand how failures propagate through the system architecture and pinpoint the original source of issues.

**Investigation Context:** Modern microservices architectures create complex dependency webs where failures in one service can cascade to multiple downstream services, making root cause identification challenging. The key is distinguishing between the original failing service and services experiencing secondary effects. Common patterns include upstream service failures causing timeouts in dependent services, shared resource contention affecting multiple services simultaneously, and circuit breaker activations that can mask the true source of problems. Database or cache failures often impact multiple services, while network partitions can isolate service clusters.

**Key Investigation Areas:** Focus on identifying the temporal sequence of failures - which service failed first and how the failure propagated. Look for services with high fanout (many dependents) as they can cause widespread impact, and services with high fan-in (many dependencies) as they're vulnerable to cascade failures. Examine service communication patterns for bottlenecks, retry storms, and timeout configurations. Pay attention to shared infrastructure components like databases, message queues, and external APIs that can be single points of failure. Circuit breaker states, connection pool exhaustion, and retry behavior often provide clues about the failure propagation mechanism.

## Implementation Tasks:

### Task 1: Map Current Service Dependencies
- **Dataset**: ServiceExplorer/Service Map
- **Cross-reference**: ServiceExplorer/Service Edge
- **Analysis**: Identify all service-to-service communication patterns and dependency relationships
- **Goal**: Create a comprehensive view of the service architecture and communication flows

### Task 2: Identify Services with Unusual Communication Patterns
- **Dataset**: ServiceExplorer/Service Edge
- **Metrics to Query**: Call volume, response times, error rates between service pairs
- **Analysis**: Look for spikes in call volume, increased latency, or elevated errors in service communication
- **Goal**: Pinpoint abnormal service interactions that may indicate propagating issues

### Task 3: Analyze Service Health Across the Dependency Chain
- **Dataset**: ServiceExplorer/Service Metrics
- **Metrics to Query**: span_error_count_5m, span_call_count_5m, span_duration_5m for all services
- **Analysis**: Calculate error rates and latency for each service to identify the healthiest vs. most impacted services
- **Goal**: Establish service health baseline and identify services showing degradation

### Task 4: Trace Timeline Analysis for Failure Propagation
- **Dataset**: OpenTelemetry/Trace
- **Secondary Dataset**: OpenTelemetry/Span
- **Analysis**: Examine trace timestamps to determine failure sequence and propagation timing
- **Goal**: Establish the chronological order of service failures and identify the initial failure point

### Task 5: Investigate High-Impact Service Failures
- **Dataset**: ServiceExplorer/Service Metrics
- **Focus**: Services with high fanout (many dependent services)
- **Analysis**: Prioritize investigation of services that have many downstream dependencies
- **Goal**: Identify if failures in critical services are causing widespread cascade effects

### Task 6: Analyze Shared Resource Dependencies
- **Dataset**: ServiceExplorer/Database Call (Resource)
- **Cross-reference**: ServiceExplorer/External Service Call
- **Analysis**: Examine shared databases, caches, and external services for performance issues
- **Goal**: Identify shared infrastructure components that could be causing multiple service failures

### Task 7: Examine Circuit Breaker and Retry Patterns
- **Dataset**: Service Logs
- **Secondary Dataset**: OpenTelemetry/Span Event
- **Analysis**: Look for circuit breaker activations, retry attempts, and timeout patterns
- **Goal**: Understand how service resilience patterns are responding to failures

### Task 8: Correlate with Infrastructure Events
- **Dataset**: Host Quickstart/Metrics
- **Cross-reference**: Kubernetes Explorer/Kubernetes Logs
- **Analysis**: Check for infrastructure events that could trigger cascade failures
- **Goal**: Determine if infrastructure issues are the root cause of service dependency failures

### Task 9: Identify Bottleneck Services and Communication Paths
- **Dataset**: ServiceExplorer/Service Edge
- **Analysis**: Find services or communication paths with disproportionately high load or latency
- **Goal**: Locate architectural bottlenecks that could cause widespread system impact

### Task 10: Generate Dependency Impact Analysis
- **Synthesis Task**: Correlate all findings to create dependency failure timeline
- **Key Analysis**: 
  - Identify the root cause service and failure initiation time
  - Map the failure propagation path through service dependencies
  - Assess the blast radius and affected service count
  - Determine if failures are active cascades or resolved but showing lingering effects
- **Output**: Root cause service identification and comprehensive impact assessment
- **Recommendations**: Immediate containment strategies and architectural improvements to prevent future cascades
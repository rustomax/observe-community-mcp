# Observe Troubleshooting Runbook: General System Health & Root Cause Analysis

Comprehensive investigation runbook for situations where the specific problem type is unclear or when no specialized runbook matches the issue. This general-purpose approach systematically examines all major system components to identify signs of unhealthiness and track down root causes through systematic elimination and correlation analysis.

**Investigation Context:** When facing ambiguous system issues, unknown performance degradation, or complex multi-system problems, a systematic approach across all observability signals is essential. This runbook assumes no prior knowledge of the problem domain and methodically examines service health, infrastructure status, dependencies, and user impact. The goal is to quickly identify the most significant anomalies and narrow down investigation scope. Common scenarios include vague user complaints about "slowness," unexplained system behavior, intermittent issues that don't fit clear patterns, or situations where multiple symptoms suggest complex underlying problems requiring broad investigation before focusing on specific areas.

**Key Investigation Areas:** Start with high-level system health indicators before drilling down into specifics. Look for correlations across different system layers - services, infrastructure, dependencies, and user experience. Identify temporal patterns that might indicate triggers like deployments, traffic changes, or external events. Examine error rates, latency patterns, resource utilization, and throughput metrics across all services. Compare current behavior against historical baselines to detect deviations. Focus on finding the most significant anomalies first, then use dependency mapping to understand impact scope. Look for common failure patterns like resource exhaustion, cascade failures, external dependency issues, or recent changes that correlate with problem onset.

## Implementation Tasks

### Task 1: Overall System Health Assessment
- **Dataset**: ServiceExplorer/Service Metrics
- **Metrics to Query**: span_error_count_5m, span_call_count_5m, span_duration_5m across all services
- **Analysis**: Calculate error rates, latency percentiles, and throughput for all services to identify most impacted areas
- **Goal**: Establish broad system health baseline and identify services showing the most significant anomalies

### Task 2: Infrastructure Resource Health Check
- **Dataset**: Host Quickstart/Metrics
- **Cross-reference**: Kubernetes Explorer/Prometheus Metrics
- **Analysis**: Examine CPU, memory, disk, and network utilization across all infrastructure components
- **Goal**: Identify resource constraints or infrastructure issues that could be causing system-wide problems

### Task 3: Recent Change Correlation Analysis
- **Dataset**: ServiceExplorer/Deployment
- **Cross-reference**: Kubernetes Explorer/Kubernetes Logs
- **Analysis**: Identify recent deployments, configuration changes, or infrastructure modifications within problem timeframe
- **Goal**: Determine if recent changes correlate with the onset of system issues

### Task 4: Service Dependency Impact Mapping
- **Dataset**: ServiceExplorer/Service Map
- **Cross-reference**: ServiceExplorer/Service Edge
- **Analysis**: Map service dependencies and identify high-impact services that could cause widespread issues
- **Goal**: Understand potential cascade failure paths and prioritize investigation of critical services

### Task 5: Error Pattern and Anomaly Detection
- **Dataset**: Service Logs
- **Cross-reference**: OpenTelemetry/Span Event
- **Analysis**: Search for unusual error patterns, exception spikes, or log anomalies across all services
- **Goal**: Identify specific error types or patterns that might indicate the root cause category

### Task 6: External Dependency Health Check
- **Dataset**: ServiceExplorer/External Service Call
- **Analysis**: Examine response times, error rates, and availability of external services and APIs
- **Goal**: Determine if external dependency issues are causing internal system problems

### Task 7: Database and Data Layer Investigation
- **Dataset**: ServiceExplorer/Service Metrics
- **Cross-reference**: ServiceExplorer/Database Call (Resource)
- **Metrics to Query**: span_database_duration_5m, span_database_error_count_5m
- **Analysis**: Check database performance and data layer health across all services
- **Goal**: Identify if data layer issues are contributing to system problems

### Task 8: User Experience and Traffic Pattern Analysis
- **Dataset**: CDP/User Session
- **Cross-reference**: ServiceExplorer/Service Metrics
- **Analysis**: Examine user session patterns, geographic distribution, and user-facing error rates
- **Goal**: Understand user impact and identify if issues affect specific user segments or are system-wide

### Task 9: Timeline and Trend Analysis
- **Datasets**: All previous datasets with historical comparison
- **Analysis**: Compare current metrics against 24h, 7d, and 30d historical patterns to identify trend deviations
- **Goal**: Distinguish between gradual degradation and sudden onset issues, identify cyclical patterns

### Task 10: Cross-System Correlation and Root Cause Synthesis
- **Synthesis Task**: Correlate findings from all previous tasks
- **Key Analysis**:
  - Identify the most significant anomalies and their temporal relationships
  - Map dependency relationships to understand impact propagation
  - Correlate infrastructure, service, and user-facing symptoms
  - Determine primary vs secondary effects
  - Establish timeline of issue progression
- **Output**: Root cause hypothesis with supporting evidence and recommended next steps
- **Recommendations**: 
  - Immediate stabilization actions for most critical issues
  - Specific focused runbook recommendations for deeper investigation
  - Monitoring enhancements to prevent similar issues
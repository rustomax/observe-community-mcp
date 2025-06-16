# Observe Troubleshooting Runbook: Kubernetes Cluster Health Assessment

Comprehensive analysis of Kubernetes cluster health including pod restarts, resource constraints, node issues, and scheduling problems. Uses Kubernetes logs, metrics, and entity data to identify cluster-wide issues and resource allocation problems.

**Investigation Context:** Kubernetes clusters are complex orchestration environments where issues can manifest at multiple layers - nodes, pods, containers, networking, and storage. Common problems include resource exhaustion causing pod evictions, node failures leading to service disruption, misconfigured resource requests/limits causing scheduling issues, and networking problems preventing inter-pod communication. Cluster health issues often cascade, where node problems cause pod rescheduling, leading to resource pressure on remaining nodes. Understanding the relationship between cluster infrastructure health and application performance is crucial for maintaining service reliability.

**Key Investigation Areas:** Focus on cluster-wide patterns rather than individual pod issues - look for nodes with high resource utilization, frequent pod restarts across multiple services, or scheduling failures indicating resource constraints. Examine the health of cluster components like the API server, etcd, and networking plugins. Pod lifecycle events reveal scheduling problems, resource limits, and container failures. Node conditions and taints indicate infrastructure issues. Network policies and service mesh configurations can cause connectivity problems. Storage issues may manifest as persistent volume mounting failures or performance degradation.

## Implementation Tasks

### Task 1: Assess Overall Cluster Resource Utilization
- **Dataset**: Kubernetes Explorer/Prometheus Metrics
- **Metrics to Query**: Node CPU/memory utilization, pod resource consumption, cluster capacity
- **Analysis**: Identify nodes approaching resource limits and overall cluster resource pressure
- **Goal**: Establish cluster-wide resource health and identify capacity constraints

### Task 2: Analyze Pod Restart and Failure Patterns
- **Dataset**: Kubernetes Explorer/Kubernetes Logs
- **Cross-reference**: Kubernetes Explorer/Kubernetes Entity
- **Analysis**: Examine pod restart frequencies, failure reasons, and affected namespaces/services
- **Goal**: Identify services experiencing instability and underlying causes of pod failures

### Task 3: Investigate Node Health and Availability
- **Dataset**: Kubernetes Explorer/Prometheus Metrics
- **Cross-reference**: Host Quickstart/Metrics
- **Analysis**: Check node conditions, resource utilization, and availability status
- **Goal**: Identify problematic nodes that may be causing service disruption

### Task 4: Examine Pod Scheduling and Resource Constraints
- **Dataset**: Kubernetes Explorer/Kubernetes Logs
- **Analysis**: Look for scheduling failures, resource quota violations, and unschedulable pods
- **Goal**: Identify resource allocation problems preventing proper pod scheduling

### Task 5: Analyze Container Resource Limits and Requests
- **Dataset**: Kubernetes Explorer/Prometheus Metrics
- **Analysis**: Compare actual resource usage against configured requests and limits
- **Goal**: Identify misconfigured resource specifications causing performance issues or waste

### Task 6: Investigate Cluster Component Health
- **Dataset**: Kubernetes Explorer/Kubernetes Logs
- **Focus**: API server, etcd, controller manager, scheduler logs
- **Analysis**: Check for errors, latency issues, or availability problems in cluster components
- **Goal**: Ensure cluster control plane is healthy and functioning properly

### Task 7: Examine Network Connectivity and Service Discovery
- **Dataset**: Kubernetes Explorer/Kubernetes Logs
- **Cross-reference**: ServiceExplorer/Service Edge
- **Analysis**: Look for DNS resolution failures, service connectivity issues, and network policy problems
- **Goal**: Identify network-related issues affecting inter-service communication

### Task 8: Analyze Storage and Persistent Volume Issues
- **Dataset**: Kubernetes Explorer/Kubernetes Logs
- **Analysis**: Check for persistent volume mounting failures, storage class issues, and disk space problems
- **Goal**: Identify storage-related constraints affecting application functionality

### Task 9: Correlate Cluster Events with Service Performance
- **Dataset**: ServiceExplorer/Service Metrics
- **Cross-reference**: Kubernetes Explorer/Kubernetes Logs
- **Analysis**: Connect Kubernetes events with service latency and error rate changes
- **Goal**: Understand how cluster health impacts application service performance

### Task 10: Generate Cluster Health Assessment
- **Synthesis Task**: Correlate all cluster health findings
- **Key Analysis**:
  - Critical cluster components and node health status
  - Resource allocation efficiency and capacity planning needs
  - Pod stability patterns and failure root causes
  - Network and storage infrastructure health
- **Output**: Comprehensive cluster health report with priority issues
- **Recommendations**: Immediate cluster stabilization actions and long-term optimization strategies
"""
OPAL query templates for different complexity levels and analysis types.

Provides sophisticated query patterns that match the complexity needed for different
types of observability analysis.
"""

from typing import Dict, List, Optional
from dataclasses import dataclass
import re


@dataclass
class QueryTemplate:
    name: str
    complexity: str  # "simple", "analytical", "advanced"
    intent: str      # "error_analysis", "performance_analysis", etc.
    opal_template: str
    required_fields: List[str]
    description: str


class QueryComplexityDetector:
    """
    Detects the complexity level needed for a user query and suggests appropriate templates.
    """
    
    def __init__(self):
        # Complexity indicators
        self.complexity_patterns = {
            "simple": {
                "keywords": ["show", "list", "display", "get", "find"],
                "patterns": ["show me", "list all", "display the", "get all"],
                "max_conditions": 1
            },
            "analytical": {
                "keywords": ["rate", "percentage", "trend", "pattern", "analyze", "compare"],
                "patterns": ["error rate", "success rate", "percentage", "trends over", "compared to"],
                "calculations": ["rate", "ratio", "percent", "average", "median"]
            },
            "advanced": {
                "keywords": ["correlation", "investigate", "drill down", "root cause", "anomaly"],
                "patterns": ["correlate with", "investigate", "deep dive", "anomaly detection"],
                "multi_step": True
            }
        }
        
        # Query templates organized by intent and complexity
        self.templates = {
            "error_analysis": {
                "simple": QueryTemplate(
                    name="basic_error_count",
                    complexity="simple", 
                    intent="error_analysis",
                    opal_template="filter {error_condition} | statsby error_count:count(), group_by({group_field})",
                    required_fields=["error", "service_name"],
                    description="Basic error counting grouped by service"
                ),
                "analytical": QueryTemplate(
                    name="error_rate_analysis",
                    complexity="analytical",
                    intent="error_analysis", 
                    opal_template="statsby error_rate:avg(if({error_field}, 1.0, 0.0)), total_requests:count(), error_count:sum(if({error_field}, 1, 0)), group_by({group_field}) | sort desc(error_rate)",
                    required_fields=["error", "service_name"],
                    description="Calculate error rates with total context"
                ),
                "advanced": QueryTemplate(
                    name="error_pattern_analysis",
                    complexity="advanced",
                    intent="error_analysis",
                    opal_template="filter {error_condition} | statsby error_rate:avg(if({error_field}, 1.0, 0.0)), p95_duration:percentile({duration_field}, 0.95), error_patterns:count(), group_by({group_field}, {status_field}) | make_col severity:if(error_rate > 0.1, \"critical\", if(error_rate > 0.05, \"high\", \"medium\")) | sort desc(error_rate)",
                    required_fields=["error", "service_name", "duration", "status_code"],
                    description="Advanced error analysis with severity classification"
                )
            },
            "performance_analysis": {
                "simple": QueryTemplate(
                    name="basic_performance",
                    complexity="simple",
                    intent="performance_analysis",
                    opal_template="statsby avg_duration:avg({duration_field}), request_count:count(), group_by({group_field})",
                    required_fields=["duration", "service_name"],
                    description="Basic performance metrics by service"
                ),
                "analytical": QueryTemplate(
                    name="latency_percentiles",
                    complexity="analytical", 
                    intent="performance_analysis",
                    opal_template="statsby avg_duration:avg({duration_field}), p50:percentile({duration_field}, 0.5), p95:percentile({duration_field}, 0.95), p99:percentile({duration_field}, 0.99), request_count:count(), group_by({group_field}) | make_col performance_tier:if(p95 > {slow_threshold}, \"slow\", if(p95 > {medium_threshold}, \"medium\", \"fast\")) | sort desc(p95)",
                    required_fields=["duration", "service_name"],
                    description="Comprehensive latency analysis with performance tiers"
                ),
                "advanced": QueryTemplate(
                    name="performance_correlation",
                    complexity="advanced",
                    intent="performance_analysis", 
                    opal_template="filter {duration_field} > {threshold} | statsby slow_requests:count(), avg_duration:avg({duration_field}), error_rate:avg(if({error_field}, 1.0, 0.0)), group_by({group_field}) | make_col correlation_score:if(error_rate > 0.1 and avg_duration > {slow_threshold}, \"high_correlation\", \"low_correlation\") | sort desc(avg_duration)",
                    required_fields=["duration", "error", "service_name"],
                    description="Correlate performance issues with error rates"
                )
            },
            "time_series": {
                "simple": QueryTemplate(
                    name="basic_timeseries",
                    complexity="simple",
                    intent="time_series",
                    opal_template="timechart {interval}, request_count:count(), group_by({group_field})",
                    required_fields=["timestamp", "service_name"],
                    description="Basic time series visualization"
                ),
                "analytical": QueryTemplate(
                    name="trend_analysis",
                    complexity="analytical",
                    intent="time_series",
                    opal_template="timechart {interval}, request_count:count(), error_count:sum(if({error_field}, 1, 0)), avg_duration:avg({duration_field}), group_by({group_field})",
                    required_fields=["timestamp", "error", "duration", "service_name"], 
                    description="Multi-metric time series with trends"
                )
            },
            "log_analysis": {
                "simple": QueryTemplate(
                    name="basic_log_search",
                    complexity="simple",
                    intent="log_analysis",
                    opal_template="filter {message_field} ~ /{pattern}/ | limit {limit}",
                    required_fields=["body", "message"],
                    description="Basic log pattern matching"
                ),
                "analytical": QueryTemplate(
                    name="log_pattern_analysis", 
                    complexity="analytical",
                    intent="log_analysis",
                    opal_template="filter {message_field} ~ /{pattern}/ | statsby message_count:count(), group_by({group_field}) | sort desc(message_count) | limit {limit}",
                    required_fields=["body", "service_name"],
                    description="Analyze log patterns with frequency analysis"
                )
            }
        }
    
    def detect_complexity(self, user_query: str) -> str:
        """
        Detect the complexity level needed for a user query.
        
        Returns: "simple", "analytical", or "advanced"
        """
        query_lower = user_query.lower()
        
        # Check for advanced patterns first
        advanced_patterns = self.complexity_patterns["advanced"]
        if any(keyword in query_lower for keyword in advanced_patterns["keywords"]):
            return "advanced"
        if any(pattern in query_lower for pattern in advanced_patterns["patterns"]):
            return "advanced"
        
        # Check for analytical patterns
        analytical_patterns = self.complexity_patterns["analytical"]
        if any(keyword in query_lower for keyword in analytical_patterns["keywords"]):
            return "analytical"
        if any(pattern in query_lower for pattern in analytical_patterns["patterns"]):
            return "analytical"
        if any(calc in query_lower for calc in analytical_patterns["calculations"]):
            return "analytical"
        
        # Check for percentage/rate indicators
        if any(indicator in query_lower for indicator in ["rate", "percentage", "percent", "%", "ratio"]):
            return "analytical"
        
        # Default to simple
        return "simple"
    
    def get_template(self, intent: str, complexity: str) -> Optional[QueryTemplate]:
        """
        Get the appropriate query template for given intent and complexity.
        """
        if intent in self.templates and complexity in self.templates[intent]:
            return self.templates[intent][complexity]
        
        # Fallback to simpler complexity
        if intent in self.templates:
            if "simple" in self.templates[intent]:
                return self.templates[intent]["simple"]
        
        return None
    
    def fill_template(self, template: QueryTemplate, field_mapping: Dict[str, str], 
                     parameters: Dict[str, str] = None) -> str:
        """
        Fill a query template with actual field names and parameters.
        
        Args:
            template: The query template to fill
            field_mapping: Mapping of template fields to actual dataset fields
            parameters: Additional parameters like thresholds, intervals, etc.
        """
        opal_query = template.opal_template
        
        # Default parameters
        default_params = {
            "interval": "5m",
            "limit": "50", 
            "slow_threshold": "5000000000",  # 5 seconds in nanoseconds
            "medium_threshold": "1000000000",  # 1 second in nanoseconds
            "threshold": "1000000000"  # 1 second in nanoseconds
        }
        
        if parameters:
            default_params.update(parameters)
        
        # Replace field placeholders
        for template_field, actual_field in field_mapping.items():
            opal_query = opal_query.replace("{" + template_field + "}", actual_field)
        
        # Replace parameter placeholders
        for param_name, param_value in default_params.items():
            opal_query = opal_query.replace("{" + param_name + "}", str(param_value))
        
        return opal_query


# Example usage and testing
if __name__ == "__main__":
    detector = QueryComplexityDetector()
    
    test_queries = [
        ("Show me all errors", "simple"),
        ("Calculate error rates by service", "analytical"), 
        ("Show error rate percentages with trends", "analytical"),
        ("Investigate correlation between latency and errors", "advanced"),
        ("Find slow requests over 2 seconds", "simple"),
        ("Analyze performance trends and calculate percentiles", "analytical")
    ]
    
    for query, expected in test_queries:
        detected = detector.detect_complexity(query)
        status = "✅" if detected == expected else "❌"
        print(f"{status} '{query}' -> {detected} (expected: {expected})")
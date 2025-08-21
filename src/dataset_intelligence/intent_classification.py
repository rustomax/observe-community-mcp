"""
Intent-based dataset selection for improved NLP query accuracy.

Analyzes user requests to classify intent and match with appropriate dataset types.
"""

import re
from typing import Dict, List, Set, Optional
from dataclasses import dataclass


@dataclass
class QueryIntent:
    primary: str
    secondary: List[str]
    required_fields: List[str]
    preferred_dataset_types: List[str]
    confidence: float


class IntentClassifier:
    """
    Classifies user query intent to improve dataset selection accuracy.
    """
    
    def __init__(self):
        # Intent patterns with field requirements and dataset preferences
        self.intent_patterns = {
            "error_analysis": {
                "keywords": ["error", "errors", "exception", "failure", "failed", "fault"],
                "phrases": ["error rate", "error pattern", "error count", "failure rate"],
                "required_fields": ["error", "status_code", "exception", "failed", "status"],
                "preferred_types": ["trace", "event"],
                "weight": 1.0
            },
            "performance_analysis": {
                "keywords": ["slow", "latency", "duration", "performance", "response time", "speed"],
                "phrases": ["slow traces", "high latency", "response time", "performance issue"],
                "required_fields": ["duration", "response_time", "latency", "elapsed_time"],
                "preferred_types": ["trace", "metric"],
                "weight": 1.0
            },
            "service_metrics": {
                "keywords": ["service", "services", "microservice", "application"],
                "phrases": ["by service", "service breakdown", "service performance"],
                "required_fields": ["service_name", "for_service_name", "service"],
                "preferred_types": ["metric", "trace", "event"],
                "weight": 0.8
            },
            "log_analysis": {
                "keywords": ["log", "logs", "message", "messages", "pattern"],
                "phrases": ["log pattern", "log message", "error message"],
                "required_fields": ["body", "message", "log", "content"],
                "preferred_types": ["log", "event"],
                "weight": 0.9
            },
            "time_series": {
                "keywords": ["over time", "trend", "trends", "timeline", "interval"],
                "phrases": ["over time", "time series", "trends over", "patterns over time"],
                "required_fields": ["timestamp", "time", "_time"],
                "preferred_types": ["metric", "event"],
                "weight": 0.7
            },
            "resource_analysis": {
                "keywords": ["cpu", "memory", "disk", "pod", "container", "node"],
                "phrases": ["resource usage", "pod performance", "container metrics"],
                "required_fields": ["cpu", "memory", "pod_name", "container"],
                "preferred_types": ["metric", "resource"],
                "weight": 0.8
            }
        }
    
    def classify_intent(self, user_query: str) -> QueryIntent:
        """
        Analyze user query and classify intent with confidence scoring.
        """
        query_lower = user_query.lower()
        intent_scores = {}
        
        for intent_name, pattern in self.intent_patterns.items():
            score = 0.0
            
            # Keyword matching
            keyword_matches = sum(1 for keyword in pattern["keywords"] if keyword in query_lower)
            score += keyword_matches * 10
            
            # Phrase matching (higher weight)
            phrase_matches = sum(1 for phrase in pattern["phrases"] if phrase in query_lower)
            score += phrase_matches * 25
            
            # Apply pattern weight
            score *= pattern["weight"]
            
            intent_scores[intent_name] = score
        
        # Find primary intent
        if not intent_scores or max(intent_scores.values()) == 0:
            return QueryIntent(
                primary="general_query",
                secondary=[],
                required_fields=[],
                preferred_dataset_types=["event", "metric"],
                confidence=0.5
            )
        
        # Sort by score
        sorted_intents = sorted(intent_scores.items(), key=lambda x: x[1], reverse=True)
        primary_intent = sorted_intents[0][0]
        primary_score = sorted_intents[0][1]
        
        # Find secondary intents (score > 0 and within 50% of primary)
        threshold = primary_score * 0.5
        secondary_intents = [
            intent for intent, score in sorted_intents[1:] 
            if score > 0 and score >= threshold
        ]
        
        # Combine requirements from primary and secondary intents
        all_intents = [primary_intent] + secondary_intents
        required_fields = []
        preferred_types = []
        
        for intent in all_intents:
            if intent in self.intent_patterns:
                required_fields.extend(self.intent_patterns[intent]["required_fields"])
                preferred_types.extend(self.intent_patterns[intent]["preferred_types"])
        
        # Remove duplicates while preserving order
        required_fields = list(dict.fromkeys(required_fields))
        preferred_types = list(dict.fromkeys(preferred_types))
        
        # Calculate confidence (normalized to 0-1)
        confidence = min(primary_score / 50.0, 1.0)  # 50 points = 100% confidence
        
        return QueryIntent(
            primary=primary_intent,
            secondary=secondary_intents,
            required_fields=required_fields,
            preferred_dataset_types=preferred_types,
            confidence=confidence
        )


class DatasetScorer:
    """
    Scores datasets based on query intent and field requirements.
    """
    
    def score_dataset_for_intent(
        self, 
        dataset: Dict, 
        intent: QueryIntent, 
        schema_fields: Optional[List[str]] = None
    ) -> float:
        """
        Calculate a relevance score for a dataset given a query intent.
        
        Args:
            dataset: Dataset metadata including name, description, etc.
            intent: Classified query intent with field requirements
            schema_fields: Available fields in the dataset (if known)
            
        Returns:
            Relevance score (0-100, higher is better)
        """
        score = 0.0
        
        # Base semantic similarity score (from existing search)
        if "similarity_score" in dataset:
            score += dataset["similarity_score"] * 30  # Max 30 points
        
        # Dataset type matching
        dataset_type = self._extract_dataset_type(dataset)
        if dataset_type in intent.preferred_dataset_types:
            score += 25  # High weight for type match
        
        # Field availability scoring
        if schema_fields:
            available_fields = set(f.lower() for f in schema_fields)
            required_fields = set(f.lower() for f in intent.required_fields)
            
            # Field match ratio
            if required_fields:
                match_ratio = len(required_fields.intersection(available_fields)) / len(required_fields)
                score += match_ratio * 30  # Max 30 points for perfect field match
        
        # Business category bonus
        if "business_category" in dataset:
            category = dataset["business_category"].lower()
            if intent.primary == "error_analysis" and "application" in category:
                score += 10
            elif intent.primary == "resource_analysis" and "infrastructure" in category:
                score += 10
        
        # Technical category bonus  
        if "technical_category" in dataset:
            tech_category = dataset["technical_category"].lower()
            if intent.primary == "time_series" and "metrics" in tech_category:
                score += 5
            elif intent.primary == "log_analysis" and "events" in tech_category:
                score += 5
        
        # Apply confidence weighting
        score *= intent.confidence
        
        return min(score, 100.0)  # Cap at 100
    
    def _extract_dataset_type(self, dataset: Dict) -> str:
        """Extract dataset type from metadata."""
        name = dataset.get("name", "").lower()
        description = dataset.get("description", "").lower()
        
        # Pattern matching for dataset types
        if any(keyword in name for keyword in ["trace", "span", "tracing"]):
            return "trace"
        elif any(keyword in name for keyword in ["metric", "measurement", "gauge"]):
            return "metric"
        elif any(keyword in name for keyword in ["log", "event", "message"]):
            return "event"
        elif any(keyword in name for keyword in ["resource", "pod", "container", "node"]):
            return "resource"
        else:
            return "unknown"


# Example usage and testing
if __name__ == "__main__":
    classifier = IntentClassifier()
    scorer = DatasetScorer()
    
    # Test cases
    test_queries = [
        "Show me error rates by service with percentages",
        "Find slow traces over 2 seconds", 
        "Analyze log patterns for error messages",
        "Show request volume trends over time",
        "Display CPU usage by pod"
    ]
    
    for query in test_queries:
        intent = classifier.classify_intent(query)
        print(f"\nQuery: {query}")
        print(f"Intent: {intent.primary} (confidence: {intent.confidence:.2f})")
        print(f"Required fields: {intent.required_fields}")
        print(f"Preferred types: {intent.preferred_dataset_types}")
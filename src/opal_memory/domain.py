"""
Observability domain knowledge and concept mapping for OPAL memory system
"""

import re
from typing import Dict, List, Set, Tuple, Optional
from enum import Enum


class ObservabilityIntent(Enum):
    """Categories of observability query intents"""
    ERROR_ANALYSIS = "error_analysis"
    PERFORMANCE_MONITORING = "performance_monitoring" 
    DATA_EXPLORATION = "data_exploration"
    AGGREGATION = "aggregation"
    TIME_SERIES = "time_series"
    UNKNOWN = "unknown"


class TimeContext(Enum):
    """Categories of time references in queries"""
    QUERY_WINDOW = "query_window"      # Time range for query execution (API parameter)
    DATA_FILTER = "data_filter"        # Time values used in OPAL filtering logic
    MIXED = "mixed"                    # Both query window and data filtering
    NONE = "none"                      # No time references


class DomainConceptMapper:
    """Maps observability concepts to normalized terms for better matching"""
    
    def __init__(self):
        # Domain concept groups - words that mean similar things in observability
        self.concept_groups = {
            'error_concepts': {
                'errors', 'error', 'failures', 'failure', 'failed', 'issues', 'issue', 
                'problems', 'problem', 'exceptions', 'exception', 'faults', 'fault',
                'broken', 'crashes', 'crash', 'bugs', 'bug'
            },
            'performance_concepts': {
                'latency', 'response_time', 'response time', 'performance', 'speed',
                'duration', 'time', 'delay', 'slowness', 'fast', 'slow'
            },
            'throughput_concepts': {
                'throughput', 'requests_per_second', 'rps', 'qps', 'queries_per_second',
                'volume', 'load', 'traffic', 'requests', 'calls'
            },
            'aggregation_concepts': {
                'count', 'total', 'number', 'sum', 'average', 'avg', 'mean', 'median',
                'min', 'max', 'percentile', 'p50', 'p95', 'p99', 'distribution'
            },
            'temporal_concepts': {
                'recent', 'last', 'past', 'latest', 'current', 'now', 'today',
                'hour', 'hours', 'minute', 'minutes', 'second', 'seconds', 
                'day', 'days', 'week', 'weeks'
            },
            'action_concepts': {
                'show', 'display', 'get', 'fetch', 'find', 'search', 'list',
                'view', 'see', 'check', 'look', 'examine', 'analyze'
            },
            'grouping_concepts': {
                'group_by', 'group by', 'by', 'per', 'split by', 'break down',
                'categorize', 'segment'
            },
            'filtering_concepts': {
                'filter', 'where', 'with', 'having', 'containing', 'matching',
                'equals', 'like', 'similar'
            },
            'service_concepts': {
                'service', 'services', 'microservice', 'microservices', 
                'component', 'components', 'application', 'app', 'system'
            },
            'infrastructure_concepts': {
                'host', 'hosts', 'server', 'servers', 'instance', 'instances',
                'node', 'nodes', 'container', 'containers', 'pod', 'pods'
            },
            'endpoint_concepts': {
                'endpoint', 'endpoints', 'api', 'apis', 'route', 'routes',
                'path', 'paths', 'url', 'urls'
            }
        }
        
        # Create reverse mapping for quick lookups
        self.concept_to_group = {}
        for group_name, concepts in self.concept_groups.items():
            for concept in concepts:
                self.concept_to_group[concept.lower()] = group_name
        
        # Intent patterns for classifying queries
        self.intent_patterns = {
            ObservabilityIntent.ERROR_ANALYSIS: [
                r'\b(error|failure|exception|fault|crash|bug|issue|problem)\w*\b',
                r'\b(failed|broken|down|unavailable)\b',
                r'\b(5xx|4xx|error.rate|error_rate)\b'
            ],
            ObservabilityIntent.PERFORMANCE_MONITORING: [
                r'\b(latency|response.time|performance|duration|speed|slow|fast)\b',
                r'\b(p\d+|percentile|median)\b',
                r'\b(sla|slo|threshold)\b'
            ],
            ObservabilityIntent.DATA_EXPLORATION: [
                r'\b(what|which|show|list|explore|discover)\b.*\b(field|column|data)\b',
                r'\b(schema|structure|available)\b',
                r'\b(recent|latest|sample)\b.*\b(data|records|entries)\b'
            ],
            ObservabilityIntent.AGGREGATION: [
                r'\b(count|total|sum|average|mean|min|max)\b',
                r'\b(top|bottom|highest|lowest)\b.*\b\d+\b',
                r'\b(group.by|by)\b.*\b(service|host|endpoint)\b'
            ],
            ObservabilityIntent.TIME_SERIES: [
                r'\b(trend|over.time|timeline|chart|graph)\b',
                r'\b(last|past|recent)\b.*\b(hour|minute|day|week)\b',
                r'\btimechart\b'
            ]
        }
    
    def normalize_query_concepts(self, query: str) -> str:
        """
        Normalize query by replacing domain concepts with canonical terms.
        This helps with semantic similarity by standardizing vocabulary.
        """
        normalized = query.lower()
        
        # Apply concept group normalizations
        replacements = {
            # Error concepts -> 'error'
            r'\b(failures?|failed|issues?|problems?|exceptions?|faults?|crashes?|bugs?)\b': 'error',
            
            # Performance concepts -> 'latency'  
            r'\b(response.time|performance|duration|speed|delay)\b': 'latency',
            
            # Throughput concepts -> 'throughput'
            r'\b(requests?.per.second|rps|qps|queries?.per.second|volume|load|traffic)\b': 'throughput',
            
            # Action concepts -> 'show'
            r'\b(display|get|fetch|find|search|list|view|see|check|look|examine|analyze)\b': 'show',
            
            # Grouping concepts -> 'group_by'
            r'\b(group.by|split.by|break.down|categorize|segment)\b': 'group_by',
            r'\b\bby\s+(\w+)\b': r'group_by \1',  # "by service" -> "group_by service"
            
            # Service concepts -> 'service'
            r'\b(microservices?|components?|applications?|apps?|systems?)\b': 'service',
            
            # Infrastructure concepts -> 'host'
            r'\b(servers?|instances?|nodes?|containers?|pods?)\b': 'host',
            
            # Temporal concepts
            r'\b(recent|last|past|latest|current)\b': 'recent',
            r'\b(hours?|hrs?)\b': 'hour',
            r'\b(minutes?|mins?)\b': 'minute',
            r'\b(seconds?|secs?)\b': 'second'
        }
        
        for pattern, replacement in replacements.items():
            normalized = re.sub(pattern, replacement, normalized)
        
        return normalized.strip()
    
    def classify_query_intent(self, query: str) -> ObservabilityIntent:
        """
        Classify the intent/purpose of an observability query.
        Helps with matching similar types of queries.
        """
        query_lower = query.lower()
        
        # Score each intent based on pattern matches
        intent_scores = {intent: 0 for intent in ObservabilityIntent}
        
        for intent, patterns in self.intent_patterns.items():
            for pattern in patterns:
                matches = len(re.findall(pattern, query_lower))
                intent_scores[intent] += matches
        
        # Return intent with highest score, or UNKNOWN if no matches
        best_intent = max(intent_scores.keys(), key=lambda x: intent_scores[x])
        return best_intent if intent_scores[best_intent] > 0 else ObservabilityIntent.UNKNOWN
    
    def extract_key_entities(self, query: str) -> Dict[str, List[str]]:
        """
        Extract key observability entities from a query.
        Helps with context-aware matching.
        """
        query_lower = query.lower()
        entities = {
            'services': [],
            'metrics': [],
            'time_ranges': [],
            'aggregations': [],
            'filters': []
        }
        
        # Extract service names (common patterns)
        service_patterns = [
            r'\b([a-z-_]+service)\b',  # ending in 'service'
            r'\bservice[:\s]+([a-z-_]+)\b',  # 'service: name' or 'service name'
            r'\b([a-z-_]+)[-_](api|svc|service)\b'  # name-api, name_svc patterns
        ]
        
        for pattern in service_patterns:
            matches = re.findall(pattern, query_lower)
            entities['services'].extend(matches if isinstance(matches[0], str) else [m[0] for m in matches])
        
        # Extract time ranges
        time_patterns = [
            r'\b(last|past|recent)\s+(\d+)\s*(hour|minute|day|week|month)s?\b',
            r'\b(\d+)\s*(h|m|d|hr|min|hour|hours|minute|minutes)\b'
        ]
        
        for pattern in time_patterns:
            matches = re.findall(pattern, query_lower)
            entities['time_ranges'].extend([' '.join(m) if isinstance(m, tuple) else m for m in matches])
        
        # Extract aggregation functions
        agg_pattern = r'\b(count|sum|avg|average|min|max|percentile|p\d+)\b'
        entities['aggregations'] = re.findall(agg_pattern, query_lower)
        
        # Clean up and deduplicate
        for key in entities:
            entities[key] = list(set([e.strip() for e in entities[key] if e.strip()]))
        
        return entities
    
    def calculate_domain_similarity(self, query1: str, query2: str) -> float:
        """
        Calculate domain-specific similarity between two queries.
        Considers intent, entities, and concept overlap.
        """
        # Normalize both queries
        norm1 = self.normalize_query_concepts(query1)
        norm2 = self.normalize_query_concepts(query2)
        
        # Calculate intent similarity
        intent1 = self.classify_query_intent(query1)
        intent2 = self.classify_query_intent(query2)
        intent_score = 1.0 if intent1 == intent2 and intent1 != ObservabilityIntent.UNKNOWN else 0.5
        
        # Calculate entity overlap
        entities1 = self.extract_key_entities(query1)
        entities2 = self.extract_key_entities(query2)
        
        entity_scores = []
        for entity_type in entities1.keys():
            set1 = set(entities1[entity_type])
            set2 = set(entities2[entity_type])
            if set1 or set2:  # Only calculate if at least one query has this entity type
                overlap = len(set1.intersection(set2))
                union = len(set1.union(set2))
                entity_scores.append(overlap / union if union > 0 else 0)
        
        entity_score = sum(entity_scores) / len(entity_scores) if entity_scores else 0
        
        # Calculate concept overlap using normalized queries
        words1 = set(norm1.split())
        words2 = set(norm2.split())
        concept_overlap = len(words1.intersection(words2)) / len(words1.union(words2)) if words1.union(words2) else 0
        
        # Combine scores with weights
        domain_similarity = (
            0.4 * intent_score +
            0.3 * entity_score +
            0.3 * concept_overlap
        )
        
        return min(1.0, domain_similarity)
    
    def get_concept_group(self, word: str) -> Optional[str]:
        """Get the concept group for a word"""
        return self.concept_to_group.get(word.lower())
    
    def get_similar_concepts(self, word: str) -> Set[str]:
        """Get all concepts similar to a given word"""
        group = self.get_concept_group(word)
        if group:
            return self.concept_groups[group] - {word.lower()}
        return set()
    
    def classify_time_context(self, query: str) -> TimeContext:
        """
        Classify the type of time reference in a query.
        
        Query Window Time: "in the last hour", "past 2 days" (API time_range)
        Data Filter Time: "latency > 200ms", "duration longer than 1s" (OPAL query logic)
        """
        query_lower = query.lower()
        
        # Patterns for query window time (API parameter)
        query_window_patterns = [
            r'\b(in|over|during)\s+the\s+(last|past|recent)\s+\d+\s*(hour|minute|day|week|month)s?\b',
            r'\b(last|past|recent)\s+\d+\s*(h|m|d|hr|hrs|min|mins|hour|hours|minute|minutes|day|days|week|weeks|month|months)\b',
            r'\b(yesterday|today|this\s+(hour|day|week|month))\b',
            r'\bsince\s+(yesterday|last\s+(hour|day|week|month))\b'
        ]
        
        # Patterns for data filter time (OPAL query content)  
        data_filter_patterns = [
            r'\b(latency|duration|response\s*time|execution\s*time)\s*[><=]+\s*\d+\s*(ms|milliseconds?|s|seconds?|m|minutes?)\b',
            r'\b(slower?|faster?|longer?|shorter?)\s+than\s+\d+\s*(ms|milliseconds?|s|seconds?|m|minutes?)\b',
            r'\b(took?|takes?|lasting?|duration\s*of)\s+(more|less)\s+than\s+\d+\s*(ms|milliseconds?|s|seconds?)\b',
            r'\b(timeout|elapsed|processing\s*time)\s*[><=]+\s*\d+\s*(ms|s|seconds?|minutes?)\b',
            r'\bfilter.*duration\b.*\d+',
            r'\bfilter.*latency\b.*\d+',
            r'\bfilter.*response.*time\b.*\d+'
        ]
        
        # Check for patterns
        has_query_window = any(re.search(pattern, query_lower) for pattern in query_window_patterns)
        has_data_filter = any(re.search(pattern, query_lower) for pattern in data_filter_patterns)
        
        if has_query_window and has_data_filter:
            return TimeContext.MIXED
        elif has_query_window:
            return TimeContext.QUERY_WINDOW
        elif has_data_filter:
            return TimeContext.DATA_FILTER
        else:
            return TimeContext.NONE
    
    def extract_query_window_time(self, query: str) -> Optional[Dict[str, str]]:
        """
        Extract query window time information (API time_range parameter).
        
        Returns:
            Dict with 'value', 'unit', 'normalized' keys, or None if no window time found
        """
        query_lower = query.lower()
        
        # Patterns to extract time window values
        patterns = [
            r'\b(last|past|recent)\s+(\d+)\s*(h|m|d|hr|hrs|min|mins|hour|hours|minute|minutes|day|days|week|weeks|month|months)\b',
            r'\bin\s+the\s+(last|past|recent)\s+(\d+)\s*(hour|minute|day|week|month)s?\b'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, query_lower)
            if match:
                groups = match.groups()
                if len(groups) >= 3:
                    value = groups[1] if len(groups) > 2 else groups[0]
                    unit = groups[-1]  # Last group is the unit
                    
                    # Normalize unit
                    unit_mapping = {
                        'h': 'h', 'hr': 'h', 'hrs': 'h', 'hour': 'h', 'hours': 'h',
                        'm': 'm', 'min': 'm', 'mins': 'm', 'minute': 'm', 'minutes': 'm',
                        'd': 'd', 'day': 'd', 'days': 'd',
                        'week': 'w', 'weeks': 'w',
                        'month': 'M', 'months': 'M'
                    }
                    
                    normalized_unit = unit_mapping.get(unit, unit)
                    normalized = f"{value}{normalized_unit}"
                    
                    return {
                        'value': value,
                        'unit': unit,
                        'normalized': normalized,
                        'original': match.group(0)
                    }
        
        return None
    
    def extract_data_filter_time(self, query: str) -> List[Dict[str, str]]:
        """
        Extract data filter time information (OPAL query values).
        
        Returns:
            List of dicts with 'field', 'operator', 'value', 'unit', 'nanoseconds' keys
        """
        query_lower = query.lower()
        results = []
        
        # Patterns to extract data filter time values
        patterns = [
            r'\b(latency|duration|response\s*time|execution\s*time)\s*([><=]+)\s*(\d+(?:\.\d+)?)\s*(ms|milliseconds?|s|seconds?|m|minutes?)\b',
            r'\b(slower?|faster?|longer?|shorter?)\s+than\s+(\d+(?:\.\d+)?)\s*(ms|milliseconds?|s|seconds?|m|minutes?)\b',
            r'\btook?\s+(more|less)\s+than\s+(\d+(?:\.\d+)?)\s*(ms|milliseconds?|s|seconds?)\b'
        ]
        
        for pattern in patterns:
            matches = re.finditer(pattern, query_lower)
            for match in matches:
                groups = match.groups()
                
                if len(groups) >= 3:
                    if 'than' in pattern:  # "slower than X" format
                        field = groups[0]
                        operator = '>=' if any(word in groups[1] for word in ['slower', 'longer', 'more']) else '<='
                        value = groups[1] if len(groups) == 3 else groups[2]
                        unit = groups[2] if len(groups) == 3 else groups[3]
                    else:  # "latency > X" format
                        field = groups[0]
                        operator = groups[1]
                        value = groups[2]
                        unit = groups[3]
                    
                    # Convert to nanoseconds for OPAL
                    nanoseconds = self._convert_to_nanoseconds(float(value), unit)
                    
                    results.append({
                        'field': field,
                        'operator': operator, 
                        'value': value,
                        'unit': unit,
                        'nanoseconds': nanoseconds,
                        'original': match.group(0)
                    })
        
        return results
    
    def _convert_to_nanoseconds(self, value: float, unit: str) -> int:
        """Convert time value to nanoseconds for OPAL queries"""
        unit_lower = unit.lower()
        
        conversions = {
            'ms': 1_000_000,           # milliseconds to nanoseconds
            'millisecond': 1_000_000,
            'milliseconds': 1_000_000,
            's': 1_000_000_000,        # seconds to nanoseconds  
            'second': 1_000_000_000,
            'seconds': 1_000_000_000,
            'm': 60_000_000_000,       # minutes to nanoseconds
            'minute': 60_000_000_000,
            'minutes': 60_000_000_000
        }
        
        multiplier = conversions.get(unit_lower, 1_000_000)  # Default to ms
        return int(value * multiplier)
    
    def calculate_time_aware_similarity(self, query1: str, query2: str) -> float:
        """
        Calculate similarity between queries considering time context.
        
        Query window times are treated as interchangeable (high similarity).
        Data filter times require value compatibility (moderate similarity).
        """
        context1 = self.classify_time_context(query1)
        context2 = self.classify_time_context(query2)
        
        # If both are query window time, focus on core intent (ignore specific time ranges)
        if context1 == context2 == TimeContext.QUERY_WINDOW:
            # Remove time window parts and compare core queries
            core1 = self._remove_query_window_time(query1)
            core2 = self._remove_query_window_time(query2)
            
            # High base similarity for same query window context
            base_similarity = 0.9
            
            # Adjust based on core query similarity
            core_similarity = self.calculate_domain_similarity(core1, core2)
            return min(1.0, base_similarity * core_similarity)
        
        # If both are data filter time, consider time value compatibility
        elif context1 == context2 == TimeContext.DATA_FILTER:
            filter1 = self.extract_data_filter_time(query1)
            filter2 = self.extract_data_filter_time(query2)
            
            # Check if time filters are in same magnitude
            time_compatibility = self._assess_time_filter_compatibility(filter1, filter2)
            
            # Base similarity reduced for different time filters
            base_similarity = 0.7
            return base_similarity * time_compatibility
        
        # If contexts don't match, lower similarity
        elif context1 != context2:
            return 0.3  # Different time contexts are less likely to match
        
        # If neither has time context, use standard domain similarity
        else:
            return self.calculate_domain_similarity(query1, query2)
    
    def _remove_query_window_time(self, query: str) -> str:
        """Remove query window time phrases from query"""
        patterns = [
            r'\b(in|over|during)\s+the\s+(last|past|recent)\s+\d+\s*(hour|minute|day|week|month)s?\b',
            r'\b(last|past|recent)\s+\d+\s*(h|m|d|hr|hrs|min|mins|hour|hours|minute|minutes|day|days|week|weeks)\b',
            r'\b(yesterday|today|this\s+(hour|day|week|month))\b'
        ]
        
        cleaned = query
        for pattern in patterns:
            cleaned = re.sub(pattern, '', cleaned, flags=re.IGNORECASE)
        
        # Clean up extra whitespace
        cleaned = re.sub(r'\s+', ' ', cleaned).strip()
        return cleaned
    
    def _assess_time_filter_compatibility(self, filters1: List[Dict], filters2: List[Dict]) -> float:
        """Assess compatibility between data filter time values"""
        if not filters1 or not filters2:
            return 1.0  # No time filters to compare
        
        # Compare time magnitudes (order of magnitude compatibility)
        compatibilities = []
        
        for f1 in filters1:
            for f2 in filters2:
                ns1 = f1.get('nanoseconds', 0)
                ns2 = f2.get('nanoseconds', 0)
                
                if ns1 > 0 and ns2 > 0:
                    # Calculate order of magnitude difference
                    import math
                    ratio = max(ns1, ns2) / min(ns1, ns2)
                    log_ratio = math.log10(ratio)
                    
                    # High compatibility for same order of magnitude
                    if log_ratio < 0.5:      # Within ~3x
                        compatibility = 1.0
                    elif log_ratio < 1.0:    # Within ~10x
                        compatibility = 0.8
                    elif log_ratio < 1.5:    # Within ~30x
                        compatibility = 0.6
                    else:                    # Very different magnitudes
                        compatibility = 0.3
                    
                    compatibilities.append(compatibility)
        
        return max(compatibilities) if compatibilities else 0.5


# Global domain mapper instance
_domain_mapper: Optional[DomainConceptMapper] = None


def get_domain_mapper() -> DomainConceptMapper:
    """Get or create the global domain concept mapper"""
    global _domain_mapper
    
    if _domain_mapper is None:
        _domain_mapper = DomainConceptMapper()
    
    return _domain_mapper
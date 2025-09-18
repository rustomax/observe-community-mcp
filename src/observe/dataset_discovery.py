"""
Smart dataset discovery for multi-dataset queries.

This module provides functionality to automatically discover related datasets
that can be joined together based on schema relationships and common patterns.
"""

import sys
import re
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass
from src.logging import get_logger

logger = get_logger('DISCOVERY')

# Import telemetry decorators
try:
    from src.telemetry.decorators import trace_database_operation
    from src.telemetry.utils import add_span_attributes
except ImportError:
    # Fallback decorators if telemetry is not available
    def trace_database_operation(operation=None, table=None):
        def decorator(func):
            return func
        return decorator

    def add_span_attributes(span, attributes):
        pass


@dataclass
class DatasetRelationship:
    """Represents a relationship between two datasets."""
    primary_dataset_id: str
    secondary_dataset_id: str
    join_keys: List[str]
    relationship_type: str  # "one_to_many", "many_to_one", "many_to_many"
    confidence: float
    suggested_alias: str


@dataclass  
class DatasetSuggestion:
    """Represents a suggested dataset for multi-dataset queries."""
    dataset_id: str
    dataset_name: str
    suggested_alias: str
    relevance_score: float
    potential_joins: List[str]
    description: str


def analyze_dataset_schema(schema_info: str) -> Dict[str, Any]:
    """
    Analyze dataset schema to extract field information and types.
    
    Args:
        schema_info: Schema information string (typically JSON or text format)
        
    Returns:
        Dict containing parsed schema information
    """
    schema_analysis = {
        "fields": [],
        "key_fields": [],
        "foreign_key_candidates": [],
        "timestamp_fields": [],
        "metric_fields": [],
        "dimension_fields": []
    }
    
    try:
        # Try to extract field names from schema (handles multiple formats)
        field_patterns = [
            r"'name':\s*'([^']+)'",  # JSON format: 'name': 'field_name'
            r'"name":\s*"([^"]+)"',  # JSON format: "name": "field_name"
            r"name:\s*(\w+)",        # YAML-like format
            r"Field:\s*(\w+)",       # Text format: Field: field_name
            r"(\w+)\s*\(",          # Function-like format: field_name(
        ]
        
        for pattern in field_patterns:
            matches = re.findall(pattern, schema_info, re.IGNORECASE)
            schema_analysis["fields"].extend(matches)
        
        # Remove duplicates and filter
        schema_analysis["fields"] = list(set(schema_analysis["fields"]))
        
        # Categorize fields by type and purpose
        for field in schema_analysis["fields"]:
            field_lower = field.lower()
            
            # Identify key fields (potential join keys)
            if any(key_term in field_lower for key_term in [
                'id', 'key', 'guid', 'uuid', 'identifier', 
                'instanceid', 'podname', 'containerid', 'servicename'
            ]):
                schema_analysis["key_fields"].append(field)
            
            # Identify foreign key candidates 
            if any(fk_term in field_lower for fk_term in [
                'instanceid', 'volumeid', 'podid', 'containerid', 
                'nodeid', 'serviceid', 'userid', 'accountid'
            ]):
                schema_analysis["foreign_key_candidates"].append(field)
            
            # Identify timestamp fields
            if any(time_term in field_lower for time_term in [
                'time', 'timestamp', 'date', 'created', 'updated', 
                'start', 'end', 'duration'
            ]):
                schema_analysis["timestamp_fields"].append(field)
            
            # Identify metric fields
            if any(metric_term in field_lower for metric_term in [
                'value', 'count', 'metric', 'cpu', 'memory', 'disk', 
                'network', 'latency', 'throughput', 'error', 'rate'
            ]):
                schema_analysis["metric_fields"].append(field)
            
            # Everything else is likely a dimension
            if field not in (schema_analysis["key_fields"] + 
                           schema_analysis["timestamp_fields"] + 
                           schema_analysis["metric_fields"]):
                schema_analysis["dimension_fields"].append(field)
        
        logger.debug(f"analyzed schema | fields:{len(schema_analysis['fields'])} | keys:{len(schema_analysis['key_fields'])} | fk_candidates:{len(schema_analysis['foreign_key_candidates'])}")
        
    except Exception as e:
        logger.error(f"schema analysis error: {e}")
    
    return schema_analysis


@trace_database_operation(operation="dataset_discovery", table="dataset_relationships")
async def discover_related_datasets(
    primary_dataset_id: str,
    primary_schema: str,
    available_datasets: List[Dict[str, str]],
    max_suggestions: int = 5
) -> List[DatasetSuggestion]:
    """
    Discover datasets that can potentially be joined with the primary dataset.
    
    Args:
        primary_dataset_id: ID of the primary dataset
        primary_schema: Schema information for the primary dataset
        available_datasets: List of available datasets with id, name, and optionally schema
        max_suggestions: Maximum number of suggestions to return
        
    Returns:
        List of dataset suggestions ranked by relevance
    """
    if not available_datasets:
        return []
    
    logger.debug(f"discovering related datasets for {primary_dataset_id}")
    
    # Analyze primary dataset schema
    primary_analysis = analyze_dataset_schema(primary_schema)
    
    suggestions = []
    
    for dataset in available_datasets:
        if dataset.get('id') == primary_dataset_id:
            continue  # Skip self
        
        dataset_id = dataset.get('id', '')
        dataset_name = dataset.get('name', '')
        
        # Calculate relevance based on name patterns and potential relationships
        suggestion = analyze_dataset_relationship(
            primary_dataset_id, primary_analysis, dataset_id, dataset_name
        )
        
        if suggestion and suggestion.relevance_score > 0.1:  # Minimum threshold
            suggestions.append(suggestion)
    
    # Sort by relevance score (descending)
    suggestions.sort(key=lambda x: x.relevance_score, reverse=True)
    
    # Limit to max_suggestions
    suggestions = suggestions[:max_suggestions]
    
    logger.debug(f"found {len(suggestions)} related datasets")
    for suggestion in suggestions:
        logger.debug(f"suggestion: {suggestion.suggested_alias}: {suggestion.dataset_name} (score: {suggestion.relevance_score:.2f})")
    
    return suggestions


def analyze_dataset_relationship(
    primary_dataset_id: str,
    primary_analysis: Dict[str, Any], 
    candidate_dataset_id: str,
    candidate_dataset_name: str
) -> Optional[DatasetSuggestion]:
    """
    Analyze the potential relationship between primary dataset and a candidate dataset.
    
    Args:
        primary_dataset_id: ID of primary dataset
        primary_analysis: Analyzed schema of primary dataset
        candidate_dataset_id: ID of candidate dataset
        candidate_dataset_name: Name of candidate dataset
        
    Returns:
        DatasetSuggestion if a relationship is found, None otherwise
    """
    relevance_score = 0.0
    potential_joins = []
    suggested_alias = ""
    description = ""
    
    dataset_name_lower = candidate_dataset_name.lower()
    
    # Common dataset relationship patterns
    relationship_patterns = {
        # AWS Infrastructure
        'volume': {
            'keywords': ['volume', 'ebs', 'storage'],
            'alias': 'volumes',
            'joins': ['instanceId', 'volumeId'],
            'score': 0.8
        },
        'instance': {
            'keywords': ['instance', 'ec2', 'virtual machine', 'vm'],
            'alias': 'instances', 
            'joins': ['instanceId', 'instanceType'],
            'score': 0.8
        },
        'cloudtrail': {
            'keywords': ['cloudtrail', 'event', 'api', 'audit'],
            'alias': 'events',
            'joins': ['instanceId', 'resourceId', 'userId'],
            'score': 0.7
        },
        # Kubernetes
        'pod': {
            'keywords': ['pod', 'kubernetes', 'k8s'],
            'alias': 'pods',
            'joins': ['podName', 'namespace', 'nodeName'],
            'score': 0.8
        },
        'container': {
            'keywords': ['container', 'docker'],
            'alias': 'containers',
            'joins': ['containerName', 'containerId', 'podName'],
            'score': 0.7
        },
        'service': {
            'keywords': ['service', 'svc'],
            'alias': 'services',
            'joins': ['serviceName', 'namespace'],
            'score': 0.7
        },
        # Monitoring/Observability
        'metric': {
            'keywords': ['metric', 'measurement', 'telemetry'],
            'alias': 'metrics',
            'joins': ['resourceId', 'serviceName'],
            'score': 0.6
        },
        'log': {
            'keywords': ['log', 'logging'],
            'alias': 'logs',
            'joins': ['instanceId', 'serviceName', 'podName'],
            'score': 0.6
        },
        'trace': {
            'keywords': ['trace', 'tracing', 'span'],
            'alias': 'traces',
            'joins': ['traceId', 'spanId', 'serviceName'],
            'score': 0.6
        }
    }
    
    # Check for pattern matches
    best_pattern = None
    best_pattern_score = 0.0
    
    for pattern_name, pattern_info in relationship_patterns.items():
        pattern_score = 0.0
        
        # Check if dataset name matches pattern keywords
        for keyword in pattern_info['keywords']:
            if keyword in dataset_name_lower:
                pattern_score = pattern_info['score']
                
                # Boost score if multiple keywords match
                keyword_matches = sum(1 for kw in pattern_info['keywords'] if kw in dataset_name_lower)
                pattern_score += 0.1 * (keyword_matches - 1)
                break
        
        if pattern_score > best_pattern_score:
            best_pattern_score = pattern_score
            best_pattern = pattern_info
            suggested_alias = pattern_info['alias']
    
    if best_pattern:
        relevance_score = best_pattern_score
        potential_joins = best_pattern['joins']
        
        # Check if primary dataset has any of the potential join keys
        primary_keys = primary_analysis.get('key_fields', []) + primary_analysis.get('foreign_key_candidates', [])
        matching_keys = [join_key for join_key in potential_joins 
                        if any(join_key.lower() in pk.lower() or pk.lower() in join_key.lower() 
                               for pk in primary_keys)]
        
        if matching_keys:
            relevance_score += 0.2  # Boost score for matching keys
            description = f"Can join on: {', '.join(matching_keys)}"
        else:
            description = f"Potential joins: {', '.join(potential_joins)}"
    
    # Additional heuristics based on name similarity
    if not suggested_alias:
        # Generate alias from dataset name
        name_parts = re.findall(r'\w+', dataset_name_lower)
        if name_parts:
            if len(name_parts[-1]) > 3:  # Use last meaningful word
                suggested_alias = name_parts[-1].lower()
            else:
                suggested_alias = ''.join(part[:3] for part in name_parts[-2:])
        else:
            suggested_alias = f"ds_{candidate_dataset_id[-4:]}"
    
    # AWS-specific patterns
    if 'aws/' in dataset_name_lower:
        relevance_score += 0.1
        if 'ec2' in dataset_name_lower:
            relevance_score += 0.2
    
    # Kubernetes-specific patterns  
    if any(k8s_term in dataset_name_lower for k8s_term in ['kubernetes', 'k8s']):
        relevance_score += 0.1
    
    # Infrastructure correlation patterns
    if any(infra_term in dataset_name_lower for infra_term in ['infrastructure', 'system', 'resource']):
        relevance_score += 0.1
    
    if relevance_score > 0.0:
        return DatasetSuggestion(
            dataset_id=candidate_dataset_id,
            dataset_name=candidate_dataset_name,
            suggested_alias=suggested_alias,
            relevance_score=relevance_score,
            potential_joins=potential_joins,
            description=description or f"Related {suggested_alias} dataset"
        )
    
    return None


def build_join_query_suggestions(
    primary_analysis: Dict[str, Any],
    suggestions: List[DatasetSuggestion]
) -> List[str]:
    """
    Build example OPAL join queries based on dataset suggestions.
    
    Args:
        primary_analysis: Analyzed schema of primary dataset
        suggestions: List of dataset suggestions
        
    Returns:
        List of example OPAL query snippets
    """
    join_examples = []
    
    primary_keys = primary_analysis.get('key_fields', []) + primary_analysis.get('foreign_key_candidates', [])
    
    for suggestion in suggestions[:3]:  # Limit to top 3 suggestions
        alias = suggestion.suggested_alias
        
        # Find potential join conditions
        join_conditions = []
        for join_key in suggestion.potential_joins:
            # Look for matching keys in primary dataset
            matching_primary_keys = [pk for pk in primary_keys 
                                   if join_key.lower() in pk.lower() or pk.lower() in join_key.lower()]
            
            if matching_primary_keys:
                primary_key = matching_primary_keys[0]
                join_conditions.append(f"{primary_key}=@{alias}.{join_key}")
        
        if join_conditions:
            # Create join query example
            join_condition = join_conditions[0]  # Use first matching condition
            example_fields = f"volume_size:@{alias}.size" if alias == "volumes" else f"info:@{alias}.name"
            
            join_query = f"join on({join_condition}), {example_fields}"
            join_examples.append({
                "query": join_query,
                "description": f"Join with {suggestion.dataset_name} on {join_condition.split('=')[0]}",
                "alias": alias,
                "dataset_id": suggestion.dataset_id
            })
    
    return join_examples


async def suggest_dataset_for_query_intent(
    query_intent: str,
    available_datasets: List[Dict[str, str]],
    max_suggestions: int = 3
) -> List[DatasetSuggestion]:
    """
    Suggest datasets based on natural language query intent.
    
    Args:
        query_intent: Natural language description of what user wants
        available_datasets: List of available datasets
        max_suggestions: Maximum suggestions to return
        
    Returns:
        List of relevant dataset suggestions
    """
    intent_lower = query_intent.lower()
    suggestions = []
    
    # Intent-based dataset mapping
    intent_patterns = {
        # Infrastructure monitoring
        'cpu': ['metric', 'instance', 'performance', 'system'],
        'memory': ['metric', 'instance', 'performance', 'system'],
        'disk': ['metric', 'volume', 'storage', 'instance'],
        'network': ['metric', 'instance', 'traffic', 'bandwidth'],
        
        # AWS-specific
        'ec2': ['instance', 'aws', 'virtual machine'],
        'ebs': ['volume', 'storage', 'aws'],
        'cloudtrail': ['event', 'audit', 'api', 'aws'],
        
        # Kubernetes
        'pod': ['kubernetes', 'k8s', 'container'],
        'container': ['kubernetes', 'docker', 'k8s'],
        'service': ['kubernetes', 'k8s'],
        'node': ['kubernetes', 'k8s', 'infrastructure'],
        
        # Operations
        'error': ['log', 'event', 'trace', 'metric'],
        'latency': ['metric', 'trace', 'performance'],
        'throughput': ['metric', 'performance'],
        'availability': ['metric', 'uptime', 'health']
    }
    
    # Find relevant datasets based on intent keywords
    for dataset in available_datasets:
        dataset_name = dataset.get('name', '').lower()
        dataset_id = dataset.get('id', '')
        
        relevance_score = 0.0
        matching_intents = []
        
        # Check for direct keyword matches
        for intent_word in intent_lower.split():
            if len(intent_word) > 3:  # Skip short words
                if intent_word in dataset_name:
                    relevance_score += 0.3
                    matching_intents.append(intent_word)
                
                # Check intent patterns
                if intent_word in intent_patterns:
                    pattern_keywords = intent_patterns[intent_word]
                    for keyword in pattern_keywords:
                        if keyword in dataset_name:
                            relevance_score += 0.2
                            matching_intents.append(f"{intent_word}->{keyword}")
                            break
        
        # Check for related terms
        if any(term in dataset_name for term in ['metric', 'log', 'event', 'trace']) and \
           any(term in intent_lower for term in ['monitor', 'track', 'analyze', 'measure']):
            relevance_score += 0.1
        
        if relevance_score > 0.1:
            # Generate alias from dataset name
            name_parts = re.findall(r'\w+', dataset_name)
            suggested_alias = name_parts[-1].lower() if name_parts else f"ds_{dataset_id[-4:]}"
            
            suggestion = DatasetSuggestion(
                dataset_id=dataset_id,
                dataset_name=dataset.get('name', ''),
                suggested_alias=suggested_alias,
                relevance_score=relevance_score,
                potential_joins=[],  # Will be filled based on schema analysis
                description=f"Relevant for: {', '.join(matching_intents)}"
            )
            suggestions.append(suggestion)
    
    # Sort by relevance
    suggestions.sort(key=lambda x: x.relevance_score, reverse=True)
    
    logger.debug(f"found {len(suggestions)} datasets for intent: '{query_intent}'")
    
    return suggestions[:max_suggestions]
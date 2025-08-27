"""
Dataset recommendation system for intelligent dataset discovery.

This module provides multi-strategy dataset recommendations based on natural language queries,
combining semantic similarity, categorical matching, field relevance, and schema intelligence.
"""

import re
import sys
from dataclasses import dataclass
from typing import List, Dict, Optional, Set, Tuple
import asyncio
import asyncpg
import json
from datetime import datetime

try:
    import openai
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False


@dataclass
class DatasetRecommendation:
    """
    A recommended dataset with relevance scoring and explanation.
    """
    dataset_id: str
    name: str
    dataset_type: str
    business_category: str
    technical_category: str
    key_fields: List[str]
    relevance_score: float
    match_reasons: List[str]
    sample_fields: Dict[str, str]
    description: Optional[str] = None


@dataclass
class QueryIntent:
    """
    Parsed intent and metadata from a natural language query.
    """
    original_query: str
    embedding: Optional[List[float]]
    business_categories: List[str]
    technical_categories: List[str]
    relevant_fields: List[str]
    query_terms: List[str]
    intent_type: str  # 'performance', 'errors', 'monitoring', 'analysis', etc.
    preferred_interfaces: List[str]  # 'log', 'metric', 'span', etc.
    preferred_types: List[str]  # 'event', 'resource', 'interval', 'table'


class QueryParser:
    """
    Parses natural language queries to extract intent, categories, and relevant fields.
    """
    
    # Category mappings based on common query patterns
    BUSINESS_CATEGORY_PATTERNS = {
        'infrastructure': [
            # Container/orchestration terms
            'pod', 'node', 'container', 'cluster', 'kubernetes', 'k8s', 'docker', 'ecs', 'fargate',
            # Hardware/system terms  
            'server', 'host', 'instance', 'vm', 'machine', 'compute',
            # Resource terms
            'cpu', 'memory', 'ram', 'disk', 'storage', 'processor', 'core', 'thread',
            # Cloud provider terms
            'ec2', 'gce', 'azure', 'aws', 'gcp', 'cloud',
            # System monitoring
            'system', 'os', 'linux', 'windows', 'telegraf'
        ],
        'application': [
            # Service terms
            'service', 'app', 'application', 'microservice', 'api', 'endpoint', 'webapp',
            # Request/response terms
            'request', 'response', 'http', 'https', 'rest', 'graphql',
            # Performance terms
            'trace', 'span', 'latency', 'performance', 'duration', 'response time',
            # Application frameworks
            'spring', 'django', 'express', 'flask', 'react', 'angular'
        ],
        'monitoring': [
            'alert', 'metric', 'monitor', 'health', 'status', 'availability', 'uptime', 'sla', 'slo',
            'dashboard', 'visualization', 'chart', 'graph', 'observability', 'telemetry'
        ],
        'database': [
            # Generic database terms
            'db', 'database', 'sql', 'nosql', 'query', 'connection', 'transaction', 'table', 'index',
            # Specific database systems
            'mysql', 'postgres', 'postgresql', 'oracle', 'sql server', 'mongodb', 'redis', 'elasticsearch',
            'cassandra', 'dynamodb', 'rds', 'aurora', 'cosmos', 'bigquery',
            # Database operations
            'crud', 'select', 'insert', 'update', 'delete', 'join', 'schema'
        ],
        'security': [
            'auth', 'authentication', 'authorization', 'login', 'user', 'access', 'permission', 'security',
            'oauth', 'jwt', 'token', 'certificate', 'ssl', 'tls', 'encryption', 'firewall',
            'vulnerability', 'intrusion', 'audit', 'compliance'
        ],
        'network': [
            'network', 'traffic', 'bandwidth', 'connection', 'tcp', 'udp', 'http', 'https', 'dns',
            'load balancer', 'proxy', 'cdn', 'latency', 'packet', 'routing', 'vpn', 'subnet'
        ],
        'storage': [
            'storage', 'volume', 'disk', 'file', 'bucket', 's3', 'blob', 'filesystem', 'iops',
            'throughput', 'backup', 'snapshot', 'archive', 'ebs', 'efs', 'gcs'
        ]
    }
    
    TECHNICAL_CATEGORY_PATTERNS = {
        'metrics': ['metric', 'measurement', 'count', 'rate', 'average', 'percentile', 'gauge', 'counter'],
        'logs': ['log', 'event', 'message', 'entry', 'output', 'console'],
        'events': ['event', 'incident', 'alert', 'notification', 'trigger'],
        'resources': ['resource', 'inventory', 'catalog', 'list', 'status', 'state'],
        'traces': ['trace', 'span', 'tracing', 'distributed', 'call', 'request flow']
    }
    
    FIELD_PATTERNS = {
        'service_name': ['service', 'app', 'application', 'microservice'],
        'error': ['error', 'exception', 'failure', 'fault', 'issue', 'problem', 'bug'],
        'duration': ['duration', 'latency', 'response time', 'time', 'speed', 'performance', 'elapsed'],
        'timestamp': ['time', 'when', 'date', 'timestamp', 'created', 'updated'],
        'status': ['status', 'state', 'condition', 'health', 'code'],
        'cpu': ['cpu', 'processor', 'compute', 'core', 'thread'],
        'memory': ['memory', 'ram', 'mem', 'heap', 'buffer'],
        'network': ['network', 'net', 'traffic', 'bandwidth', 'connection'],
        'user': ['user', 'customer', 'account', 'client', 'username'],
        'count': ['count', 'number', 'amount', 'quantity', 'total', 'sum'],
        'host': ['host', 'hostname', 'server', 'node', 'instance'],
        'container': ['container', 'pod', 'docker', 'kubernetes'],
        'database': ['database', 'db', 'table', 'schema', 'connection'],
        'url': ['url', 'uri', 'path', 'endpoint', 'route'],
        'ip': ['ip', 'address', 'source', 'destination', 'client'],
        'disk': ['disk', 'storage', 'volume', 'filesystem', 'mount'],
        'process': ['process', 'pid', 'command', 'thread'],
        'port': ['port', 'socket', 'listen', 'bind']
    }
    
    INTENT_PATTERNS = {
        'performance': ['performance', 'latency', 'speed', 'slow', 'fast', 'response time', 'throughput'],
        'errors': ['error', 'exception', 'failure', 'fault', 'issue', 'problem', 'bug'],
        'monitoring': ['monitor', 'health', 'status', 'availability', 'uptime', 'alert'],
        'analysis': ['analyze', 'trend', 'pattern', 'compare', 'correlation', 'insight'],
        'troubleshooting': ['debug', 'diagnose', 'investigate', 'root cause', 'troubleshoot'],
        'capacity': ['capacity', 'usage', 'utilization', 'consumption', 'load', 'scale']
    }
    
    # Interface and type mappings for query understanding
    INTERFACE_PATTERNS = {
        'log': ['log', 'logs', 'logging', 'event', 'message', 'output', 'console', 'syslog'],
        'metric': ['metric', 'metrics', 'measurement', 'gauge', 'counter', 'histogram', 'summary'],
        'span': ['span', 'trace', 'tracing', 'distributed', 'otel', 'opentelemetry', 'request flow'],
        'otel_span': ['span', 'trace', 'tracing', 'distributed', 'otel', 'opentelemetry']
    }
    
    TYPE_PATTERNS = {
        'event': ['event', 'time series', 'stream', 'timeseries', 'log', 'metric', 'alert'],
        'resource': ['resource', 'inventory', 'catalog', 'static', 'configuration', 'metadata'],
        'interval': ['interval', 'span', 'duration', 'trace', 'session', 'period'],
        'table': ['table', 'lookup', 'reference', 'dimension', 'static']
    }
    
    # Query intent to preferred interface/type mapping
    INTENT_TO_INTERFACE_TYPE = {
        'performance': [('metric', 'event'), ('span', 'interval'), ('otel_span', 'interval')],
        'errors': [('log', 'event'), ('metric', 'event'), ('span', 'interval')],
        'monitoring': [('metric', 'event'), ('log', 'event')],
        'analysis': [('metric', 'event'), ('log', 'event'), ('span', 'interval')],
        'troubleshooting': [('log', 'event'), ('span', 'interval'), ('metric', 'event')],
        'capacity': [('metric', 'event'), ('resource', 'resource')]
    }
    
    def parse_query(self, query: str) -> QueryIntent:
        """
        Parse a natural language query into structured intent.
        
        Args:
            query: Natural language query string
            
        Returns:
            QueryIntent with extracted metadata
        """
        query_lower = query.lower()
        
        # Extract business categories
        business_categories = []
        for category, patterns in self.BUSINESS_CATEGORY_PATTERNS.items():
            if any(pattern in query_lower for pattern in patterns):
                business_categories.append(category.title())
        
        # Extract technical categories  
        technical_categories = []
        for category, patterns in self.TECHNICAL_CATEGORY_PATTERNS.items():
            if any(pattern in query_lower for pattern in patterns):
                technical_categories.append(category.title())
        
        # Extract relevant fields
        relevant_fields = []
        for field, patterns in self.FIELD_PATTERNS.items():
            if any(pattern in query_lower for pattern in patterns):
                relevant_fields.append(field)
        
        # Determine intent type
        intent_type = 'general'
        for intent, patterns in self.INTENT_PATTERNS.items():
            if any(pattern in query_lower for pattern in patterns):
                intent_type = intent
                break
        
        # Extract key terms (remove common stop words)
        stop_words = {'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by', 'is', 'are', 'was', 'were', 'be', 'been', 'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'could', 'should', 'may', 'might', 'can', 'show', 'me', 'get', 'find'}
        query_terms = [word for word in re.findall(r'\b\w+\b', query_lower) if word not in stop_words and len(word) > 2]
        
        # Extract preferred interfaces
        preferred_interfaces = []
        for interface, patterns in self.INTERFACE_PATTERNS.items():
            if any(pattern in query_lower for pattern in patterns):
                preferred_interfaces.append(interface)
        
        # Extract preferred types
        preferred_types = []
        for dtype, patterns in self.TYPE_PATTERNS.items():
            if any(pattern in query_lower for pattern in patterns):
                preferred_types.append(dtype)
        
        # Add intent-based interface/type preferences
        if intent_type in self.INTENT_TO_INTERFACE_TYPE:
            for interface, dtype in self.INTENT_TO_INTERFACE_TYPE[intent_type]:
                if interface not in preferred_interfaces:
                    preferred_interfaces.append(interface)
                if dtype not in preferred_types:
                    preferred_types.append(dtype)
        
        return QueryIntent(
            original_query=query,
            embedding=None,  # Will be populated later
            business_categories=business_categories,
            technical_categories=technical_categories,
            relevant_fields=relevant_fields,
            query_terms=query_terms,
            intent_type=intent_type,
            preferred_interfaces=preferred_interfaces,
            preferred_types=preferred_types
        )


class DatasetRecommendationEngine:
    """
    Core engine for recommending datasets based on natural language queries.
    """
    
    def __init__(self, db_config: Dict[str, str]):
        """
        Initialize the recommendation engine.
        
        Args:
            db_config: Database connection configuration
        """
        self.db_config = db_config
        self.parser = QueryParser()
        self.connection_pool = None
        
        # Priority dataset patterns - these get boosted in recommendations
        # Patterns are case-insensitive. Order matters: more specific first.
        self.priority_patterns = {
            'tracing_critical': [
                # Exact matches for core tracing datasets (highest priority)
                'span',
                'span event',
                'trace',
            ],
            'tracing_high': [
                # High-priority tracing datasets
                'opentelemetry/trace',
                'otel/trace',
                'distributed trace',
                'opentelemetry span',
                'jaeger span',
            ],
            'logs_critical': [
                # Exact matches for core log datasets (highest priority)
                'kubernetes explorer/opentelemetry logs',
                'kubernetes/container logs',
                'kubernetes logs',
                'opentelemetry logs',
            ],
            'logs_high': [
                # High-priority log datasets
                'container logs',
                'application logs',
                'otel logs',
                'kubernetes/logs',
            ],
            'metrics_critical': [
                # Exact matches for core metrics datasets (highest priority)
                'prometheus metrics',
                'service inspector metrics', 
                'service metrics',
                'span metrics',
            ],
            'metrics_high': [
                # High-priority metrics datasets
                'cadvisor metrics',
                'kubelet metrics',
                'kubernetes/prometheus metrics',
                'kubernetes explorer/prometheus metrics',
            ]
        }
    
    async def initialize(self):
        """Initialize database connection pool."""
        try:
            self.connection_pool = await asyncpg.create_pool(
                host=self.db_config['host'],
                port=self.db_config['port'],
                database=self.db_config['database'],
                user=self.db_config['user'],
                password=self.db_config['password'],
                min_size=1,
                max_size=5,
                command_timeout=30
            )
            print("[DATASET_REC] Database connection pool initialized", file=sys.stderr)
        except Exception as e:
            print(f"[DATASET_REC] Failed to initialize database connection: {e}", file=sys.stderr)
            raise
    
    async def close(self):
        """Close database connection pool."""
        if self.connection_pool:
            await self.connection_pool.close()
    
    async def get_query_embedding(self, query: str) -> Optional[List[float]]:
        """
        Generate embedding for the query using OpenAI API.
        
        Args:
            query: Natural language query
            
        Returns:
            List of floats representing the embedding, or None if unavailable
        """
        if not OPENAI_AVAILABLE:
            print("[DATASET_REC] OpenAI not available for embeddings", file=sys.stderr)
            return None
        
        try:
            import os
            api_key = os.getenv("OPENAI_API_KEY") or os.getenv("SMART_TOOLS_API_KEY")
            if not api_key:
                print("[DATASET_REC] No OpenAI API key available", file=sys.stderr)
                return None
            
            client = openai.OpenAI(api_key=api_key)
            response = client.embeddings.create(
                input=query,
                model="text-embedding-ada-002"
            )
            return response.data[0].embedding
            
        except Exception as e:
            print(f"[DATASET_REC] Error generating embedding: {e}", file=sys.stderr)
            return None
    
    def calculate_field_relevance_score(self, key_fields: List[str], relevant_fields: List[str]) -> float:
        """
        Calculate field relevance score based on key fields overlap.
        
        Args:
            key_fields: Dataset's key fields
            relevant_fields: Query's relevant fields
            
        Returns:
            Score between 0.0 and 1.0
        """
        if not key_fields or not relevant_fields:
            return 0.0
        
        # Convert to sets for intersection
        key_set = set(field.lower() for field in key_fields if field)
        relevant_set = set(relevant_fields)
        
        # Calculate overlap
        intersection = key_set.intersection(relevant_set)
        if not intersection:
            return 0.0
        
        # Score based on percentage of relevant fields found
        return len(intersection) / len(relevant_set)
    
    def calculate_category_bonus(self, dataset_business: str, dataset_technical: str, 
                               query_business: List[str], query_technical: List[str]) -> float:
        """
        Calculate category matching bonus.
        
        Args:
            dataset_business: Dataset's business category
            dataset_technical: Dataset's technical category
            query_business: Query's business categories
            query_technical: Query's technical categories
            
        Returns:
            Score between 0.0 and 1.0
        """
        score = 0.0
        
        # Business category match (higher weight)
        if dataset_business and dataset_business.lower() in [cat.lower() for cat in query_business]:
            score += 0.6
        
        # Technical category match
        if dataset_technical and dataset_technical.lower() in [cat.lower() for cat in query_technical]:
            score += 0.4
        
        return min(score, 1.0)  # Cap at 1.0
    
    def calculate_interface_type_score(self, dataset_interfaces: str, dataset_type: str, 
                                      preferred_interfaces: List[str], preferred_types: List[str]) -> float:
        """
        Calculate interface and type matching score.
        
        Args:
            dataset_interfaces: Dataset's interfaces JSONB field
            dataset_type: Dataset's type (Event, Resource, Interval, Table)
            preferred_interfaces: Query's preferred interfaces
            preferred_types: Query's preferred types
            
        Returns:
            Score between 0.0 and 1.0
        """
        if not preferred_interfaces and not preferred_types:
            return 0.5  # Neutral score if no preferences
        
        interface_score = 0.0
        type_score = 0.0
        
        # Parse interfaces from JSONB
        dataset_interface_paths = set()
        if dataset_interfaces:
            try:
                if isinstance(dataset_interfaces, list):
                    for interface_obj in dataset_interfaces:
                        if isinstance(interface_obj, dict) and 'path' in interface_obj:
                            dataset_interface_paths.add(interface_obj['path'])
            except (TypeError, KeyError):
                pass
        
        # Calculate interface matching score
        if preferred_interfaces:
            interface_matches = 0
            for pref_interface in preferred_interfaces:
                if pref_interface in dataset_interface_paths:
                    interface_matches += 1
                # Special handling for span/otel_span equivalence
                elif pref_interface == 'span' and 'otel_span' in dataset_interface_paths:
                    interface_matches += 1
                elif pref_interface == 'otel_span' and 'span' in dataset_interface_paths:
                    interface_matches += 1
            interface_score = interface_matches / len(preferred_interfaces)
        
        # Calculate type matching score
        if preferred_types and dataset_type:
            dataset_type_lower = dataset_type.lower()
            for pref_type in preferred_types:
                if pref_type.lower() == dataset_type_lower:
                    type_score = 1.0
                    break
        
        # Combine scores with interface weighting higher (interfaces are more specific)
        if preferred_interfaces and preferred_types:
            return interface_score * 0.7 + type_score * 0.3
        elif preferred_interfaces:
            return interface_score
        else:
            return type_score

    def calculate_priority_boost(self, dataset_name: str, intent: QueryIntent) -> float:
        """
        Calculate priority boost for critical datasets.
        
        Args:
            dataset_name: Name of the dataset
            intent: Parsed query intent
            
        Returns:
            Priority boost score (0.0 to 1.0)
        """
        if not dataset_name:
            return 0.0
        
        dataset_name_lower = dataset_name.lower().strip()
        max_boost = 0.0
        
        # Check critical patterns first (exact matches get maximum boost)
        critical_patterns = (
            self.priority_patterns.get('tracing_critical', []) +
            self.priority_patterns.get('logs_critical', []) +
            self.priority_patterns.get('metrics_critical', [])
        )
        
        for pattern in critical_patterns:
            pattern_lower = pattern.lower().strip()
            # Exact match gets maximum boost
            if dataset_name_lower == pattern_lower:
                max_boost = max(max_boost, 1.0)
            # Full pattern contained in dataset name gets high boost  
            elif pattern_lower in dataset_name_lower and len(pattern_lower) > 5:
                max_boost = max(max_boost, 0.9)
        
        # Check high-priority patterns (good boost)
        high_patterns = (
            self.priority_patterns.get('tracing_high', []) +
            self.priority_patterns.get('logs_high', []) +
            self.priority_patterns.get('metrics_high', [])
        )
        
        for pattern in high_patterns:
            pattern_lower = pattern.lower().strip()
            # Exact match gets high boost
            if dataset_name_lower == pattern_lower:
                max_boost = max(max_boost, 0.8)
            # Full pattern contained in dataset name gets moderate boost
            elif pattern_lower in dataset_name_lower and len(pattern_lower) > 5:
                max_boost = max(max_boost, 0.7)
        
        # Query-context specific boosting (only if no high priority already assigned)
        if max_boost < 0.7:
            query_terms = getattr(intent, 'query_terms', [])
            query_lower = ' '.join(query_terms).lower()
            
            # Boost for trace/performance queries + span datasets
            if any(term in query_lower for term in ['trace', 'span', 'latency', 'performance', 'distributed']) and \
               any(term in dataset_name_lower for term in ['span', 'trace']) and \
               'service' not in dataset_name_lower:  # Avoid ServiceExplorer matches
                max_boost = max(max_boost, 0.6)
            
            # Boost for log/error queries + log datasets  
            elif any(term in query_lower for term in ['log', 'logs', 'error', 'debug']) and \
                 any(term in dataset_name_lower for term in ['logs', 'log']) and \
                 'service' not in dataset_name_lower:  # Avoid ServiceExplorer matches
                max_boost = max(max_boost, 0.6)
            
            # Boost for metric queries + metric datasets
            elif any(term in query_lower for term in ['metric', 'metrics', 'monitoring', 'cpu', 'memory']) and \
                 any(term in dataset_name_lower for term in ['metrics', 'metric', 'prometheus']) and \
                 'service' not in dataset_name_lower:  # Avoid ServiceExplorer matches
                max_boost = max(max_boost, 0.6)
        
        return max_boost

    def calculate_name_matching_score(self, dataset_name: str, query_terms: List[str]) -> float:
        """
        Calculate name matching score for exact and partial matches.
        
        Args:
            dataset_name: Name of the dataset
            query_terms: Important terms from the query
            
        Returns:
            Score between 0.0 and 1.0
        """
        if not dataset_name or not query_terms:
            return 0.0
        
        dataset_name_lower = dataset_name.lower()
        matches = 0
        exact_matches = 0
        
        for term in query_terms:
            term_lower = term.lower()
            if term_lower in dataset_name_lower:
                matches += 1
                # Check for exact word boundaries (not just substring)
                if f" {term_lower} " in f" {dataset_name_lower} " or dataset_name_lower.startswith(term_lower) or dataset_name_lower.endswith(term_lower):
                    exact_matches += 1
        
        if matches == 0:
            return 0.0
        
        # Weight exact matches higher
        base_score = matches / len(query_terms)
        exact_bonus = (exact_matches / len(query_terms)) * 0.5
        
        return min(base_score + exact_bonus, 1.0)

    def calculate_schema_score(self, schema_info: Dict, query_terms: List[str]) -> float:
        """
        Calculate schema-based relevance score.
        
        Args:
            schema_info: Dataset's schema information (JSONB)
            query_terms: Important terms from the query
            
        Returns:
            Score between 0.0 and 1.0
        """
        if not schema_info or not query_terms:
            return 0.0
        
        try:
            # Extract field names from schema
            field_names = []
            if isinstance(schema_info, dict):
                # Look for columns or fields
                columns = schema_info.get('columns', [])
                if isinstance(columns, list):
                    field_names.extend([col.get('name', '').lower() for col in columns if isinstance(col, dict)])
            
            if not field_names:
                return 0.0
            
            # Check for query terms in field names
            matches = 0
            for term in query_terms:
                if any(term in field_name for field_name in field_names):
                    matches += 1
            
            return matches / len(query_terms) if query_terms else 0.0
            
        except Exception as e:
            print(f"[DATASET_REC] Error calculating schema score: {e}", file=sys.stderr)
            return 0.0
    
    def generate_match_reasons(self, dataset: Dict, intent: QueryIntent, scores: Dict[str, float]) -> List[str]:
        """
        Generate human-readable explanations for why a dataset was recommended.
        
        Args:
            dataset: Dataset information
            intent: Query intent
            scores: Individual scoring components
            
        Returns:
            List of explanation strings
        """
        reasons = []
        
        # Priority boost (highest priority - for critical datasets)
        if scores.get('priority', 0) > 0.8:
            reasons.append("🔥 Critical dataset for this data type")
        elif scores.get('priority', 0) > 0.5:
            reasons.append("⭐ High-priority dataset for this analysis")
        
        # Interface/Type matching
        if scores.get('interface_type', 0) > 0.7:
            reasons.append("Perfect interface/type match for your query")
        elif scores.get('interface_type', 0) > 0.4:
            reasons.append("Good interface/type match for your query")
        
        # Name matching (second highest priority)
        if scores.get('name', 0) > 0.5:
            reasons.append("Dataset name matches query terms")
        elif scores.get('name', 0) > 0.2:
            reasons.append("Partial name match with query terms")
        
        # Semantic similarity
        if scores.get('semantic', 0) > 0.7:
            reasons.append("High semantic similarity to your query")
        elif scores.get('semantic', 0) > 0.5:
            reasons.append("Moderate semantic similarity to your query")
        
        # Category matches
        if scores.get('category', 0) > 0.5:
            reasons.append(f"Matches {dataset.get('business_category', 'relevant')} domain")
        
        # Field relevance
        if scores.get('field', 0) > 0.3:
            relevant_fields = [f for f in intent.relevant_fields if f in [kf.lower() for kf in dataset.get('key_fields', [])]]
            if relevant_fields:
                reasons.append(f"Contains relevant fields: {', '.join(relevant_fields)}")
        
        # Schema matches
        if scores.get('schema', 0) > 0.3:
            reasons.append("Schema structure matches query requirements")
        
        # Intent-specific reasons
        if intent.intent_type == 'performance' and 'duration' in dataset.get('key_fields', []):
            reasons.append("Suitable for performance analysis")
        elif intent.intent_type == 'errors' and dataset.get('technical_category') in ['Logs', 'Events']:
            reasons.append("Good for error investigation")
        
        return reasons or ["General relevance to your query"]
    
    async def recommend_datasets(
        self, 
        query: str, 
        limit: int = 10,
        min_score: float = 0.1,
        categories: Optional[List[str]] = None
    ) -> List[DatasetRecommendation]:
        """
        Recommend datasets based on natural language query.
        
        Args:
            query: Natural language query
            limit: Maximum number of recommendations
            min_score: Minimum relevance score threshold
            categories: Optional category filter
            
        Returns:
            List of dataset recommendations ordered by relevance
        """
        if not self.connection_pool:
            await self.initialize()
        
        print(f"[DATASET_REC] Processing query: {query[:100]}...", file=sys.stderr)
        
        # Parse query intent
        intent = self.parser.parse_query(query)
        print(f"[DATASET_REC] Parsed intent: {intent.intent_type}, categories: {intent.business_categories + intent.technical_categories}", file=sys.stderr)
        
        # Get query embedding
        intent.embedding = await self.get_query_embedding(query)
        
        try:
            async with self.connection_pool.acquire() as conn:
                # Hybrid approach: Get candidates from both semantic similarity AND name matching
                candidates = []
                
                # Step 1: Get semantic similarity candidates
                if intent.embedding:
                    if categories:
                        semantic_sql = """
                        SELECT 
                            dataset_id, name, dataset_type, business_category, technical_category,
                            key_fields, schema_info, description, interfaces,
                            COALESCE(1 - (combined_embedding <=> $1), 0) as semantic_score
                        FROM dataset_intelligence 
                        WHERE excluded = false AND business_category = ANY($2)
                        ORDER BY semantic_score DESC
                        LIMIT $3
                        """
                        semantic_params = [f"[{','.join(map(str, intent.embedding))}]", categories, limit]
                    else:
                        semantic_sql = """
                        SELECT 
                            dataset_id, name, dataset_type, business_category, technical_category,
                            key_fields, schema_info, description, interfaces,
                            COALESCE(1 - (combined_embedding <=> $1), 0) as semantic_score
                        FROM dataset_intelligence 
                        WHERE excluded = false 
                        ORDER BY semantic_score DESC
                        LIMIT $2
                        """
                        semantic_params = [f"[{','.join(map(str, intent.embedding))}]", limit]
                    
                    semantic_rows = await conn.fetch(semantic_sql, *semantic_params)
                    candidates.extend(semantic_rows)
                
                # Step 2: Get name matching candidates (ensure exact/partial name matches aren't missed)
                if intent.query_terms:
                    # Build name matching query for important query terms
                    name_conditions = []
                    for term in intent.query_terms[:5]:  # Check top 5 important terms
                        if len(term) > 3:  # Only for meaningful terms
                            name_conditions.append(f"LOWER(name) LIKE '%{term.lower()}%'")
                    
                    if name_conditions:
                        name_sql = f"""
                        SELECT DISTINCT
                            dataset_id, name, dataset_type, business_category, technical_category,
                            key_fields, schema_info, description, interfaces,
                            0.7 as semantic_score
                        FROM dataset_intelligence 
                        WHERE excluded = false AND ({' OR '.join(name_conditions)})
                        LIMIT {limit}
                        """
                        name_rows = await conn.fetch(name_sql)
                        candidates.extend(name_rows)
                
                # Step 3: Deduplicate candidates (prefer higher semantic scores)
                seen_ids = {}
                for row in candidates:
                    dataset_id = row['dataset_id']
                    if dataset_id not in seen_ids or row['semantic_score'] > seen_ids[dataset_id]['semantic_score']:
                        seen_ids[dataset_id] = row
                
                rows = list(seen_ids.values())
                print(f"[DATASET_REC] Found {len(rows)} candidate datasets (semantic + name matching)", file=sys.stderr)
                
                recommendations = []
                
                for row in rows:
                    # Calculate individual scoring components
                    semantic_score = float(row['semantic_score']) if intent.embedding else 0.5
                    
                    category_score = self.calculate_category_bonus(
                        row['business_category'], 
                        row['technical_category'],
                        intent.business_categories,
                        intent.technical_categories
                    )
                    
                    field_score = self.calculate_field_relevance_score(
                        row['key_fields'] or [],
                        intent.relevant_fields
                    )
                    
                    schema_score = self.calculate_schema_score(
                        row['schema_info'] if row['schema_info'] else {},
                        intent.query_terms
                    )
                    
                    name_score = self.calculate_name_matching_score(
                        row['name'],
                        intent.query_terms
                    )
                    
                    interface_type_score = self.calculate_interface_type_score(
                        row['interfaces'],
                        row['dataset_type'],
                        intent.preferred_interfaces,
                        intent.preferred_types
                    )
                    
                    # Calculate priority boost for critical datasets
                    priority_boost = self.calculate_priority_boost(row['name'], intent)
                    
                    # Combined scoring with weights (adjusted to include priority boost)
                    base_score = (
                        semantic_score * 0.25 +         # Semantic similarity (reduced to make room for priority)
                        category_score * 0.20 +         # Category matching
                        field_score * 0.15 +            # Field relevance
                        schema_score * 0.05 +           # Schema intelligence
                        name_score * 0.15 +             # Name matching
                        interface_type_score * 0.15     # Interface/type matching
                    )
                    
                    # Apply priority boost (can increase score significantly for critical datasets)
                    # Critical datasets get much stronger boost to ensure they float to top
                    if priority_boost >= 0.9:  # Critical datasets
                        relevance_score = base_score + (priority_boost * 0.45)  # Up to 45% boost for critical
                    elif priority_boost >= 0.7:  # High priority datasets  
                        relevance_score = base_score + (priority_boost * 0.35)  # Up to 35% boost for high priority
                    else:  # Moderate priority
                        relevance_score = base_score + (priority_boost * 0.25)  # Up to 25% boost for moderate
                    
                    # Skip if below minimum threshold
                    if relevance_score < min_score:
                        continue
                    
                    # Generate explanations
                    scores = {
                        'semantic': semantic_score,
                        'category': category_score,
                        'field': field_score,
                        'schema': schema_score,
                        'name': name_score,
                        'interface_type': interface_type_score,
                        'priority': priority_boost
                    }
                    
                    match_reasons = self.generate_match_reasons(row, intent, scores)
                    
                    # Extract sample fields from schema
                    sample_fields = {}
                    if row['schema_info']:
                        try:
                            schema = row['schema_info']
                            if isinstance(schema, dict):
                                columns = schema.get('columns', [])[:5]  # First 5 fields
                                for col in columns:
                                    if isinstance(col, dict) and 'name' in col and 'type' in col:
                                        sample_fields[col['name']] = col['type']
                        except Exception:
                            pass
                    
                    recommendations.append(DatasetRecommendation(
                        dataset_id=row['dataset_id'],
                        name=row['name'],
                        dataset_type=row['dataset_type'],
                        business_category=row['business_category'] or 'Unknown',
                        technical_category=row['technical_category'] or 'Unknown',
                        key_fields=list(row['key_fields']) if row['key_fields'] else [],
                        relevance_score=relevance_score,
                        match_reasons=match_reasons,
                        sample_fields=sample_fields,
                        description=row['description']
                    ))
                
                # Sort by relevance score and limit
                recommendations.sort(key=lambda x: x.relevance_score, reverse=True)
                final_recommendations = recommendations[:limit]
                
                print(f"[DATASET_REC] Returning {len(final_recommendations)} recommendations", file=sys.stderr)
                return final_recommendations
                
        except Exception as e:
            print(f"[DATASET_REC] Error in recommendation query: {e}", file=sys.stderr)
            import traceback
            traceback.print_exc(file=sys.stderr)
            return []


# Global instance
_recommendation_engine = None


async def get_recommendation_engine() -> DatasetRecommendationEngine:
    """Get or create the global recommendation engine instance."""
    global _recommendation_engine
    
    if _recommendation_engine is None:
        import os
        db_config = {
            'host': os.getenv('POSTGRES_HOST', 'localhost'),
            'port': int(os.getenv('POSTGRES_PORT', 5432)),
            'database': os.getenv('POSTGRES_DB', 'opal_memory'),
            'user': os.getenv('POSTGRES_USER', 'opal'),
            'password': os.getenv('POSTGRES_PASSWORD', '')
        }
        
        _recommendation_engine = DatasetRecommendationEngine(db_config)
        await _recommendation_engine.initialize()
    
    return _recommendation_engine


async def query_semantic_graph(
    query: str,
    limit: int = 10,
    min_score: float = 0.1,
    categories: Optional[List[str]] = None
) -> List[DatasetRecommendation]:
    """
    Main function to recommend datasets based on natural language query.
    
    Args:
        query: Natural language query describing what data you're looking for
        limit: Maximum number of recommendations to return
        min_score: Minimum relevance score threshold (0.0-1.0)
        categories: Optional list of business categories to filter by
        
    Returns:
        List of DatasetRecommendation objects ordered by relevance
        
    Examples:
        recommendations = await query_semantic_graph(
            "Show me service error rates and performance issues"
        )
        
        recommendations = await query_semantic_graph(
            "Find CPU and memory usage for containers",
            categories=["Infrastructure"]
        )
    """
    engine = await get_recommendation_engine()
    return await engine.recommend_datasets(query, limit, min_score, categories)
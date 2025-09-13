#!/usr/bin/env python3
"""
Datasets Intelligence Script

This script analyzes datasets in Observe to create rich metadata for fast semantic search.
It uses rule-based analysis instead of LLM embeddings for speed and reliability.

Usage:
    python datasets_intelligence.py --help
"""

import asyncio
import json
import logging
import os
import sys
import argparse
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Any, Tuple, Set
import asyncpg
import httpx
from dotenv import load_dotenv

# ANSI color codes for terminal output
class Colors:
    RED = '\033[91m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    MAGENTA = '\033[95m'
    CYAN = '\033[96m'
    WHITE = '\033[97m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'
    RESET = '\033[0m'
    
    # Background colors
    BG_RED = '\033[101m'
    BG_GREEN = '\033[102m'
    BG_YELLOW = '\033[103m'
    BG_BLUE = '\033[104m'

class ColoredFormatter(logging.Formatter):
    """Custom formatter that adds colors to log messages based on level and content."""
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # Color mapping for log levels
        self.level_colors = {
            logging.DEBUG: Colors.CYAN,
            logging.INFO: Colors.WHITE,
            logging.WARNING: Colors.YELLOW,
            logging.ERROR: Colors.RED,
            logging.CRITICAL: Colors.RED + Colors.BOLD
        }
        
        # Special patterns for highlighting key events
        self.event_patterns = {
            'unchanged - skipping': Colors.GREEN + Colors.BOLD,
            'has changed - performing': Colors.BLUE + Colors.BOLD,
            'not found in database': Colors.MAGENTA + Colors.BOLD,
            'Excluding dataset': Colors.YELLOW,
            'Successfully analyzed': Colors.GREEN,
            'Progress:': Colors.CYAN + Colors.BOLD,
            'Analysis Statistics': Colors.YELLOW + Colors.BOLD + Colors.UNDERLINE,
            'Database connection established': Colors.GREEN + Colors.BOLD,
            'Dataset analysis completed': Colors.GREEN + Colors.BOLD + Colors.UNDERLINE,
            'Discovered': Colors.CYAN,
            'Failed': Colors.RED + Colors.BOLD,
            'Error': Colors.RED + Colors.BOLD,
            'has no data': Colors.RED,
            'checking for data': Colors.CYAN,
            'has data - analyzing': Colors.GREEN + Colors.BOLD,
        }
    
    def format(self, record):
        # Format the message first
        message = super().format(record)
        
        # Apply level-based coloring
        level_color = self.level_colors.get(record.levelno, Colors.WHITE)
        
        # Check for special event patterns and apply specific colors
        colored_message = message
        for pattern, color in self.event_patterns.items():
            if pattern in message:
                colored_message = colored_message.replace(
                    pattern, 
                    f"{color}{pattern}{Colors.RESET}"
                )
        
        # Apply level color to the entire message if no special pattern matched
        if colored_message == message:
            colored_message = f"{level_color}{message}{Colors.RESET}"
        
        return colored_message

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class DatasetsIntelligenceAnalyzer:
    """Analyzes datasets and generates intelligence for fast semantic search."""
    
    def __init__(self):
        # Database connection
        self.db_pool = None
        
        # Observe API configuration
        self.observe_customer_id = os.getenv('OBSERVE_CUSTOMER_ID')
        self.observe_token = os.getenv('OBSERVE_TOKEN')
        self.observe_domain = os.getenv('OBSERVE_DOMAIN', 'observeinc.com')
        
        # HTTP client for Observe API
        self.http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(60.0, connect=10.0, read=60.0),
            headers={
                'Authorization': f'Bearer {self.observe_customer_id} {self.observe_token}',
                'Content-Type': 'application/json'
            }
        )
        
        # Statistics
        self.stats = {
            'datasets_processed': 0,
            'datasets_skipped': 0,
            'datasets_failed': 0,
            'datasets_excluded': 0,
            'datasets_empty': 0
        }
        
        # Rate limiting configuration
        self.last_observe_call = 0
        self.observe_delay = 0.2  # 200ms between Observe API calls
        self.max_retries = 3
        self.base_retry_delay = 1.0

        # Force mode flag
        self.force_mode = False
    
    async def rate_limit_observe(self) -> None:
        """Apply rate limiting for Observe API calls."""
        elapsed = time.time() - self.last_observe_call
        if elapsed < self.observe_delay:
            await asyncio.sleep(self.observe_delay - elapsed)
        self.last_observe_call = time.time()
    
    async def retry_with_backoff(self, func, *args, **kwargs):
        """Retry a function with exponential backoff."""
        for attempt in range(self.max_retries):
            try:
                return await func(*args, **kwargs)
            except Exception as e:
                if attempt == self.max_retries - 1:
                    raise e
                
                wait_time = self.base_retry_delay * (2 ** attempt)
                
                if "timeout" in str(e).lower() or "429" in str(e):
                    wait_time *= 2
                elif "502" in str(e) or "503" in str(e) or "504" in str(e):
                    wait_time *= 1.5
                
                logger.warning(f"Attempt {attempt + 1}/{self.max_retries} failed: {e}. Retrying in {wait_time:.1f}s...")
                await asyncio.sleep(wait_time)
    
    async def initialize_database(self) -> None:
        """Initialize database connection and ensure schema exists."""
        db_config = {
            'host': os.getenv('POSTGRES_HOST', 'localhost'),
            'port': int(os.getenv('POSTGRES_PORT', '5432')),
            'database': os.getenv('POSTGRES_DB', 'semantic_graph'),
            'user': os.getenv('POSTGRES_USER', 'semantic_graph'),
            'password': os.getenv('SEMANTIC_GRAPH_PASSWORD', 'g83hbeyB32792r3Gsjnfwe0ihf2')
        }
        
        try:
            self.db_pool = await asyncpg.create_pool(**db_config, min_size=1, max_size=5)
            logger.info("Database connection established")
            
            # Create schema if it doesn't exist
            await self.ensure_schema_exists()
            
        except Exception as e:
            logger.error(f"Failed to connect to database: {e}")
            raise
    
    async def ensure_schema_exists(self) -> None:
        """Ensure the datasets intelligence schema exists."""
        # Get the absolute path to the schema file
        script_dir = os.path.dirname(os.path.abspath(__file__))
        schema_path = os.path.join(script_dir, '..', 'sql', 'datasets_intelligence_schema.sql')
        
        with open(schema_path, 'r') as f:
            schema_sql = f.read()
        
        async with self.db_pool.acquire() as conn:
            await conn.execute(schema_sql)
            logger.info("Datasets intelligence schema created/verified")
    
    def should_exclude_dataset(self, dataset: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        """
        Determine if a dataset should be excluded from analysis.
        Based on the original dataset_intelligence.py patterns.
        """
        config = dataset.get('config', {})
        state = dataset.get('state', {})
        
        name = config.get('name', '').lower()
        interfaces = state.get('interfaces', [])
        
        # Monitor datasets - expanded patterns
        monitor_patterns = [
            'monitor/', 'monitor-', 'slo/monitor', '/monitor', 'monitor ',
            'usage/monitor', '/slo', 'slo ', ' slo'
        ]
        if any(pattern in name for pattern in monitor_patterns):
            return True, "monitor_dataset"
        
        # Additional SLO and monitoring keywords
        monitoring_keywords = ['monitoring', ' slo', 'slo/']
        if any(keyword in name for keyword in monitoring_keywords):
            return True, "monitor_dataset"
        
        # Notification interfaces - check interface paths
        notification_interfaces = ['action_notification', 'materialized_notification']
        interface_paths = []
        if interfaces:
            for iface in interfaces:
                if isinstance(iface, dict) and 'path' in iface:
                    interface_paths.append(iface['path'])
        
        if any(iface in interface_paths for iface in notification_interfaces):
            return True, "notification_interface"
            
        # SMA (Simple Moving Average) derived datasets
        if 'metric-sma-for-' in name:
            return True, "derived_metric"
            
        # Internal/system datasets
        internal_patterns = ['_internal', 'system_', 'usage/', '_system']
        if any(pattern in name for pattern in internal_patterns):
            return True, "internal_system"
        
        return False, None
    
    async def fetch_all_datasets(self) -> List[Dict[str, Any]]:
        """Fetch all datasets from Observe API."""
        url = f"https://{self.observe_customer_id}.{self.observe_domain}/v1/dataset"
        
        async def _fetch():
            await self.rate_limit_observe()
            response = await self.http_client.get(url)
            response.raise_for_status()
            
            data = response.json()
            datasets = data.get('data', [])
            logger.info(f"Discovered {len(datasets)} datasets from Observe")
            return datasets
        
        try:
            return await self.retry_with_backoff(_fetch)
        except Exception as e:
            logger.error(f"Failed to fetch datasets after retries: {e}")
            raise
    
    async def check_dataset_needs_update(self, dataset_id: str, name: str, dataset_type: str, interfaces: List[str]) -> bool:
        """
        Check if a dataset needs to be updated based on existing database record.
        Returns True if dataset needs analysis, False if it can be skipped.
        """
        # Force mode: always analyze
        if self.force_mode:
            return True

        try:
            async with self.db_pool.acquire() as conn:
                # Check if dataset exists and when it was last analyzed
                result = await conn.fetchrow("""
                    SELECT dataset_name, dataset_type, interface_types, last_analyzed
                    FROM datasets_intelligence 
                    WHERE dataset_id = $1
                """, dataset_id)
                
                if not result:
                    # Dataset doesn't exist, needs analysis
                    logger.debug(f"Dataset {dataset_id} not found in database, needs analysis")
                    return True
                
                # Check if core attributes have changed
                if result['dataset_name'] != name:
                    logger.info(f"Dataset {dataset_id} name changed: '{result['dataset_name']}' -> '{name}'")
                    return True
                
                if result['dataset_type'] != dataset_type:
                    logger.info(f"Dataset {dataset_id} type changed: '{result['dataset_type']}' -> '{dataset_type}'")
                    return True
                
                # Check interface changes
                existing_interfaces = result['interface_types'] or []
                if set(existing_interfaces) != set(interfaces):
                    logger.info(f"Dataset {dataset_id} interfaces changed: {existing_interfaces} -> {interfaces}")
                    return True
                
                # Check if analyzed within last 7 days
                if result['last_analyzed']:
                    # Use timezone-naive datetime for comparison (database stores timezone-naive)
                    days_since_analysis = (datetime.now() - result['last_analyzed']).total_seconds() / (24 * 3600)
                    if days_since_analysis < 7:
                        logger.info(f"Skipping {name} - analyzed {days_since_analysis:.1f} days ago")
                        self.stats['datasets_skipped'] += 1
                        return False
                
                # If we get here, dataset exists but needs refresh
                logger.debug(f"Dataset {dataset_id} needs refresh")
                return True
                
        except Exception as e:
            logger.warning(f"Error checking dataset update status for {dataset_id}: {e}")
            # If we can't check, err on the side of updating
            return True
    
    async def check_dataset_has_data(self, dataset_id: str, dataset_type: str) -> bool:
        """Check if a dataset has any data over the last 24 hours."""
        # Use different OPAL verbs based on dataset type
        if dataset_type == "Resource":
            query = "topk 1"
        else:
            query = "limit 1"
        
        url = f"https://{self.observe_customer_id}.{self.observe_domain}/v1/meta/export/query"
        
        payload = {
            "query": {
                "stages": [
                    {
                        "input": [
                            {
                                "inputName": "main",
                                "datasetId": dataset_id
                            }
                        ],
                        "stageID": "query_stage",
                        "pipeline": query
                    }
                ]
            },
            "rowCount": "1"
        }
        
        # Check 24-hour window for data
        params = {"interval": "24h"}
        
        async def _check_data():
            logger.debug(f"checking for data in dataset {dataset_id} (type: {dataset_type}) over 24h")
            
            await self.rate_limit_observe()
            response = await self.http_client.post(url, json=payload, params=params)
            
            if response.status_code != 200:
                logger.debug(f"Data check failed for dataset {dataset_id}: {response.status_code}")
                return False
                
            # Check if response has any data
            content_type = response.headers.get('content-type', '')
            response_text = response.text
            
            if not response_text or len(response_text.strip()) == 0:
                logger.debug(f"Dataset {dataset_id} has no data: empty response")
                return False
            
            if 'text/csv' in content_type:
                csv_data = response_text.strip()
                lines = csv_data.split('\n')
                # Has data if more than just header
                has_data = len(lines) > 1 and len(lines[1].strip()) > 0
                logger.debug(f"Dataset {dataset_id} has data: {has_data} (CSV lines: {len(lines)})")
                return has_data
                
            elif 'application/x-ndjson' in content_type or 'application/json' in content_type:
                # Handle NDJSON format
                ndjson_data = response_text.strip()
                lines = [line.strip() for line in ndjson_data.split('\n') if line.strip()]
                
                if lines:
                    try:
                        first_obj = json.loads(lines[0])
                        has_data = len(lines) > 0
                        logger.debug(f"Dataset {dataset_id} has data: {has_data} (NDJSON lines: {len(lines)})")
                        return has_data
                    except json.JSONDecodeError as e:
                        logger.debug(f"Failed to parse NDJSON for dataset {dataset_id}: {e}")
                        return False
                else:
                    logger.debug(f"Dataset {dataset_id} has no data: empty NDJSON response")
                    return False
            else:
                logger.debug(f"Dataset {dataset_id} unexpected content type: {content_type}")
                return False
        
        try:
            return await self.retry_with_backoff(_check_data)
        except Exception as e:
            logger.warning(f"Failed to check data for dataset {dataset_id} after retries: {e}")
            return True  # Default to including dataset if we can't check

    def expand_keywords(self, name_lower: str) -> Set[str]:
        """Expand keywords from dataset name for better matching."""
        expanded_keywords = set()

        # Add original words
        words = name_lower.replace('/', ' ').replace('-', ' ').replace('_', ' ').split()
        expanded_keywords.update(words)

        # Add common abbreviations and expansions
        keyword_expansions = {
            'k8s': ['kubernetes', 'k8s', 'kube'],
            'kubernetes': ['kubernetes', 'k8s', 'kube', 'container', 'pod'],
            'app': ['application', 'app', 'service'],
            'application': ['application', 'app', 'service'],
            'db': ['database', 'db', 'sql'],
            'database': ['database', 'db', 'sql'],
            'auth': ['authentication', 'auth', 'security'],
            'svc': ['service', 'svc', 'app'],
            'service': ['service', 'svc', 'app', 'application'],
            'otel': ['opentelemetry', 'otel', 'trace', 'span'],
            'opentelemetry': ['opentelemetry', 'otel', 'trace', 'span'],
            'log': ['logs', 'log', 'logging'],
            'logs': ['logs', 'log', 'logging'],
            'metric': ['metrics', 'metric', 'monitoring'],
            'metrics': ['metrics', 'metric', 'monitoring'],
            'infra': ['infrastructure', 'infra', 'system'],
            'infrastructure': ['infrastructure', 'infra', 'system'],
            'host': ['host', 'node', 'server', 'machine'],
            'node': ['node', 'host', 'server', 'machine'],
            'network': ['network', 'net', 'connection', 'traffic'],
            'net': ['network', 'net', 'connection'],
            'user': ['user', 'customer', 'session'],
            'error': ['error', 'exception', 'failure', 'issue'],
            'perf': ['performance', 'perf', 'latency', 'speed'],
            'performance': ['performance', 'perf', 'latency', 'speed'],
        }

        # Apply expansions
        for word in list(expanded_keywords):
            if word in keyword_expansions:
                expanded_keywords.update(keyword_expansions[word])

        return expanded_keywords

    def categorize_with_enhanced_matching(self, name_lower: str, expanded_keywords: Set[str], interfaces: List[str], dataset_type: str) -> Tuple[str, str]:
        """Enhanced categorization using expanded keywords."""

        # Enhanced business category matching with expanded keywords
        business_patterns = {
            "Infrastructure": {
                'primary': ['kubernetes', 'k8s', 'host', 'infrastructure', 'system', 'container', 'node', 'server', 'machine', 'infra'],
                'secondary': ['pod', 'cluster', 'deployment', 'hardware', 'vm', 'virtualization']
            },
            "Application": {
                'primary': ['service', 'application', 'app', 'opentelemetry', 'span', 'trace', 'otel'],
                'secondary': ['api', 'web', 'microservice', 'frontend', 'backend', 'endpoint']
            },
            "Database": {
                'primary': ['database', 'db', 'sql', 'query', 'postgres', 'mysql', 'redis'],
                'secondary': ['table', 'schema', 'transaction', 'index', 'collection']
            },
            "User": {
                'primary': ['user', 'journey', 'hero', 'session', 'cdp', 'customer'],
                'secondary': ['visitor', 'behavior', 'interaction', 'engagement', 'conversion']
            },
            "Network": {
                'primary': ['network', 'connection', 'traffic', 'net', 'tcp', 'http'],
                'secondary': ['bandwidth', 'packet', 'protocol', 'dns', 'load', 'proxy']
            },
            "Storage": {
                'primary': ['storage', 'volume', 'disk', 'filesystem', 'file'],
                'secondary': ['backup', 'archive', 'blob', 'object', 'bucket']
            },
            "Security": {
                'primary': ['security', 'auth', 'permission', 'authentication', 'authorization'],
                'secondary': ['token', 'certificate', 'encryption', 'audit', 'compliance']
            },
            "Monitoring": {
                'primary': ['monitor', 'alert', 'slo', 'sli', 'health'],
                'secondary': ['check', 'probe', 'status', 'notification', 'threshold']
            },
            "Business": {
                'primary': ['business', 'revenue', 'financial', 'sales', 'billing'],
                'secondary': ['order', 'payment', 'invoice', 'transaction', 'commerce']
            }
        }

        business_scores = {}
        for category, patterns in business_patterns.items():
            score = 0
            # Primary keywords get higher weight
            for keyword in patterns['primary']:
                if keyword in expanded_keywords or keyword in name_lower:
                    score += 2
            # Secondary keywords get lower weight
            for keyword in patterns['secondary']:
                if keyword in expanded_keywords or keyword in name_lower:
                    score += 1
            business_scores[category] = score

        # Get business category with highest score
        business_category = max(business_scores, key=business_scores.get) if max(business_scores.values()) > 0 else "Infrastructure"

        # Enhanced technical category matching
        technical_patterns = {
            "Logs": {
                'interfaces': ['log'],
                'keywords': ['log', 'logs', 'logging', 'syslog', 'audit'],
                'weight': 3
            },
            "Metrics": {
                'interfaces': ['metric', 'metric_metadata'],
                'keywords': ['metric', 'metrics', 'monitoring', 'gauge', 'counter', 'histogram'],
                'weight': 3
            },
            "Traces": {
                'interfaces': ['otel_span'],
                'keywords': ['span', 'trace', 'tracing', 'opentelemetry', 'otel'],
                'weight': 3
            },
            "Resources": {
                'interfaces': [],
                'keywords': ['resource', 'inventory', 'config', 'configuration'],
                'weight': 2
            },
            "Sessions": {
                'interfaces': [],
                'keywords': ['session', 'journey', 'user', 'visitor'],
                'weight': 2
            },
            "Alerts": {
                'interfaces': [],
                'keywords': ['alert', 'notification', 'alarm', 'warning'],
                'weight': 2
            },
            "Events": {
                'interfaces': [],
                'keywords': ['event', 'activity', 'action', 'occurrence'],
                'weight': 1
            }
        }

        technical_scores = {}
        for category, pattern in technical_patterns.items():
            score = 0
            # Interface matching gets highest priority
            if any(iface in interfaces for iface in pattern['interfaces']):
                score += pattern['weight'] * 2
            # Keyword matching
            if any(keyword in expanded_keywords or keyword in name_lower for keyword in pattern['keywords']):
                score += pattern['weight']
            technical_scores[category] = score

        # Handle dataset type-based categorization
        if not max(technical_scores.values()):
            if dataset_type == "Resource":
                technical_category = "Resources"
            elif dataset_type == "Interval":
                if any(keyword in expanded_keywords for keyword in ['session', 'journey', 'user']):
                    technical_category = "Sessions"
                else:
                    technical_category = "Events"
            else:
                technical_category = "Events"
        else:
            technical_category = max(technical_scores, key=technical_scores.get)

        return business_category, technical_category

    async def generate_dataset_analysis(self, name: str, dataset_type: str, interfaces: List[str]) -> Dict[str, Any]:
        """Generate enhanced rule-based analysis with better keyword matching."""

        # Normalize and expand keywords
        name_lower = name.lower()
        expanded_keywords = self.expand_keywords(name_lower)

        # Enhanced categorization
        business_category, technical_category = self.categorize_with_enhanced_matching(
            name_lower, expanded_keywords, interfaces, dataset_type
        )
        
        # Generate purpose and usage based on patterns
        if 'logs' in name_lower:
            purpose = f"Contains log entries from {name.split('/')[0] if '/' in name else name}"
            usage = "Debug issues, trace request flows, analyze error patterns, monitor system health"
        elif 'metrics' in name_lower or 'metric' in interfaces:
            purpose = f"Contains performance metrics from {name.split('/')[0] if '/' in name else name}"
            usage = "Monitor performance trends, set up alerts, analyze resource utilization, track SLA compliance"
        elif 'span' in name_lower or 'trace' in name_lower:
            purpose = f"Contains distributed tracing data from {name.split('/')[0] if '/' in name else name}"
            usage = "Trace request flows, analyze service dependencies, debug latency issues, monitor service performance"
        elif dataset_type == "Resource":
            purpose = f"Contains resource information for {name.split('/')[0] if '/' in name else name}"
            usage = "Inventory management, resource utilization analysis, capacity planning, configuration tracking"
        else:
            purpose = f"Contains {technical_category.lower()} data for {business_category.lower()} monitoring"
            usage = f"Investigate {business_category.lower()} issues, analyze {technical_category.lower()} patterns, troubleshoot system problems"
        
        # Generate common use cases based on category
        common_use_cases = []
        if technical_category == "Logs":
            common_use_cases = [
                "Error investigation and debugging",
                "Request flow tracing",
                "Security incident analysis",
                "Performance troubleshooting"
            ]
        elif technical_category == "Metrics":
            common_use_cases = [
                "Performance monitoring and alerting",
                "Resource utilization analysis", 
                "SLA compliance tracking",
                "Capacity planning"
            ]
        elif technical_category == "Traces":
            common_use_cases = [
                "End-to-end request tracing",
                "Service dependency mapping",
                "Latency root cause analysis",
                "Performance optimization"
            ]
        else:
            common_use_cases = [
                f"{business_category} monitoring",
                "Issue investigation",
                "Trend analysis",
                "System health checks"
            ]
        
        return {
            "inferred_purpose": purpose,
            "typical_usage": usage,
            "business_category": business_category,
            "technical_category": technical_category,
            "common_use_cases": common_use_cases,
            "data_frequency": "medium"  # Default, could be enhanced with actual data analysis
        }
    
    async def store_dataset_intelligence(self, dataset_data: Dict[str, Any]) -> None:
        """Store dataset intelligence in the database."""
        async with self.db_pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO datasets_intelligence (
                    dataset_id, dataset_name, dataset_type, workspace_id, interface_types,
                    business_category, technical_category, inferred_purpose, typical_usage,
                    key_fields, common_use_cases, data_frequency, first_seen, last_seen,
                    excluded, exclusion_reason, confidence_score, last_analyzed
                ) VALUES (
                    $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18
                ) ON CONFLICT (dataset_id) DO UPDATE SET
                    dataset_name = EXCLUDED.dataset_name,
                    dataset_type = EXCLUDED.dataset_type,
                    workspace_id = EXCLUDED.workspace_id,
                    interface_types = EXCLUDED.interface_types,
                    business_category = EXCLUDED.business_category,
                    technical_category = EXCLUDED.technical_category,
                    inferred_purpose = EXCLUDED.inferred_purpose,
                    typical_usage = EXCLUDED.typical_usage,
                    key_fields = EXCLUDED.key_fields,
                    common_use_cases = EXCLUDED.common_use_cases,
                    data_frequency = EXCLUDED.data_frequency,
                    last_seen = EXCLUDED.last_seen,
                    excluded = EXCLUDED.excluded,
                    exclusion_reason = EXCLUDED.exclusion_reason,
                    confidence_score = EXCLUDED.confidence_score,
                    last_analyzed = EXCLUDED.last_analyzed,
                    updated_at = NOW()
            """, *[
                dataset_data['dataset_id'],
                dataset_data['dataset_name'],
                dataset_data['dataset_type'],
                dataset_data['workspace_id'],
                dataset_data['interface_types'],
                dataset_data['business_category'],
                dataset_data['technical_category'],
                dataset_data['inferred_purpose'],
                dataset_data['typical_usage'],
                dataset_data['key_fields'],
                dataset_data['common_use_cases'],
                dataset_data['data_frequency'],
                dataset_data['first_seen'],
                dataset_data['last_seen'],
                dataset_data['excluded'],
                dataset_data['exclusion_reason'],
                dataset_data['confidence_score'],
                datetime.now()  # Use timezone-naive to match database schema
            ])
    
    async def analyze_dataset(self, dataset: Dict[str, Any]) -> None:
        """Analyze a single dataset and store intelligence."""
        # Extract dataset information
        meta = dataset.get('meta', {})
        config = dataset.get('config', {})
        state = dataset.get('state', {})
        
        dataset_id = meta.get('id', '').replace('o::', '').split(':')[-1]
        name = config.get('name', '')
        dataset_type = state.get('kind', '')
        workspace_id = meta.get('workspaceId', '')
        interfaces = state.get('interfaces', [])
        
        if not dataset_id or not name:
            logger.warning(f"Skipping dataset with empty ID or name: id='{dataset_id}', name='{name}'")
            self.stats['datasets_failed'] += 1
            return
        
        # Extract interface types
        interface_types = []
        if interfaces:
            for iface in interfaces:
                if isinstance(iface, dict) and 'path' in iface:
                    interface_types.append(iface['path'])
        
        logger.info(f"Analyzing dataset: {name} ({dataset_id})")
        
        try:
            # Check if should be excluded
            excluded, exclusion_reason = self.should_exclude_dataset(dataset)
            
            if excluded:
                logger.info(f"Excluding dataset {name}: {exclusion_reason}")
                await self.store_dataset_intelligence({
                    'dataset_id': dataset_id,
                    'dataset_name': name,
                    'dataset_type': dataset_type,
                    'workspace_id': workspace_id,
                    'interface_types': interface_types,
                    'business_category': '',
                    'technical_category': '',
                    'inferred_purpose': '',
                    'typical_usage': '',
                    'key_fields': [],
                    'common_use_cases': [],
                    'data_frequency': '',
                    'first_seen': datetime.now(),
                    'last_seen': datetime.now(),
                    'excluded': True,
                    'exclusion_reason': exclusion_reason,
                    'confidence_score': 1.0
                })
                self.stats['datasets_excluded'] += 1
                return
            
            # Check if dataset needs update (skip if analyzed recently)
            needs_update = await self.check_dataset_needs_update(dataset_id, name, dataset_type, interface_types)
            if not needs_update:
                return
            
            # Check if dataset has data
            logger.info(f"Dataset {name} checking for data availability")
            has_data = await self.check_dataset_has_data(dataset_id, dataset_type)
            
            if not has_data:
                logger.info(f"Dataset {name} has no data - skipping")
                self.stats['datasets_empty'] += 1
                return
            
            logger.info(f"Dataset {name} has data - analyzing")
            
            # Generate rule-based analysis
            analysis = await self.generate_dataset_analysis(name, dataset_type, interface_types)
            
            # Store dataset intelligence
            await self.store_dataset_intelligence({
                'dataset_id': dataset_id,
                'dataset_name': name,
                'dataset_type': dataset_type,
                'workspace_id': workspace_id,
                'interface_types': interface_types,
                'business_category': analysis['business_category'],
                'technical_category': analysis['technical_category'],
                'inferred_purpose': analysis['inferred_purpose'],
                'typical_usage': analysis['typical_usage'],
                'key_fields': [],  # TODO: Could be enhanced with schema analysis
                'common_use_cases': analysis['common_use_cases'],
                'data_frequency': analysis['data_frequency'],
                'first_seen': datetime.now(),  # TODO: Could be enhanced with actual timestamps
                'last_seen': datetime.now(),
                'excluded': False,
                'exclusion_reason': None,
                'confidence_score': 1.0
            })
            
            self.stats['datasets_processed'] += 1
            logger.info(f"Successfully analyzed dataset: {name}")
            
        except Exception as e:
            logger.error(f"Failed to analyze dataset {name}: {e}")
            self.stats['datasets_failed'] += 1
    
    async def analyze_all_datasets(self, limit: Optional[int] = None) -> None:
        """Analyze all datasets from Observe."""
        # Print startup banner
        logger.info("")
        logger.info("╔═══════════════════════════════════════════════════════════════╗")
        logger.info("║              🗄️  Datasets Intelligence Analyzer               ║")
        logger.info("║                                                               ║")
        logger.info("║  Analyzing Observe datasets for fast semantic discovery      ║")
        if self.force_mode:
            logger.info("║                    🧹 FORCE MODE ENABLED 🧹                    ║")
        logger.info("╚═══════════════════════════════════════════════════════════════╝")
        logger.info("")
        logger.info("🚀 Starting dataset analysis...")
        
        # Fetch all datasets
        datasets = await self.fetch_all_datasets()
        
        if limit:
            datasets = datasets[:limit]
            logger.info(f"Limited analysis to {limit} datasets")
        
        # Process datasets
        for i, dataset in enumerate(datasets):
            logger.info(f"Progress: {i+1}/{len(datasets)}")
            await self.analyze_dataset(dataset)
            
            # Add delay to avoid overwhelming APIs
            await asyncio.sleep(1.0)
        
        logger.info("Dataset analysis completed")
        self.print_statistics()
    
    def print_statistics(self) -> None:
        """Print analysis statistics."""
        logger.info("")
        logger.info("╔═══════════════════════════════════════════════════════════════╗")
        logger.info("║                    📈 Dataset Analysis Statistics            ║")
        logger.info("╠═══════════════════════════════════════════════════════════════╣")
        logger.info(f"║ Datasets processed: {self.stats['datasets_processed']:>35} ║")
        logger.info(f"║ Datasets skipped: {self.stats['datasets_skipped']:>37} ║")
        logger.info(f"║ Datasets excluded: {self.stats['datasets_excluded']:>36} ║")
        logger.info(f"║ Datasets empty: {self.stats['datasets_empty']:>39} ║")
        logger.info(f"║ Datasets failed: {self.stats['datasets_failed']:>38} ║")
        logger.info("╚═══════════════════════════════════════════════════════════════╝")
        logger.info("")
    
    async def clear_database(self) -> None:
        """Clear all data from datasets_intelligence table for fresh start."""
        async with self.db_pool.acquire() as conn:
            result = await conn.execute("DELETE FROM datasets_intelligence")
            count = result.split()[-1] if result else "0"
            logger.info(f"🧹 Cleared {count} existing records from database")

    async def cleanup(self) -> None:
        """Cleanup resources."""
        if self.http_client:
            await self.http_client.aclose()
        if self.db_pool:
            await self.db_pool.close()

async def main():
    parser = argparse.ArgumentParser(description="Analyze Observe datasets for fast semantic search")
    parser.add_argument('--limit', type=int, help='Limit number of datasets to analyze')
    parser.add_argument('--verbose', action='store_true', help='Enable verbose logging')
    parser.add_argument('--force', action='store_true', help='Force clean database and reprocess all datasets from scratch')

    args = parser.parse_args()
    
    # Configure colored logging
    handler = logging.StreamHandler()
    formatter = ColoredFormatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    handler.setFormatter(formatter)
    
    # Set up root logger
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(logging.INFO)
    
    if args.verbose:
        root_logger.setLevel(logging.DEBUG)
    
    # Reduce noise from HTTP libraries unless in verbose mode
    if not args.verbose:
        logging.getLogger('httpx').setLevel(logging.WARNING)
        logging.getLogger('httpcore').setLevel(logging.WARNING)
    
    analyzer = DatasetsIntelligenceAnalyzer()
    
    try:
        await analyzer.initialize_database()

        # Set force mode
        analyzer.force_mode = args.force

        # Clear database if force mode is enabled
        if args.force:
            logger.info("🧹 Force mode enabled - clearing database...")
            await analyzer.clear_database()

        await analyzer.analyze_all_datasets(limit=args.limit)
        
    except KeyboardInterrupt:
        logger.info("Analysis interrupted by user")
    except Exception as e:
        logger.error(f"Analysis failed: {e}")
        raise
    finally:
        await analyzer.cleanup()

if __name__ == "__main__":
    asyncio.run(main())
#!/usr/bin/env python3
"""
Metrics Intelligence Script

This script analyzes metrics datasets in Observe to create rich metadata for semantic search.
It focuses specifically on datasets with 'metric' interface and extracts detailed information
about individual metrics including their dimensions, value patterns, and usage contexts.

Usage:
    python metrics_intelligence.py --help
"""

import asyncio
import json
import logging
import os
import sys
import argparse
import time
import statistics
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
            'Excluding metric': Colors.YELLOW,
            'Successfully analyzed': Colors.GREEN,
            'Progress:': Colors.CYAN + Colors.BOLD,
            'Analysis Statistics': Colors.YELLOW + Colors.BOLD + Colors.UNDERLINE,
            'Database connection established': Colors.GREEN + Colors.BOLD,
            'Metrics analysis completed': Colors.GREEN + Colors.BOLD + Colors.UNDERLINE,
            'Discovered': Colors.CYAN,
            'Failed': Colors.RED + Colors.BOLD,
            'Error': Colors.RED + Colors.BOLD,
            'has no metrics data': Colors.RED,
            'checking for metrics': Colors.CYAN,
            'has metrics - analyzing': Colors.GREEN + Colors.BOLD,
            'High cardinality': Colors.YELLOW + Colors.BOLD,
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

# Add src directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class MetricsIntelligenceAnalyzer:
    """Analyzes metrics datasets and generates intelligence for semantic search."""
    
    def __init__(self):
        # Database connection
        self.db_pool = None
        
        # Observe API configuration
        self.observe_customer_id = os.getenv('OBSERVE_CUSTOMER_ID')
        self.observe_token = os.getenv('OBSERVE_TOKEN')
        self.observe_domain = os.getenv('OBSERVE_DOMAIN', 'observe-staging.com')
        
        
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
            'metrics_discovered': 0,
            'metrics_processed': 0,
            'metrics_skipped': 0,
            'metrics_excluded': 0,
            'high_cardinality_metrics': 0
        }
        
        # Rate limiting configuration
        self.last_observe_call = 0
        self.observe_delay = 0.2  # 200ms between Observe API calls
        self.max_retries = 3
        self.base_retry_delay = 1.0
        
        # Cardinality thresholds
        self.HIGH_CARDINALITY_THRESHOLD = 1000  # Warn about dimensions with >1000 unique values

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
            'password': os.getenv('SEMANTIC_GRAPH_PASSWORD', 'semantic_graph_secure_2024!')
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
        """Ensure the metrics intelligence schema exists."""
        # Get the absolute path to the schema file
        script_dir = os.path.dirname(os.path.abspath(__file__))
        schema_path = os.path.join(script_dir, '..', 'sql', 'metrics_intelligence_schema.sql')
        
        with open(schema_path, 'r') as f:
            schema_sql = f.read()
        
        async with self.db_pool.acquire() as conn:
            await conn.execute(schema_sql)
            logger.info("Metrics intelligence schema created/verified")
    
    async def get_metrics_with_data(self, dataset_id: str) -> Dict[str, int]:
        """
        Get all metrics that have data in the last 24 hours with their counts.
        More efficient than checking each metric individually.

        Returns:
            Dict mapping metric_name -> count for metrics with data
        """
        validation_query = """
        statsby count(), group_by(metric)
        """

        try:
            result = await self.execute_opal_query(dataset_id, validation_query, "240m")

            if not result:
                logger.debug(f"No metric data found in dataset {dataset_id} in last 240m")
                return {}

            metrics_with_data = {}
            for row in result:
                metric_name = row.get('metric', '')
                count_value = row.get('count()', row.get('count', 0))

                if metric_name and count_value:
                    try:
                        count_int = int(str(count_value))
                        if count_int > 0:
                            metrics_with_data[metric_name] = count_int
                            logger.debug(f"Metric {metric_name} has {count_int} data points in last 24h")
                    except (ValueError, TypeError) as e:
                        logger.debug(f"Could not parse count {count_value} for metric {metric_name}: {e}")
                        # If we can't parse but got result, include it
                        metrics_with_data[metric_name] = 1  # Default to 1 to include

            logger.info(f"Found {len(metrics_with_data)} metrics with recent data (240m) in dataset {dataset_id}")
            return metrics_with_data

        except Exception as e:
            logger.warning(f"Failed to get metric data counts for dataset {dataset_id}: {e}")
            # If validation fails completely, return empty dict (fail open at individual level)
            return {}

    async def has_recent_data(self, dataset_id: str, metric_name: str) -> bool:
        """
        Check if a metric has any data in the last 24 hours.

        Note: This is the individual fallback method.
        Use get_metrics_with_data() for bulk validation when possible.

        Returns:
            True if metric has recent data, False if empty/stale
        """
        # Query to check for any data points in the last 24 hours
        validation_query = f"""
        filter metric = "{metric_name}"
        | statsby count()
        """

        try:
            result = await self.execute_opal_query(dataset_id, validation_query, "240m")

            if not result or len(result) == 0:
                logger.debug(f"No data found for metric {metric_name} in last 240m")
                return False

            # Check if we got any count > 0
            for row in result:
                count_value = row.get('count()', row.get('count', 0))
                if count_value:
                    try:
                        # Convert to int in case it's returned as string
                        count_int = int(str(count_value))
                        if count_int > 0:
                            logger.debug(f"Metric {metric_name} has {count_int} data points in last 240m")
                            return True
                    except (ValueError, TypeError) as e:
                        logger.debug(f"Could not parse count value {count_value} for metric {metric_name}: {e}")
                        # If we can't parse the count but got a result, assume it has data
                        return True

            logger.debug(f"Metric {metric_name} has no data points in last 240m")
            return False

        except Exception as e:
            logger.warning(f"Failed to validate data for metric {metric_name}: {e}")
            # If validation fails, include the metric (fail open)
            return True

    async def store_excluded_metric(self, dataset_id: str, dataset_name: str, metric_name: str,
                                  exclusion_type: str, exclusion_reason: str) -> None:
        """Store an excluded metric in the database for tracking purposes."""
        try:
            query = """
                INSERT INTO metrics_intelligence (
                    dataset_id, metric_name, dataset_name, dataset_type, workspace_id,
                    metric_type, unit, description, common_dimensions, dimension_cardinality,
                    sample_dimensions, value_type, value_range, sample_values, data_frequency,
                    last_seen, first_seen, inferred_purpose, typical_usage, business_categories,
                    technical_category, common_fields, nested_field_paths, nested_field_analysis,
                    excluded, exclusion_reason, confidence_score, last_analyzed
                ) VALUES (
                    $1, $2, $3, 'unknown', NULL, 'unknown', NULL, NULL, '{}', '{}',
                    '{}', 'unknown', '{}', '{}', 'none', NULL, NULL,
                    'Excluded metric', 'Not analyzed due to exclusion', '["Unknown"]', 'Unknown',
                    '{}', '{}', '{}', TRUE, $4, 0.0, NOW()
                ) ON CONFLICT (dataset_id, metric_name) DO UPDATE SET
                    excluded = TRUE,
                    exclusion_reason = EXCLUDED.exclusion_reason,
                    last_analyzed = NOW()
            """

            async with self.db_pool.acquire() as conn:
                await conn.execute(query, dataset_id, metric_name, dataset_name, exclusion_reason)
                logger.debug(f"Stored excluded metric: {metric_name} - {exclusion_reason}")

        except Exception as e:
            logger.error(f"Failed to store excluded metric {metric_name}: {e}")

    def should_exclude_metric(self, metric_name: str, labels_or_attributes: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        """
        Determine if a metric should be excluded from analysis based on static criteria.
        Note: This is for static exclusions only. Data validation happens separately.

        Returns:
            (exclude: bool, reason: str)
        """
        # No static exclusions - analyze all metrics comprehensively
        # Data validation (empty metrics) is handled separately in has_recent_data()
        return False, None
    
    async def check_metric_needs_update(self, dataset_id: str, metric_name: str, sample_data_count: int) -> bool:
        """
        Check if a metric needs to be updated based on existing database record.
        Returns True if metric needs analysis, False if it can be skipped.

        Criteria for skipping:
        - Metric exists in database with same dataset_id and metric_name
        - Last analyzed within the last 24 hours
        - Sample data count is similar (within 20% difference)
        """
        # Force mode: always analyze
        if self.force_mode:
            return True
        try:
            async with self.db_pool.acquire() as conn:
                # Check if metric exists and when it was last analyzed
                result = await conn.fetchrow("""
                    SELECT last_analyzed, confidence_score
                    FROM metrics_intelligence 
                    WHERE dataset_id = $1 AND metric_name = $2
                """, dataset_id, metric_name)
                
                if not result:
                    # Metric doesn't exist, needs full analysis
                    logger.debug(f"Metric {metric_name} not found in database, needs analysis")
                    return True
                
                last_analyzed = result['last_analyzed']
                
                # Check if analyzed within last 24 hours
                if last_analyzed:
                    # Use timezone-naive datetime for comparison (database stores timezone-naive)
                    hours_since_analysis = (datetime.now() - last_analyzed).total_seconds() / 3600
                    if hours_since_analysis < 24:
                        logger.info(f"Skipping {metric_name} - analyzed {hours_since_analysis:.1f} hours ago")
                        self.stats['metrics_skipped'] += 1
                        return False
                
                # If we get here, metric exists but needs refresh
                logger.debug(f"Metric {metric_name} needs refresh - last analyzed {hours_since_analysis:.1f} hours ago")
                return True
                
        except Exception as e:
            logger.warning(f"Error checking metric update status for {metric_name}: {e}")
            # If we can't check, err on the side of updating
            return True
    
    async def fetch_metrics_datasets(self) -> List[Dict[str, Any]]:
        """Fetch all datasets with metric interface from Observe API."""
        url = f"https://{self.observe_customer_id}.{self.observe_domain}/v1/dataset"
        
        async def _fetch():
            await self.rate_limit_observe()
            response = await self.http_client.get(url)
            response.raise_for_status()
            
            data = response.json()
            all_datasets = data.get('data', [])
            
            # Filter for datasets with metric interface
            metrics_datasets = []
            for dataset in all_datasets:
                state = dataset.get('state', {})
                interfaces = state.get('interfaces', [])
                
                # Skip if interfaces is None or not a list
                if not interfaces or not isinstance(interfaces, list):
                    continue
                
                # Check if metric interface exists
                has_metric_interface = False
                for iface in interfaces:
                    if isinstance(iface, dict) and iface.get('path') == 'metric':
                        has_metric_interface = True
                        break
                
                if has_metric_interface:
                    metrics_datasets.append(dataset)
            
            logger.info(f"Discovered {len(metrics_datasets)} datasets with metric interface out of {len(all_datasets)} total")
            return metrics_datasets
        
        try:
            return await self.retry_with_backoff(_fetch)
        except Exception as e:
            logger.error(f"Failed to fetch metrics datasets after retries: {e}")
            raise
    
    async def execute_opal_query(self, dataset_id: str, query: str, time_range: str = "1h") -> Optional[List[Dict[str, Any]]]:
        """Execute an OPAL query and return parsed results."""
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
            "rowCount": "10000"  # Allow larger result sets for metric discovery
        }
        
        params = {"interval": time_range}
        
        async def _execute_and_parse():
            await self.rate_limit_observe()
            response = await self.http_client.post(url, json=payload, params=params)
            
            if response.status_code != 200:
                logger.warning(f"Query failed for dataset {dataset_id}: {response.status_code}")
                return None
            
            content_type = response.headers.get('content-type', '')
            logger.debug(f"Response content-type: {content_type} for dataset {dataset_id}")
            
            if 'text/csv' in content_type:
                csv_data = response.text.strip()
                if not csv_data:
                    logger.debug(f"Empty CSV response for dataset {dataset_id}")
                    return None
                
                lines = csv_data.split('\n')
                logger.debug(f"CSV response has {len(lines)} lines for dataset {dataset_id}")
                if len(lines) <= 1:
                    logger.debug(f"Only header line found for dataset {dataset_id}")
                    return None
                
                # Parse CSV into list of dictionaries
                header = [col.strip('"') for col in lines[0].split(',')]
                results = []
                
                for line in lines[1:]:
                    if not line.strip():
                        continue
                    
                    # Simple CSV parsing (handles quoted fields)
                    values = []
                    current_value = ""
                    in_quotes = False
                    
                    for char in line:
                        if char == '"' and not in_quotes:
                            in_quotes = True
                        elif char == '"' and in_quotes:
                            in_quotes = False
                        elif char == ',' and not in_quotes:
                            values.append(current_value.strip('"'))
                            current_value = ""
                        else:
                            current_value += char
                    
                    # Don't forget the last value
                    values.append(current_value.strip('"'))
                    
                    # Create row dict
                    row = {}
                    for i, col in enumerate(header):
                        value = values[i] if i < len(values) else ''
                        
                        # Parse JSON fields
                        if col in ['labels', 'attributes', 'resource_attributes', 'meta'] and value:
                            try:
                                row[col] = json.loads(value)
                            except json.JSONDecodeError:
                                row[col] = {}
                        else:
                            row[col] = value
                    
                    results.append(row)
                
                return results
            
            elif 'application/x-ndjson' in content_type or 'application/json' in content_type:
                # Handle NDJSON (newline-delimited JSON) format
                ndjson_data = response.text.strip()
                if not ndjson_data:
                    logger.debug(f"Empty NDJSON response for dataset {dataset_id}")
                    return None
                
                results = []
                for line in ndjson_data.split('\n'):
                    if not line.strip():
                        continue
                    try:
                        row = json.loads(line)
                        results.append(row)
                    except json.JSONDecodeError as e:
                        logger.debug(f"Failed to parse JSON line for dataset {dataset_id}: {e}")
                        continue
                
                logger.debug(f"NDJSON response parsed {len(results)} rows for dataset {dataset_id}")
                return results if results else None
            
            logger.debug(f"Unsupported content type received for dataset {dataset_id}: {content_type}")
            return None
        
        try:
            return await self.retry_with_backoff(_execute_and_parse)
        except Exception as e:
            logger.warning(f"Failed to execute query for dataset {dataset_id} after retries: {e}")
            return None
    
    def extract_nested_fields(self, data: Any, parent_path: str = "", max_depth: int = 4) -> Dict[str, Any]:
        """Recursively extract nested field paths and their value samples."""
        if max_depth <= 0:
            return {}

        nested_fields = {}

        if isinstance(data, dict):
            for key, value in data.items():
                current_path = f"{parent_path}.{key}" if parent_path else key

                # Store this field path
                if not isinstance(value, (dict, list)):
                    nested_fields[current_path] = {
                        'type': type(value).__name__,
                        'sample_value': str(value)[:100] if value is not None else None
                    }

                # Recurse into nested structures
                if isinstance(value, dict) and len(value) <= 20:  # Limit expansion for large objects
                    nested_fields.update(self.extract_nested_fields(value, current_path, max_depth - 1))
                elif isinstance(value, list) and len(value) > 0 and isinstance(value[0], dict):
                    # Analyze first list item for structure
                    nested_fields.update(self.extract_nested_fields(value[0], f"{current_path}[]", max_depth - 1))

        return nested_fields

    def analyze_nested_field_patterns(self, metric_data: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Analyze patterns in nested JSON fields across the dataset."""
        all_nested_fields = {}
        field_occurrence_count = {}
        field_cardinality = {}

        # Analyze nested structures in key JSON fields
        json_fields_to_analyze = ['labels', 'attributes', 'resource_attributes', 'meta', 'properties', 'context']

        for row in metric_data:
            for field_name in json_fields_to_analyze:
                if field_name in row and isinstance(row[field_name], dict):
                    nested_fields = self.extract_nested_fields(row[field_name], field_name)

                    for field_path, field_info in nested_fields.items():
                        # Track occurrence
                        if field_path not in field_occurrence_count:
                            field_occurrence_count[field_path] = 0
                            field_cardinality[field_path] = set()

                        field_occurrence_count[field_path] += 1
                        if field_info['sample_value']:
                            field_cardinality[field_path].add(field_info['sample_value'])

                        # Store field info
                        all_nested_fields[field_path] = field_info

        # Calculate field importance scores
        total_rows = len(metric_data)
        important_nested_fields = {}

        for field_path, occurrence_count in field_occurrence_count.items():
            presence_rate = occurrence_count / total_rows if total_rows > 0 else 0
            cardinality = len(field_cardinality[field_path])

            # Consider field important if present in >5% of records and has reasonable cardinality
            if presence_rate > 0.05 and cardinality < 1000:
                important_nested_fields[field_path] = {
                    'presence_rate': presence_rate,
                    'cardinality': cardinality,
                    'sample_values': list(field_cardinality[field_path])[:10],
                    'field_type': all_nested_fields[field_path]['type']
                }

        return {
            'nested_fields': important_nested_fields,
            'total_nested_fields_found': len(all_nested_fields),
            'important_fields_count': len(important_nested_fields)
        }

    async def analyze_metric_dimensions(self, metric_data: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Analyze dimensions/labels/attributes of a metric with enhanced nested field analysis."""
        dimension_values = {}
        dimension_keys = set()

        # Enhanced: Analyze nested JSON field patterns
        nested_analysis = self.analyze_nested_field_patterns(metric_data)

        for row in metric_data:
            # Handle different dataset structures
            dimensions = {}

            # Prometheus-style labels
            if 'labels' in row and isinstance(row['labels'], dict):
                dimensions.update(row['labels'])

            # OpenTelemetry attributes
            if 'attributes' in row and isinstance(row['attributes'], dict):
                dimensions.update(row['attributes'])

            # Resource attributes
            if 'resource_attributes' in row and isinstance(row['resource_attributes'], dict):
                dimensions.update(row['resource_attributes'])

            # Enhanced: Include important nested fields as dimensions
            for field_path, field_info in nested_analysis['nested_fields'].items():
                # Convert nested field path to value if it exists in this row
                try:
                    parts = field_path.split('.')
                    current_value = row
                    for part in parts:
                        if part.endswith('[]'):
                            part = part[:-2]
                            if isinstance(current_value.get(part), list) and len(current_value[part]) > 0:
                                current_value = current_value[part][0]
                            else:
                                current_value = None
                                break
                        else:
                            current_value = current_value.get(part) if isinstance(current_value, dict) else None
                        if current_value is None:
                            break

                    if current_value is not None:
                        dimensions[field_path] = current_value
                except (KeyError, TypeError, AttributeError):
                    continue
            
            # Collect dimension keys and values
            for key, value in dimensions.items():
                if key not in dimension_values:
                    dimension_values[key] = set()
                dimension_values[key].add(str(value))
                dimension_keys.add(key)
        
        # Calculate cardinalities and create summaries
        common_dimensions = {}
        dimension_cardinality = {}
        sample_dimensions = {}
        
        for key in dimension_keys:
            values = dimension_values.get(key, set())
            cardinality = len(values)
            
            dimension_cardinality[key] = cardinality
            
            # Sample up to 10 values
            sample_values = list(values)[:10]
            sample_dimensions[key] = sample_values
            
            # Consider common if present in >10% of data points and not too high cardinality
            if len(metric_data) > 0:
                presence_rate = len([row for row in metric_data 
                                   if any(key in dims for dims in [
                                       row.get('labels', {}), 
                                       row.get('attributes', {}), 
                                       row.get('resource_attributes', {})
                                   ] if isinstance(dims, dict))]) / len(metric_data)
                
                if presence_rate > 0.1 and cardinality < self.HIGH_CARDINALITY_THRESHOLD:
                    common_dimensions[key] = {
                        'presence_rate': presence_rate,
                        'cardinality': cardinality,
                        'sample_values': sample_values
                    }
        
        return {
            'common_dimensions': common_dimensions,
            'dimension_cardinality': dimension_cardinality,
            'sample_dimensions': sample_dimensions,
            'nested_field_analysis': nested_analysis
        }
    
    async def analyze_metric_values(self, metric_data: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Analyze value patterns of a metric."""
        values = []
        value_type = "unknown"
        
        for row in metric_data:
            if 'value' in row and row['value'] is not None and row['value'] != '':
                try:
                    val = float(row['value'])
                    values.append(val)
                except (ValueError, TypeError):
                    continue
        
        if not values:
            return {
                'value_type': 'unknown',
                'value_range': {},
                'sample_values': [],
                'data_frequency': 'unknown'
            }
        
        # Determine value type
        if all(val == int(val) for val in values[:100]):  # Check first 100
            value_type = "integer"
        else:
            value_type = "float"
        
        # Calculate statistics
        value_range = {
            'min': min(values),
            'max': max(values),
            'avg': statistics.mean(values),
            'count': len(values)
        }
        
        if len(values) > 1:
            value_range['std'] = statistics.stdev(values)
        
        # Sample values
        sample_values = values[:20]  # First 20 values
        
        # Estimate data frequency based on number of data points
        if len(values) > 1000:
            data_frequency = "high"
        elif len(values) > 100:
            data_frequency = "medium"
        else:
            data_frequency = "low"
        
        return {
            'value_type': value_type,
            'value_range': value_range,
            'sample_values': sample_values,
            'data_frequency': data_frequency
        }
    
    def detect_metric_type(self, metric_name: str, metric_data: List[Dict[str, Any]], first_row: Dict[str, Any]) -> str:
        """Detect metric type based on multiple indicators."""
        # Check explicit type field first
        explicit_type = first_row.get('metricType') or first_row.get('type', '')
        if explicit_type and explicit_type != 'unknown':
            return explicit_type.lower()
        
        # Check for tdigest field (indicates histogram/percentile metric)
        if any('tdigestValue' in row and row['tdigestValue'] for row in metric_data[:5]):
            return 'tdigest'
        
        # Pattern-based detection from metric name
        metric_lower = metric_name.lower()
        
        # Histogram patterns
        if any(pattern in metric_lower for pattern in ['_bucket', '_histogram', 'duration_', 'latency_', '_lg_']):
            return 'histogram'
            
        # Counter patterns
        if any(pattern in metric_lower for pattern in ['_total', '_count', '_sum', 'requests_', 'errors_']):
            return 'counter'
            
        # Gauge patterns
        if any(pattern in metric_lower for pattern in ['_current', '_usage', '_utilization', 'memory_', 'cpu_']):
            return 'gauge'
            
        # Default to gauge for unknown patterns
        return 'gauge'
    
    def get_metric_type_info(self, metric_type: str) -> Dict[str, str]:
        """Get metadata about the metric type for analysis context."""
        type_info = {
            'tdigest': {
                'description': 'Distribution metric (latency, duration) - use tdigest functions',
                'typical_aggregations': 'tdigest_quantile() for percentiles, tdigest_combine() with align',
                'common_use_cases': 'Latency analysis, performance monitoring, SLA tracking'
            },
            'histogram': {
                'description': 'Histogram metric - use tdigest functions for percentiles',
                'typical_aggregations': 'tdigest_quantile() for percentiles, tdigest_combine() with align',
                'common_use_cases': 'Response time distributions, resource usage patterns'
            },
            'counter': {
                'description': 'Counter metric (monotonically increasing) - use rate() function',
                'typical_aggregations': 'rate() for rate calculation, sum() for totals',
                'common_use_cases': 'Request counts, error counts, throughput analysis'
            },
            'gauge': {
                'description': 'Gauge metric (point-in-time values) - use avg() or latest values',
                'typical_aggregations': 'avg(), min(), max() for current values',
                'common_use_cases': 'Resource utilization, queue lengths, current state'
            }
        }
        return type_info.get(metric_type, {
            'description': f'Unknown metric type: {metric_type}',
            'typical_aggregations': 'sum(), avg(), count() based on use case',
            'common_use_cases': 'General metric analysis'
        })
    
    def expand_metric_keywords(self, metric_name: str) -> Set[str]:
        """Expand keywords from metric name for better matching."""
        expanded_keywords = set()

        # Add original words
        name_lower = metric_name.lower()
        words = name_lower.replace('/', ' ').replace('-', ' ').replace('_', ' ').replace('.', ' ').split()
        expanded_keywords.update(words)

        # Add common metric abbreviations and expansions
        keyword_expansions = {
            'cpu': ['cpu', 'processor', 'compute', 'utilization'],
            'mem': ['memory', 'mem', 'ram'],
            'memory': ['memory', 'mem', 'ram'],
            'disk': ['disk', 'storage', 'volume', 'filesystem'],
            'net': ['network', 'net', 'bandwidth', 'traffic'],
            'network': ['network', 'net', 'bandwidth', 'traffic'],
            'req': ['request', 'req', 'http'],
            'request': ['request', 'req', 'http'],
            'resp': ['response', 'resp', 'http'],
            'response': ['response', 'resp', 'http'],
            'err': ['error', 'err', 'failure', 'exception'],
            'error': ['error', 'err', 'failure', 'exception'],
            'latency': ['latency', 'duration', 'time', 'delay'],
            'duration': ['duration', 'latency', 'time', 'delay'],
            'throughput': ['throughput', 'rate', 'qps', 'rps'],
            'rate': ['rate', 'throughput', 'qps', 'rps'],
            'qps': ['qps', 'queries', 'rate', 'throughput'],
            'rps': ['rps', 'requests', 'rate', 'throughput'],
            'http': ['http', 'web', 'request', 'response'],
            'web': ['web', 'http', 'request', 'response'],
            'db': ['database', 'db', 'sql', 'query'],
            'database': ['database', 'db', 'sql', 'query'],
            'k8s': ['kubernetes', 'k8s', 'container', 'pod'],
            'kubernetes': ['kubernetes', 'k8s', 'container', 'pod'],
            'container': ['container', 'pod', 'docker', 'k8s'],
            'pod': ['pod', 'container', 'kubernetes', 'k8s'],
            'svc': ['service', 'svc', 'app'],
            'service': ['service', 'svc', 'app', 'application'],
            'app': ['application', 'app', 'service'],
            'application': ['application', 'app', 'service'],
            'total': ['total', 'sum', 'count', 'aggregate'],
            'count': ['count', 'total', 'number'],
            'sum': ['sum', 'total', 'aggregate'],
            'avg': ['average', 'avg', 'mean'],
            'average': ['average', 'avg', 'mean'],
            'min': ['minimum', 'min', 'lowest'],
            'max': ['maximum', 'max', 'highest'],
            'p95': ['percentile95', 'p95', '95th'],
            'p99': ['percentile99', 'p99', '99th'],
        }

        # Apply expansions
        for word in list(expanded_keywords):
            if word in keyword_expansions:
                expanded_keywords.update(keyword_expansions[word])

        return expanded_keywords

    def expand_keywords(self, name_lower: str) -> Set[str]:
        """Expand keywords from metric name for better matching."""
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

    def categorize_metric_with_enhanced_matching(self, metric_name: str, expanded_keywords: Set[str], metric_type: str, dimensions: Dict[str, Any]) -> Tuple[List[str], str]:
        """Enhanced metric categorization using expanded keywords."""

        # Enhanced business category matching
        business_patterns = {
            "Infrastructure": {
                'primary': ['cpu', 'memory', 'disk', 'filesystem', 'host', 'node', 'server', 'system'],
                'secondary': ['hardware', 'vm', 'container', 'pod', 'cluster'],
                'weight': 3
            },
            "Application": {
                'primary': ['service', 'application', 'app', 'http', 'request', 'response', 'endpoint'],
                'secondary': ['api', 'web', 'microservice', 'frontend', 'backend'],
                'weight': 3
            },
            "Database": {
                'primary': ['database', 'db', 'sql', 'query', 'transaction', 'connection'],
                'secondary': ['table', 'index', 'postgres', 'mysql', 'redis'],
                'weight': 3
            },
            "Network": {
                'primary': ['network', 'net', 'bandwidth', 'traffic', 'connection', 'tcp'],
                'secondary': ['packet', 'protocol', 'dns', 'load', 'proxy'],
                'weight': 2
            },
            "Storage": {
                'primary': ['storage', 'volume', 'disk', 'filesystem', 'file', 'io'],
                'secondary': ['backup', 'archive', 'blob', 'object', 'bucket'],
                'weight': 2
            },
            "Monitoring": {
                'primary': ['monitor', 'health', 'status', 'check', 'probe'],
                'secondary': ['alert', 'notification', 'threshold', 'sla', 'slo'],
                'weight': 1
            }
        }

        business_scores = {}
        for category, pattern in business_patterns.items():
            score = 0
            # Primary keywords get higher weight
            for keyword in pattern['primary']:
                if keyword in expanded_keywords or keyword in metric_name.lower():
                    score += pattern['weight'] * 2
            # Secondary keywords get lower weight
            for keyword in pattern['secondary']:
                if keyword in expanded_keywords or keyword in metric_name.lower():
                    score += pattern['weight']
            business_scores[category] = score

        # Get business categories - include multiple if they have significant scores
        business_categories = []
        max_score = max(business_scores.values()) if business_scores.values() else 0

        if max_score > 0:
            # Include primary category (highest score)
            primary_category = max(business_scores, key=business_scores.get)
            business_categories.append(primary_category)

            # Include additional categories if they score >= 50% of max score
            threshold = max_score * 0.5
            for category, score in business_scores.items():
                if category != primary_category and score >= threshold:
                    business_categories.append(category)

        # Default to Application if no matches
        if not business_categories:
            business_categories = ["Application"]

        # Enhanced technical category matching
        technical_patterns = {
            "Error": {
                'keywords': ['error', 'err', 'failure', 'exception', 'fault'],
                'metric_types': ['counter'],
                'weight': 4
            },
            "Latency": {
                'keywords': ['latency', 'duration', 'time', 'delay', 'response_time'],
                'metric_types': ['histogram', 'tdigest', 'gauge'],
                'weight': 4
            },
            "Performance": {
                'keywords': ['cpu', 'memory', 'utilization', 'usage', 'load', 'throughput'],
                'metric_types': ['gauge', 'counter'],
                'weight': 3
            },
            "Count": {
                'keywords': ['count', 'total', 'number', 'requests', 'connections'],
                'metric_types': ['counter'],
                'weight': 3
            },
            "Resource": {
                'keywords': ['disk', 'storage', 'filesystem', 'volume', 'capacity'],
                'metric_types': ['gauge'],
                'weight': 2
            },
            "Throughput": {
                'keywords': ['rate', 'qps', 'rps', 'throughput', 'bandwidth'],
                'metric_types': ['gauge', 'counter'],
                'weight': 3
            },
            "Availability": {
                'keywords': ['health', 'status', 'up', 'down', 'available'],
                'metric_types': ['gauge'],
                'weight': 2
            }
        }

        technical_scores = {}
        for category, pattern in technical_patterns.items():
            score = 0
            # Keyword matching
            for keyword in pattern['keywords']:
                if keyword in expanded_keywords or keyword in metric_name.lower():
                    score += pattern['weight']
            # Metric type matching
            if metric_type in pattern['metric_types']:
                score += pattern['weight']
            technical_scores[category] = score

        # Get technical category with highest score
        technical_category = max(technical_scores, key=technical_scores.get) if max(technical_scores.values()) > 0 else "Performance"

        return business_categories, technical_category

    def extract_common_fields(self, metric_data: List[Dict[str, Any]]) -> List[str]:
        """Extract commonly available fields for grouping."""
        common_fields = []
        if not metric_data:
            return common_fields
            
        # Check for standard service fields
        sample_row = metric_data[0]
        if 'service_name' in sample_row:
            common_fields.append('service_name')
        if 'span_name' in sample_row:
            common_fields.append('span_name')
        if 'environment' in sample_row:
            common_fields.append('environment')
            
        # Check common label fields
        labels = sample_row.get('labels', {})
        if isinstance(labels, dict):
            for key in ['service', 'instance', 'job', 'method', 'status_code']:
                if key in labels:
                    common_fields.append(f'labels.{key}')
                    
        return common_fields
    
    async def generate_metric_analysis(self, metric_name: str, metric_data: List[Dict[str, Any]], 
                                     dataset_name: str, dimensions: Dict[str, Any], 
                                     values: Dict[str, Any]) -> Dict[str, Any]:
        """Generate rule-based analysis of the metric for fast processing."""
        
        # Extract any available metadata
        first_row = metric_data[0] if metric_data else {}
        metric_type = self.detect_metric_type(metric_name, metric_data, first_row)
        unit = first_row.get('unit', '')
        description = first_row.get('description', '')
        
        # Rule-based categorization based on metric name patterns
        metric_lower = metric_name.lower()
        
        # Use enhanced categorization with multi-category support
        expanded_keywords = self.expand_keywords(metric_lower)
        business_categories, technical_category = self.categorize_metric_with_enhanced_matching(
            metric_name, expanded_keywords, metric_type, dimensions
        )
            
        # Generate simple purpose and usage text
        purpose = f"Tracks {metric_name.replace('_', ' ')} metrics for {dataset_name}"
        if description:
            purpose = description
            
        primary_business = business_categories[0] if business_categories else "system"
        usage = f"Monitor {technical_category.lower()} issues, analyze trends, set alerts, troubleshoot {primary_business.lower()} problems"
        
        return {
            "inferred_purpose": purpose,
            "typical_usage": usage,
            "business_categories": business_categories,
            "technical_category": technical_category,
            "metric_type": metric_type,
            "metric_type_info": self.get_metric_type_info(metric_type),
            "common_fields": self.extract_common_fields(metric_data)
        }
    
    
    async def store_metric_intelligence(self, metric_data: Dict[str, Any]) -> None:
        """Store metric intelligence in the database."""
        async with self.db_pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO metrics_intelligence (
                    dataset_id, metric_name, dataset_name, dataset_type, workspace_id,
                    metric_type, unit, description, common_dimensions, dimension_cardinality,
                    sample_dimensions, value_type, value_range, sample_values, data_frequency,
                    last_seen, first_seen, inferred_purpose, typical_usage, business_categories,
                    technical_category, common_fields, nested_field_paths, nested_field_analysis, excluded, exclusion_reason, confidence_score, last_analyzed
                ) VALUES (
                    $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17,
                    $18, $19, $20, $21, $22, $23, $24, $25, $26, $27, $28
                ) ON CONFLICT (dataset_id, metric_name) DO UPDATE SET
                    dataset_name = EXCLUDED.dataset_name,
                    dataset_type = EXCLUDED.dataset_type,
                    workspace_id = EXCLUDED.workspace_id,
                    metric_type = EXCLUDED.metric_type,
                    unit = EXCLUDED.unit,
                    description = EXCLUDED.description,
                    common_dimensions = EXCLUDED.common_dimensions,
                    dimension_cardinality = EXCLUDED.dimension_cardinality,
                    sample_dimensions = EXCLUDED.sample_dimensions,
                    value_type = EXCLUDED.value_type,
                    value_range = EXCLUDED.value_range,
                    sample_values = EXCLUDED.sample_values,
                    data_frequency = EXCLUDED.data_frequency,
                    last_seen = EXCLUDED.last_seen,
                    inferred_purpose = EXCLUDED.inferred_purpose,
                    typical_usage = EXCLUDED.typical_usage,
                    business_categories = EXCLUDED.business_categories,
                    technical_category = EXCLUDED.technical_category,
                    common_fields = EXCLUDED.common_fields,
                    nested_field_paths = EXCLUDED.nested_field_paths,
                    nested_field_analysis = EXCLUDED.nested_field_analysis,
                    excluded = EXCLUDED.excluded,
                    exclusion_reason = EXCLUDED.exclusion_reason,
                    confidence_score = EXCLUDED.confidence_score,
                    last_analyzed = EXCLUDED.last_analyzed
            """, *[
                metric_data['dataset_id'],
                metric_data['metric_name'],
                metric_data['dataset_name'],
                metric_data['dataset_type'],
                metric_data['workspace_id'],
                metric_data['metric_type'],
                metric_data['unit'],
                metric_data['description'],
                json.dumps(metric_data['common_dimensions']),
                json.dumps(metric_data['dimension_cardinality']),
                json.dumps(metric_data['sample_dimensions']),
                metric_data['value_type'],
                json.dumps(metric_data['value_range']),
                list(metric_data['sample_values']) if metric_data['sample_values'] else [],
                metric_data['data_frequency'],
                metric_data['last_seen'],
                metric_data['first_seen'],
                metric_data['inferred_purpose'],
                metric_data['typical_usage'],
                json.dumps(metric_data['business_categories']),
                metric_data['technical_category'],
                metric_data['common_fields'],
                json.dumps(metric_data['nested_field_paths']) if metric_data.get('nested_field_paths') else None,
                json.dumps(metric_data['nested_field_analysis']) if metric_data.get('nested_field_analysis') else None,
                metric_data['excluded'],
                metric_data['exclusion_reason'],
                metric_data['confidence_score'],
                datetime.now()
            ])
    
    async def check_dataset_has_data(self, dataset_id: str, dataset_type: str) -> bool:
        """Check if a dataset has any data over the last 24 hours."""
        # Simple query to check for any data
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
                    # Check if we have actual data
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

    async def analyze_dataset(self, dataset: Dict[str, Any]) -> None:
        """Analyze a single metrics dataset and discover all metrics within it."""
        # Extract dataset information
        meta = dataset.get('meta', {})
        config = dataset.get('config', {})
        state = dataset.get('state', {})
        
        dataset_id = meta.get('id', '').replace('o::', '').split(':')[-1]
        dataset_name = config.get('name', '')
        dataset_type = state.get('kind', '')
        workspace_id = meta.get('workspaceId', '')
        
        if not dataset_id or not dataset_name:
            logger.warning(f"Skipping dataset with empty ID or name: id='{dataset_id}', name='{dataset_name}'")
            self.stats['datasets_failed'] += 1
            return
        
        logger.info(f"Analyzing metrics dataset: {dataset_name} ({dataset_id})")
        
        try:
            # Check if dataset has any data before proceeding
            logger.info(f"Dataset {dataset_name} checking for data availability")
            has_data = await self.check_dataset_has_data(dataset_id, dataset_type)
            
            if not has_data:
                logger.info(f"Dataset {dataset_name} has no data - skipping")
                self.stats['datasets_skipped'] += 1
                return
            
            logger.info(f"Dataset {dataset_name} has data - analyzing metrics")
            
            # Discover all unique metrics in this dataset
            # Try multiple query variations to handle different dataset structures
            metrics_queries = [
                # Primary: Standard metrics dataset with timestamp field
                """
                filter metric != ""
                | statsby count:count(), latest_timestamp:max(timestamp), group_by(metric)
                | sort asc(metric)
                """,
                # Fallback 1: Dataset with 'time' field instead of 'timestamp'
                """
                filter metric != ""
                | statsby count:count(), latest_time:max(time), group_by(metric)
                | sort asc(metric)
                """,
                # Fallback 2: Try '__metric' field (some datasets use this)
                """
                filter __metric != ""
                | statsby count:count(), group_by(__metric)
                | sort asc(__metric)
                """,
                # Fallback 3: Try 'name' field 
                """
                filter name != ""
                | statsby count:count(), group_by(name)
                | sort asc(name)
                """,
                # Fallback 4: Simple grouping without filtering
                """
                statsby count:count(), group_by(metric)
                | sort asc(metric)
                | filter metric != ""
                """,
                # Fallback 5: Most basic - just group by any metric-like field
                """
                limit 1000
                """
            ]
            
            metrics_list = None
            for i, metrics_query in enumerate(metrics_queries):
                logger.debug(f"Trying metrics query variation {i+1} for dataset {dataset_id}")
                metrics_list = await self.execute_opal_query(dataset_id, metrics_query, "24h")
                if metrics_list:
                    logger.debug(f"Query variation {i+1} succeeded for dataset {dataset_id}")
                    
                    # If this was the raw data fallback, extract unique metrics manually
                    if i == len(metrics_queries) - 1:  # Last fallback query
                        unique_metrics = set()
                        for row in metrics_list:
                            for field in ['metric', '__metric', 'name', 'metricName']:
                                if field in row and row[field]:
                                    unique_metrics.add(row[field])
                        # Convert to expected format
                        if unique_metrics:
                            metrics_list = [{'metric': m} for m in sorted(unique_metrics)]
                        else:
                            metrics_list = None
                            continue
                    break
                else:
                    logger.debug(f"Query variation {i+1} failed for dataset {dataset_id}")
                    # Small delay between attempts
                    await asyncio.sleep(0.5)
            
            if not metrics_list:
                logger.warning(f"No metrics found in dataset {dataset_name}")
                self.stats['datasets_skipped'] += 1
                return
            
            logger.info(f"Discovered {len(metrics_list)} unique metrics in {dataset_name}")
            self.stats['metrics_discovered'] += len(metrics_list)

            # Bulk validate metrics with recent data (more efficient)
            logger.info(f"Validating data availability for all metrics in {dataset_name}")
            metrics_with_data = await self.get_metrics_with_data(dataset_id)

            # Filter metrics list to only those with recent data
            valid_metrics = []
            for metric_info in metrics_list:
                metric_name = metric_info.get('metric', '')
                if metric_name in metrics_with_data:
                    valid_metrics.append(metric_info)
                elif metric_name:  # Metric discovered but has no recent data
                    logger.info(f"Excluding metric {metric_name}: no data in last 240m ({metrics_with_data.get(metric_name, 0)} data points)")
                    self.stats['metrics_excluded'] += 1
                    # Store the exclusion in database
                    await self.store_excluded_metric(dataset_id, dataset_name, metric_name,
                                                   "no recent data", "No data points in last 240m")

            if not valid_metrics:
                logger.warning(f"No metrics with recent data found in {dataset_name}")
                self.stats['datasets_skipped'] += 1
                return

            logger.info(f"Processing {len(valid_metrics)} metrics with recent data (excluded {len(metrics_list) - len(valid_metrics)} empty metrics)")

            # OPTIMIZATION: Fetch sample data for all metrics using statsby to ensure we get all metrics
            logger.info(f"Fetching sample data for all valid metrics (much faster than individual queries)")

            # Use make_table + dedup to get one representative row per metric with all fields preserved
            # This is much better than statsby which drops fields with any() functions
            bulk_query = """
            filter metric != ""
            | make_table
            | dedup metric
            """

            logger.debug(f"Executing bulk dedup query to get sample data for all metrics")
            all_metric_samples = await self.execute_opal_query(dataset_id, bulk_query, "240m")

            if not all_metric_samples:
                logger.warning(f"No bulk data found for any metrics in {dataset_name}")
                self.stats['datasets_skipped'] += 1
                return

            logger.info(f"Retrieved sample data for {len(all_metric_samples)} metrics via bulk query")

            # Filter to only metrics that passed our validation
            valid_metric_names_set = {m.get('metric', '') for m in valid_metrics if m.get('metric')}

            valid_samples = []
            for sample in all_metric_samples:
                metric_name = sample.get('metric', '')
                if metric_name in valid_metric_names_set:
                    valid_samples.append(sample)

            logger.info(f"Found {len(valid_samples)} valid metrics in bulk sample data")

            if not valid_samples:
                logger.warning(f"No valid metrics found in bulk sample data for {dataset_name}")
                self.stats['datasets_skipped'] += 1
                return

            # For metrics that need detailed analysis, fetch more data efficiently
            # Use a smaller batch approach for metrics that need full analysis
            batch_size = 20  # Process metrics in batches to balance efficiency vs. query size

            for batch_start in range(0, len(valid_samples), batch_size):
                batch_samples = valid_samples[batch_start:batch_start + batch_size]
                batch_metrics = [s['metric'] for s in batch_samples]

                logger.info(f"Processing batch {batch_start//batch_size + 1}/{(len(valid_samples) + batch_size - 1)//batch_size} ({len(batch_metrics)} metrics)")

                # Fetch detailed data for this batch
                if len(batch_metrics) <= 10:  # Safe size for filter metric in
                    batch_query = f"""
                    filter metric in ({', '.join([f'"{name}"' for name in batch_metrics])})
                    | limit 1000
                    """
                else:  # Fall back to individual queries for large batches
                    batch_query = None

                if batch_query:
                    batch_detailed_data = await self.execute_opal_query(dataset_id, batch_query, "240m")

                    # Group batch data by metric
                    batch_data_grouped = {}
                    if batch_detailed_data:
                        for row in batch_detailed_data:
                            metric_name = row.get('metric', '')
                            if metric_name in batch_metrics:
                                if metric_name not in batch_data_grouped:
                                    batch_data_grouped[metric_name] = []
                                batch_data_grouped[metric_name].append(row)
                else:
                    batch_data_grouped = {}

                # Process each metric in this batch
                for i, sample in enumerate(batch_samples):
                    metric_name = sample.get('metric', '')
                    if not metric_name:
                        continue

                    global_index = batch_start + i + 1
                    logger.info(f"Processing metric {global_index}/{len(valid_samples)}: {metric_name}")

                    # Check if metric needs update (skip if analyzed recently)
                    needs_update = await self.check_metric_needs_update(dataset_id, metric_name, 0)
                    if not needs_update:
                        continue

                    # Use batch data if available, otherwise fall back to sample data
                    metric_data = batch_data_grouped.get(metric_name, [])

                    # If no detailed data available, use the full sample row (dedup preserves all fields)
                    if not metric_data:
                        metric_data = [sample]  # sample already has all original fields intact

                    if not metric_data:
                        logger.debug(f"No data found for metric {metric_name}")
                        continue

                    logger.debug(f"Analyzing {len(metric_data)} data points for {metric_name}")

                    # Analyze dimensions and values
                    dimensions = await self.analyze_metric_dimensions(metric_data)
                    values = await self.analyze_metric_values(metric_data)

                    # Check for high cardinality dimensions
                    high_card_dims = [k for k, v in dimensions['dimension_cardinality'].items()
                                     if v > self.HIGH_CARDINALITY_THRESHOLD]
                    if high_card_dims:
                        logger.warning(f"High cardinality dimensions in {metric_name}: {high_card_dims}")
                        self.stats['high_cardinality_metrics'] += 1

                    # Generate rule-based analysis
                    logger.debug(f"Generating analysis for {metric_name}")
                    analysis = await self.generate_metric_analysis(
                        metric_name, metric_data, dataset_name, dimensions, values
                    )

                    # Determine timestamps (handle both ISO format and nanoseconds since epoch)
                    timestamps = []
                    for row in metric_data:
                        if 'timestamp' not in row:
                            continue
                        try:
                            ts = row['timestamp']
                            if isinstance(ts, str):
                                # Try ISO format first
                                if 'T' in ts or 'Z' in ts:
                                    timestamps.append(datetime.fromisoformat(ts.replace('Z', '+00:00')))
                                else:
                                    # Try parsing as nanoseconds since epoch
                                    timestamps.append(datetime.fromtimestamp(int(ts) / 1_000_000_000))
                            else:
                                # Assume it's nanoseconds since epoch
                                timestamps.append(datetime.fromtimestamp(int(ts) / 1_000_000_000))
                        except (ValueError, TypeError) as e:
                            logger.debug(f"Failed to parse timestamp {row.get('timestamp')}: {e}")
                            continue
                    first_seen = min(timestamps) if timestamps else datetime.now()
                    last_seen = max(timestamps) if timestamps else datetime.now()

                    # Store metric intelligence
                    await self.store_metric_intelligence({
                        'dataset_id': dataset_id,
                        'metric_name': metric_name,
                        'dataset_name': dataset_name,
                        'dataset_type': dataset_type,
                        'workspace_id': workspace_id,
                        'metric_type': analysis['metric_type'],
                        'unit': metric_data[0].get('unit', ''),
                        'description': metric_data[0].get('description', ''),
                        'common_dimensions': dimensions['common_dimensions'],
                        'dimension_cardinality': dimensions['dimension_cardinality'],
                        'sample_dimensions': dimensions['sample_dimensions'],
                        'value_type': values['value_type'],
                        'value_range': values['value_range'],
                        'sample_values': values['sample_values'],
                        'data_frequency': values['data_frequency'],
                        'last_seen': last_seen,
                        'first_seen': first_seen,
                        'inferred_purpose': analysis['inferred_purpose'],
                        'typical_usage': analysis['typical_usage'],
                        'business_categories': analysis['business_categories'],
                        'technical_category': analysis['technical_category'],
                        'excluded': False,
                        'exclusion_reason': None,
                        'confidence_score': 1.0,
                        'common_fields': analysis['common_fields']
                    })

                    self.stats['metrics_processed'] += 1
                    logger.info(f"Successfully analyzed metric: {metric_name}")

                    # Brief pause for database operations
                    await asyncio.sleep(0.01)
            
            self.stats['datasets_processed'] += 1
            logger.info(f"Successfully analyzed dataset: {dataset_name}")
            
        except Exception as e:
            logger.error(f"Failed to analyze dataset {dataset_name}: {e}")
            self.stats['datasets_failed'] += 1
    
    async def analyze_all_metrics(self, limit: Optional[int] = None) -> None:
        """Analyze all metrics datasets from Observe."""
        # Print startup banner
        logger.info("")
        logger.info("╔═══════════════════════════════════════════════════════════════╗")
        logger.info("║              📊 Metrics Intelligence Analyzer                ║")
        logger.info("║                                                               ║")
        logger.info("║  Analyzing Observe metrics for semantic search discovery     ║")
        if self.force_mode:
            logger.info("║                    🧹 FORCE MODE ENABLED 🧹                    ║")
        logger.info("╚═══════════════════════════════════════════════════════════════╝")
        logger.info("")
        logger.info("🚀 Starting metrics analysis...")
        
        # Fetch all metrics datasets
        datasets = await self.fetch_metrics_datasets()
        
        if limit:
            datasets = datasets[:limit]
            logger.info(f"Limited analysis to {limit} datasets")
        
        # Process datasets
        for i, dataset in enumerate(datasets):
            logger.info(f"Progress: {i+1}/{len(datasets)}")
            await self.analyze_dataset(dataset)
            
            # Add delay to avoid overwhelming APIs
            await asyncio.sleep(1.0)
        
        logger.info("Metrics analysis completed")
        self.print_statistics()
    
    def print_statistics(self) -> None:
        """Print analysis statistics."""
        logger.info("")
        logger.info("╔═══════════════════════════════════════════════════════════════╗")
        logger.info("║                    📈 Metrics Analysis Statistics            ║")
        logger.info("╠═══════════════════════════════════════════════════════════════╣")
        logger.info(f"║ Datasets processed: {self.stats['datasets_processed']:>35} ║")
        logger.info(f"║ Datasets skipped: {self.stats['datasets_skipped']:>37} ║")
        logger.info(f"║ Datasets failed: {self.stats['datasets_failed']:>38} ║")
        logger.info(f"║ Metrics discovered: {self.stats['metrics_discovered']:>35} ║")
        logger.info(f"║ Metrics processed: {self.stats['metrics_processed']:>36} ║")
        logger.info(f"║ Metrics skipped: {self.stats['metrics_skipped']:>38} ║")
        logger.info(f"║ Metrics excluded: {self.stats['metrics_excluded']:>37} ║")
        logger.info(f"║ High cardinality metrics: {self.stats['high_cardinality_metrics']:>27} ║")
        logger.info("╚═══════════════════════════════════════════════════════════════╝")
        logger.info("")
    
    async def clear_database(self) -> None:
        """Clear all data from metrics_intelligence table for fresh start."""
        async with self.db_pool.acquire() as conn:
            # Clear the main table
            result = await conn.execute("DELETE FROM metrics_intelligence")
            count = result.split()[-1] if result else "0"
            logger.info(f"🧹 Cleared {count} existing records from metrics_intelligence table")

            # Force refresh of materialized views and indexes to clear any cached data
            # This ensures search functions return fresh results
            try:
                await conn.execute("VACUUM ANALYZE metrics_intelligence")
                await conn.execute("REINDEX TABLE metrics_intelligence")
                logger.info("🧹 Refreshed indexes and statistics")
            except Exception as e:
                logger.warning(f"Failed to refresh indexes: {e} (non-critical)")

            # Clear any potential connection-level query cache
            await conn.execute("DISCARD ALL")
            logger.info("🧹 Cleared connection cache")

    async def cleanup(self) -> None:
        """Cleanup resources."""
        if self.http_client:
            await self.http_client.aclose()
        if self.db_pool:
            await self.db_pool.close()

async def main():
    parser = argparse.ArgumentParser(description="Analyze Observe metrics for semantic search")
    parser.add_argument('--limit', type=int, help='Limit number of datasets to analyze')
    parser.add_argument('--verbose', action='store_true', help='Enable verbose logging')
    parser.add_argument('--force', action='store_true', help='Force clean database and reprocess all metrics from scratch')
    
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
    
    analyzer = MetricsIntelligenceAnalyzer()

    try:
        await analyzer.initialize_database()

        # Set force mode
        analyzer.force_mode = args.force

        # Clear database if force mode is enabled
        if args.force:
            logger.info("🧹 Force mode enabled - clearing metrics database...")
            await analyzer.clear_database()

        await analyzer.analyze_all_metrics(limit=args.limit)
        
    except KeyboardInterrupt:
        logger.info("Analysis interrupted by user")
    except Exception as e:
        logger.error(f"Analysis failed: {e}")
        raise
    finally:
        await analyzer.cleanup()

if __name__ == "__main__":
    asyncio.run(main())
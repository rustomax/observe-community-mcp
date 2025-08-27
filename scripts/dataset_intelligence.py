#!/usr/bin/env python3
"""
Dataset Intelligence Script

This script analyzes datasets in Observe to create rich metadata for semantic search.
It fetches dataset schemas, sample data, and uses LLM to generate descriptions and categorizations.

Usage:
    python dataset_intelligence.py --help
"""

import asyncio
import json
import logging
import os
import sys
import argparse
import time
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple
import asyncpg
import httpx
from openai import AsyncOpenAI
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
            'Efficiency:': Colors.GREEN + Colors.BOLD,
            'Database connection established': Colors.GREEN + Colors.BOLD,
            'Dataset analysis completed': Colors.GREEN + Colors.BOLD + Colors.UNDERLINE,
            'Fetched': Colors.CYAN,
            'interfaces changed': Colors.MAGENTA,
            'schema changed': Colors.MAGENTA,
            'name changed': Colors.MAGENTA,
            'type changed': Colors.MAGENTA,
            'last analyzed': Colors.BLUE,
            'Failed': Colors.RED + Colors.BOLD,
            'Error': Colors.RED + Colors.BOLD,
            'has no data': Colors.RED,
            'checking for data': Colors.CYAN,
            'has data - performing': Colors.GREEN + Colors.BOLD,
            'Removed empty dataset': Colors.RED + Colors.BOLD,
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

class DatasetIntelligenceAnalyzer:
    """Analyzes datasets and generates intelligence for semantic search."""
    
    def __init__(self):
        # Database connection
        self.db_pool = None
        
        # Observe API configuration
        self.observe_customer_id = os.getenv('OBSERVE_CUSTOMER_ID')
        self.observe_token = os.getenv('OBSERVE_TOKEN')
        self.observe_domain = os.getenv('OBSERVE_DOMAIN', 'observe-staging.com')
        
        # OpenAI configuration
        self.openai_client = AsyncOpenAI(api_key=os.getenv('OPENAI_API_KEY'))
        
        # HTTP client for Observe API with increased timeout
        self.http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(60.0, connect=10.0, read=60.0),  # 60s read, 10s connect
            headers={
                'Authorization': f'Bearer {self.observe_customer_id} {self.observe_token}',
                'Content-Type': 'application/json'
            }
        )
        
        # Statistics
        self.stats = {
            'datasets_processed': 0,
            'datasets_excluded': 0,
            'datasets_failed': 0,
            'datasets_skipped_unchanged': 0,
            'datasets_empty': 0,
            'datasets_pruned': 0,
            'embeddings_generated': 0
        }
        
        # Rate limiting configuration
        self.last_openai_call = 0
        self.last_observe_call = 0
        self.openai_delay = 0.5  # 500ms between OpenAI calls
        self.observe_delay = 0.2  # 200ms between Observe API calls
        self.max_retries = 3
        self.base_retry_delay = 1.0  # Base delay for exponential backoff
    
    async def rate_limit_openai(self) -> None:
        """Apply rate limiting for OpenAI API calls."""
        elapsed = time.time() - self.last_openai_call
        if elapsed < self.openai_delay:
            await asyncio.sleep(self.openai_delay - elapsed)
        self.last_openai_call = time.time()
    
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
                
                # Different retry strategies based on error type
                wait_time = self.base_retry_delay * (2 ** attempt)  # Exponential backoff
                
                # Longer waits for specific error types
                if "timeout" in str(e).lower() or "429" in str(e):
                    wait_time *= 2  # Double wait time for timeouts and rate limits
                elif "502" in str(e) or "503" in str(e) or "504" in str(e):
                    wait_time *= 1.5  # 1.5x wait time for server errors
                
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
        """Ensure the dataset intelligence schema exists."""
        # Get the absolute path to the schema file
        script_dir = os.path.dirname(os.path.abspath(__file__))
        schema_path = os.path.join(script_dir, '..', 'sql', 'dataset_intelligence_schema.sql')
        
        with open(schema_path, 'r') as f:
            schema_sql = f.read()
        
        async with self.db_pool.acquire() as conn:
            await conn.execute(schema_sql)
            logger.info("Dataset intelligence schema created/verified")
    
    def should_exclude_dataset(self, dataset: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        """
        Determine if a dataset should be excluded from analysis.
        
        Returns:
            (exclude: bool, reason: str)
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
            logger.info(f"Fetched {len(datasets)} datasets from Observe")
            return datasets
        
        try:
            return await self.retry_with_backoff(_fetch)
        except Exception as e:
            logger.error(f"Failed to fetch datasets after retries: {e}")
            raise
    
    async def fetch_dataset_schema(self, dataset_id: str) -> Optional[Dict[str, Any]]:
        """Fetch detailed schema information for a dataset."""
        url = f"https://{self.observe_customer_id}.{self.observe_domain}/v1/dataset/{dataset_id}"
        
        async def _fetch():
            await self.rate_limit_observe()
            response = await self.http_client.get(url)
            response.raise_for_status()
            return response.json()
        
        try:
            return await self.retry_with_backoff(_fetch)
        except Exception as e:
            logger.warning(f"Failed to fetch schema for dataset {dataset_id} after retries: {e}")
            return None
    
    async def fetch_sample_data(self, dataset_id: str, dataset_type: str) -> Optional[List[Dict[str, Any]]]:
        """Fetch sample data from a dataset using appropriate OPAL verb for dataset type."""
        # Use different OPAL verbs based on dataset type
        if dataset_type == "Resource":
            query = "topk 10"  # Resources require topk
        else:
            query = "limit 10"  # Events and Intervals use limit
        
        url = f"https://{self.observe_customer_id}.{self.observe_domain}/v1/meta/export/query"
        
        # Use the correct API format based on the working queries.py
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
            "rowCount": "10"
        }
        
        # Use a 60-minute time range for recent data
        params = {"interval": "60m"}
        
        async def _fetch_and_parse():
            logger.debug(f"Sample data query for dataset {dataset_id} (type: {dataset_type}):")
            logger.debug(f"  URL: {url}")
            logger.debug(f"  Query: {query}")
            logger.debug(f"  Params: {params}")
            logger.debug(f"  Payload: {json.dumps(payload, indent=2)}")
            
            await self.rate_limit_observe()
            response = await self.http_client.post(url, json=payload, params=params)
            
            logger.debug(f"Response status: {response.status_code}")
            logger.debug(f"Response headers: {dict(response.headers)}")
            
            if response.status_code != 200:
                try:
                    error_body = response.text
                    logger.warning(f"Query failed for dataset {dataset_id}: {response.status_code}")
                    logger.warning(f"Error response body: {error_body}")
                except:
                    logger.warning(f"Query failed for dataset {dataset_id}: {response.status_code} (could not read error body)")
                return None
                
            # If the response is CSV text, parse it
            content_type = response.headers.get('content-type', '')
            logger.debug(f"Response content-type: {content_type}")
            
            if 'text/csv' in content_type:
                csv_data = response.text
                logger.debug(f"CSV response length: {len(csv_data)}")
                if csv_data:
                    # Parse first few lines as sample data
                    lines = csv_data.strip().split('\n')
                    logger.debug(f"CSV lines: {len(lines)}")
                    if len(lines) > 1:  # Has header + data
                        logger.debug(f"CSV header: {lines[0]}")
                        header = lines[0].split(',')
                        sample_rows = []
                        for line in lines[1:6]:  # Take up to 5 rows
                            row_values = line.split(',')
                            row_dict = {header[i]: row_values[i] if i < len(row_values) else '' 
                                      for i in range(len(header))}
                            sample_rows.append(row_dict)
                        logger.debug(f"Successfully parsed {len(sample_rows)} sample rows")
                        return sample_rows
                    else:
                        logger.debug("CSV response has no data rows")
                else:
                    logger.debug("Empty CSV response")
            else:
                # Log non-CSV responses
                try:
                    response_text = response.text[:500]  # First 500 chars
                    logger.debug(f"Non-CSV response (first 500 chars): {response_text}")
                except:
                    logger.debug("Could not read response text")
            
            return None
        
        try:
            return await self.retry_with_backoff(_fetch_and_parse)
        except Exception as e:
            logger.warning(f"Failed to fetch sample data for dataset {dataset_id} after retries: {e}")
            return None
    
    async def check_dataset_has_data(self, dataset_id: str, dataset_type: str) -> bool:
        """Check if a dataset has any data over the last 24 hours."""
        # Use different OPAL verbs based on dataset type
        if dataset_type == "Resource":
            query = "topk 1"  # Just check if any records exist
        else:
            query = "limit 1"  # Just check if any records exist
        
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
            logger.debug(f"Checking data existence for dataset {dataset_id} (type: {dataset_type}) over 24h")
            
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
                # For NDJSON, each line should be a JSON object
                lines = [line.strip() for line in ndjson_data.split('\n') if line.strip()]
                
                if lines:
                    # Check if we have actual data (not just empty objects)
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
    
    async def generate_llm_analysis(self, 
                                   name: str, 
                                   dataset_type: str, 
                                   interfaces: List[str],
                                   schema: Dict[str, Any], 
                                   sample_data: Optional[List[Dict[str, Any]]]) -> Dict[str, str]:
        """Generate LLM analysis of the dataset."""
        
        # Prepare context for LLM
        context = {
            "name": name,
            "type": dataset_type,
            "interfaces": interfaces,
            "schema_fields": [],
            "sample_data_preview": None
        }
        
        # Extract schema fields
        if schema and 'columns' in schema:
            for col in schema['columns']:
                field_info = {
                    "name": col.get('name'),
                    "type": col.get('type'),
                    "description": col.get('description', '')
                }
                context["schema_fields"].append(field_info)
        
        # Include sample data if available
        if sample_data and len(sample_data) > 0:
            # Take first 3 rows to avoid token limits
            context["sample_data_preview"] = sample_data[:3]
        
        # Create LLM prompt
        prompt = f"""Analyze this dataset from an observability platform and provide structured insights:

Dataset Name: {name}
Type: {dataset_type}
Interfaces: {', '.join(interfaces) if interfaces else 'None'}

Schema Fields:
{json.dumps(context['schema_fields'], indent=2)}

Sample Data (first 3 rows):
{json.dumps(context['sample_data_preview'], indent=2) if context['sample_data_preview'] else 'No sample data available'}

Please provide:

1. DESCRIPTION: A clear, concise description of what this dataset contains (2-3 sentences)

2. TYPICAL_USAGE: Common investigation scenarios where this dataset would be used (3-4 specific use cases)

3. BUSINESS_CATEGORY: Choose ONE from: Infrastructure, Application, Security, Business, Network, Storage, Database, Monitoring, Analytics, User, Financial

4. TECHNICAL_CATEGORY: Choose ONE from: Logs, Metrics, Traces, Resources, Events, Sessions, Alerts

5. KEY_FIELDS: List the 5 most important fields for investigations (comma-separated)

Format your response as JSON:
{{
  "description": "...",
  "typical_usage": "...", 
  "business_category": "...",
  "technical_category": "...",
  "key_fields": ["field1", "field2", "field3", "field4", "field5"]
}}"""

        async def _generate_analysis():
            await self.rate_limit_openai()
            response = await self.openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "You are an expert in observability data analysis. Provide accurate, structured analysis of datasets."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.1
            )
            
            content = response.choices[0].message.content.strip()
            
            # Parse JSON response
            if content.startswith('```json'):
                content = content.replace('```json', '').replace('```', '').strip()
            
            analysis = json.loads(content)
            logger.debug(f"LLM analysis completed for {name}")
            return analysis
        
        try:
            return await self.retry_with_backoff(_generate_analysis)
        except Exception as e:
            logger.error(f"Failed to generate LLM analysis for {name} after retries: {e}")
            # Return fallback analysis
            return {
                "description": f"Dataset containing {dataset_type.lower()} data: {name}",
                "typical_usage": "General observability and monitoring investigations",
                "business_category": "Infrastructure",
                "technical_category": "Events" if dataset_type == "Event" else "Resources",
                "key_fields": [field.get('name', '') for field in context['schema_fields'][:5]]
            }
    
    async def generate_embeddings(self, text: str) -> Optional[List[float]]:
        """Generate OpenAI embeddings for text."""
        async def _generate_embedding():
            await self.rate_limit_openai()
            response = await self.openai_client.embeddings.create(
                model="text-embedding-3-small",
                input=text
            )
            self.stats['embeddings_generated'] += 1
            return response.data[0].embedding
        
        try:
            return await self.retry_with_backoff(_generate_embedding)
        except Exception as e:
            logger.error(f"Failed to generate embedding after retries: {e}")
            return None
    
    async def check_dataset_changed(self, dataset_id: str, name: str, dataset_type: str, 
                                   interfaces: Optional[List[str]], schema_info: Optional[Dict[str, Any]]) -> bool:
        """Check if a dataset has changed since last analysis."""
        async with self.db_pool.acquire() as conn:
            try:
                # Get existing dataset record
                existing = await conn.fetchrow(
                    """
                    SELECT name, dataset_type, interfaces, schema_info, last_analyzed
                    FROM dataset_intelligence 
                    WHERE dataset_id = $1
                    """, 
                    dataset_id
                )
                
                if not existing:
                    logger.info(f"Dataset {dataset_id} not found in database - needs analysis")
                    return True  # New dataset, needs analysis
                
                # Compare key attributes
                if existing['name'] != name:
                    logger.info(f"Dataset {dataset_id} name changed: '{existing['name']}' -> '{name}'")
                    return True
                
                if existing['dataset_type'] != dataset_type:
                    logger.info(f"Dataset {dataset_id} type changed: '{existing['dataset_type']}' -> '{dataset_type}'")
                    return True
                
                # Compare interfaces (convert existing back to list)
                if existing['interfaces']:
                    parsed_interfaces = json.loads(existing['interfaces'])
                    if parsed_interfaces is not None:
                        # Handle both old format (full objects) and new format (just paths)
                        if parsed_interfaces and isinstance(parsed_interfaces[0], dict):
                            # Old format: extract paths from dict objects
                            existing_interfaces = [iface.get('path') for iface in parsed_interfaces if iface.get('path')]
                        else:
                            # New format: already just paths
                            existing_interfaces = parsed_interfaces
                    else:
                        existing_interfaces = []
                else:
                    existing_interfaces = []
                    
                current_interfaces = interfaces or []  # Handle None interfaces
                if set(existing_interfaces) != set(current_interfaces):
                    logger.info(f"Dataset {dataset_id} interfaces changed: {existing_interfaces} -> {current_interfaces}")
                    return True
                
                # Compare schema structure (field names and types)
                if existing['schema_info']:
                    parsed_schema = json.loads(existing['schema_info'])
                    existing_schema = parsed_schema if parsed_schema is not None else {}
                else:
                    existing_schema = {}
                    
                current_schema = schema_info or {}  # Handle None schema_info
                if self._schemas_different(existing_schema, current_schema):
                    logger.info(f"Dataset {dataset_id} schema changed")
                    return True
                
                # Check if it's been more than 7 days since last analysis (for periodic refresh)
                if existing['last_analyzed']:
                    days_since_analysis = (datetime.now() - existing['last_analyzed']).days
                    if days_since_analysis > 7:
                        logger.info(f"Dataset {dataset_id} last analyzed {days_since_analysis} days ago - refreshing")
                        return True
                
                logger.info(f"Dataset {dataset_id} unchanged - skipping analysis")
                return False
                
            except Exception as e:
                import traceback
                logger.warning(f"Error checking if dataset {dataset_id} changed: {e}")
                logger.warning(f"Traceback: {traceback.format_exc()}")
                logger.warning(f"Input values - interfaces: {interfaces}, schema_info: {schema_info}")
                return True  # Default to analyzing if we can't determine
    
    def _schemas_different(self, schema1: Dict[str, Any], schema2: Dict[str, Any]) -> bool:
        """Compare two schema dictionaries to detect meaningful changes."""
        # Extract column information for comparison
        def extract_columns(schema):
            if not schema or 'columns' not in schema:
                return []
            return [(col.get('name'), col.get('type')) for col in schema['columns']]
        
        cols1 = extract_columns(schema1)
        cols2 = extract_columns(schema2)
        
        # Compare column names and types
        return set(cols1) != set(cols2)
    
    async def update_last_analyzed(self, dataset_id: str) -> None:
        """Update the last_analyzed timestamp for an unchanged dataset."""
        async with self.db_pool.acquire() as conn:
            try:
                await conn.execute(
                    """
                    UPDATE dataset_intelligence 
                    SET last_analyzed = NOW() 
                    WHERE dataset_id = $1
                    """, 
                    dataset_id
                )
            except Exception as e:
                logger.warning(f"Failed to update last_analyzed for dataset {dataset_id}: {e}")
    
    async def remove_empty_dataset(self, dataset_id: str) -> None:
        """Remove a dataset from the intelligence database if it has no data."""
        async with self.db_pool.acquire() as conn:
            try:
                result = await conn.fetchrow(
                    """
                    DELETE FROM dataset_intelligence 
                    WHERE dataset_id = $1
                    RETURNING name
                    """, 
                    dataset_id
                )
                if result:  # Row was deleted
                    logger.info(f"Removed empty dataset {dataset_id} ({result['name']}) from database")
                    self.stats['datasets_pruned'] += 1
                else:
                    logger.debug(f"Dataset {dataset_id} was not in database to remove")
            except Exception as e:
                logger.warning(f"Failed to remove empty dataset {dataset_id}: {e}")
    
    async def store_dataset_intelligence(self, dataset_data: Dict[str, Any]) -> None:
        """Store dataset intelligence in the database."""
        async with self.db_pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO dataset_intelligence (
                    dataset_id, name, dataset_type, workspace_id, interfaces, schema_info, 
                    sample_data, description, typical_usage, business_category, technical_category,
                    key_fields, description_embedding, schema_embedding, combined_embedding,
                    excluded, exclusion_reason, last_analyzed
                ) VALUES (
                    $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18
                ) ON CONFLICT (dataset_id) DO UPDATE SET
                    name = EXCLUDED.name,
                    dataset_type = EXCLUDED.dataset_type,
                    workspace_id = EXCLUDED.workspace_id,
                    interfaces = EXCLUDED.interfaces,
                    schema_info = EXCLUDED.schema_info,
                    sample_data = EXCLUDED.sample_data,
                    description = EXCLUDED.description,
                    typical_usage = EXCLUDED.typical_usage,
                    business_category = EXCLUDED.business_category,
                    technical_category = EXCLUDED.technical_category,
                    key_fields = EXCLUDED.key_fields,
                    description_embedding = EXCLUDED.description_embedding,
                    schema_embedding = EXCLUDED.schema_embedding,
                    combined_embedding = EXCLUDED.combined_embedding,
                    excluded = EXCLUDED.excluded,
                    exclusion_reason = EXCLUDED.exclusion_reason,
                    last_analyzed = EXCLUDED.last_analyzed,
                    last_updated = NOW()
            """, *[
                dataset_data['dataset_id'],
                dataset_data['name'],
                dataset_data['dataset_type'],
                dataset_data['workspace_id'],
                json.dumps(dataset_data['interfaces']),
                json.dumps(dataset_data['schema_info']),
                json.dumps(dataset_data['sample_data']),
                dataset_data['description'],
                dataset_data['typical_usage'],
                dataset_data['business_category'],
                dataset_data['technical_category'],
                dataset_data['key_fields'],
                dataset_data['description_embedding'],
                dataset_data['schema_embedding'],
                dataset_data['combined_embedding'],
                dataset_data['excluded'],
                dataset_data['exclusion_reason'],
                datetime.now()
            ])
    
    async def analyze_dataset(self, dataset: Dict[str, Any]) -> None:
        """Analyze a single dataset and store intelligence."""
        # Extract the correct fields from the API response structure
        meta = dataset.get('meta', {})
        config = dataset.get('config', {})
        state = dataset.get('state', {})
        
        dataset_id = meta.get('id', '').replace('o::', '').split(':')[-1]  # Extract just the ID number
        name = config.get('name', '')
        dataset_type = state.get('kind', '')
        workspace_id = meta.get('workspaceId', '')
        interfaces = state.get('interfaces', [])
        
        # Skip datasets with empty names or IDs
        if not dataset_id or not name:
            logger.warning(f"Skipping dataset with empty ID or name: id='{dataset_id}', name='{name}'")
            self.stats['datasets_failed'] += 1
            return
        
        logger.info(f"Analyzing dataset: {name} ({dataset_id})")
        
        try:
            # Check if should be excluded
            excluded, exclusion_reason = self.should_exclude_dataset(dataset)
            
            if excluded:
                logger.info(f"Excluding dataset {name}: {exclusion_reason}")
                await self.store_dataset_intelligence({
                    'dataset_id': dataset_id,
                    'name': name,
                    'dataset_type': dataset_type,
                    'workspace_id': workspace_id,
                    'interfaces': interfaces,
                    'schema_info': {},
                    'sample_data': [],
                    'description': '',
                    'typical_usage': '',
                    'business_category': '',
                    'technical_category': '',
                    'key_fields': [],
                    'description_embedding': None,
                    'schema_embedding': None,
                    'combined_embedding': None,
                    'excluded': True,
                    'exclusion_reason': exclusion_reason
                })
                self.stats['datasets_excluded'] += 1
                return
            
            # Fetch detailed schema first to check for changes
            schema = await self.fetch_dataset_schema(dataset_id)
            if not schema:
                logger.warning(f"No schema available for {name}")
                self.stats['datasets_failed'] += 1
                return
            
            # Extract interface types for comparison
            interface_types = []
            if interfaces:
                for iface in interfaces:
                    if isinstance(iface, dict) and 'path' in iface:
                        interface_types.append(iface['path'])
            
            # Check if dataset has changed - if not, skip expensive operations
            has_changed = await self.check_dataset_changed(
                dataset_id, name, dataset_type, interface_types, schema
            )
            
            if not has_changed:
                logger.info(f"Dataset {name} unchanged - skipping analysis")
                # Update last_analyzed timestamp to track when we checked it
                await self.update_last_analyzed(dataset_id)
                self.stats['datasets_skipped_unchanged'] += 1
                return
            
            # Dataset has changed - check if it has any data before proceeding
            logger.info(f"Dataset {name} has changed - checking for data availability")
            has_data = await self.check_dataset_has_data(dataset_id, dataset_type)
            
            if not has_data:
                logger.info(f"Dataset {name} has no data in last 24h - excluding from analysis")
                # Remove from database if it exists (pruning)
                await self.remove_empty_dataset(dataset_id)
                self.stats['datasets_empty'] += 1
                return
            
            # Dataset has changed and has data - proceed with full analysis
            logger.info(f"Dataset {name} has data - performing full analysis")
            
            # Fetch sample data
            sample_data = await self.fetch_sample_data(dataset_id, dataset_type)
            
            # Generate LLM analysis using interface_types already extracted above
            analysis = await self.generate_llm_analysis(
                name, dataset_type, interface_types, schema, sample_data
            )
            
            # Generate embeddings
            description_text = f"{name}: {analysis['description']}"
            # Ensure typical_usage is a string (convert list to string if needed)
            if isinstance(analysis['typical_usage'], list):
                usage_text = ' '.join(analysis['typical_usage'])
            else:
                usage_text = analysis['typical_usage']
            schema_text = json.dumps([f['name'] for f in schema.get('columns', [])])
            combined_text = f"{description_text} {usage_text} Fields: {schema_text}"
            
            description_embedding = await self.generate_embeddings(description_text)
            schema_embedding = await self.generate_embeddings(schema_text)
            combined_embedding = await self.generate_embeddings(combined_text)
            
            # Store in database
            await self.store_dataset_intelligence({
                'dataset_id': dataset_id,
                'name': name,
                'dataset_type': dataset_type,
                'workspace_id': workspace_id,
                'interfaces': interfaces,
                'schema_info': schema,
                'sample_data': sample_data or [],
                'description': analysis['description'],
                'typical_usage': usage_text,
                'business_category': analysis['business_category'],
                'technical_category': analysis['technical_category'],
                'key_fields': analysis['key_fields'],
                'description_embedding': str(description_embedding) if description_embedding else None,
                'schema_embedding': str(schema_embedding) if schema_embedding else None,
                'combined_embedding': str(combined_embedding) if combined_embedding else None,
                'excluded': False,
                'exclusion_reason': None
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
        logger.info("║              🧠 Dataset Intelligence Analyzer                 ║")
        logger.info("║                                                               ║")
        logger.info("║  Analyzing Observe datasets for semantic search discovery    ║")
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
            
            # Add small delay to avoid overwhelming APIs
            await asyncio.sleep(0.5)
        
        logger.info("Dataset analysis completed")
        self.print_statistics()
    
    def print_statistics(self) -> None:
        """Print analysis statistics."""
        total = (self.stats['datasets_processed'] + self.stats['datasets_excluded'] + 
                self.stats['datasets_failed'] + self.stats['datasets_skipped_unchanged'] + 
                self.stats['datasets_empty'])
        
        logger.info("")
        logger.info("╔═══════════════════════════════════════════════════════════════╗")
        logger.info("║                    📊 Analysis Statistics                     ║")
        logger.info("╠═══════════════════════════════════════════════════════════════╣")
        logger.info(f"║ Total datasets checked: {total:>35} ║")
        logger.info(f"║ 🆕 Datasets processed (new/changed): {self.stats['datasets_processed']:>20} ║")
        logger.info(f"║ ⏭️  Datasets skipped (unchanged): {self.stats['datasets_skipped_unchanged']:>23} ║")
        logger.info(f"║ 📭 Datasets empty (no data): {self.stats['datasets_empty']:>25} ║")
        logger.info(f"║ 🗑️  Datasets pruned (removed): {self.stats['datasets_pruned']:>23} ║")
        logger.info(f"║ ❌ Datasets excluded: {self.stats['datasets_excluded']:>31} ║")
        logger.info(f"║ 💥 Datasets failed: {self.stats['datasets_failed']:>33} ║")
        logger.info(f"║ 🔢 Embeddings generated: {self.stats['embeddings_generated']:>26} ║")
        
        if total > 0:
            efficiency = ((self.stats['datasets_skipped_unchanged'] + self.stats['datasets_empty']) / total) * 100
            logger.info("╠═══════════════════════════════════════════════════════════════╣")
            logger.info(f"║ ⚡ Efficiency: {efficiency:>6.1f}% of datasets skipped (optimized) ║")
        
        logger.info("╚═══════════════════════════════════════════════════════════════╝")
        logger.info("")
    
    async def cleanup(self) -> None:
        """Cleanup resources."""
        if self.http_client:
            await self.http_client.aclose()
        if self.db_pool:
            await self.db_pool.close()

async def main():
    parser = argparse.ArgumentParser(description="Analyze Observe datasets for semantic search")
    parser.add_argument('--limit', type=int, help='Limit number of datasets to analyze')
    parser.add_argument('--verbose', action='store_true', help='Enable verbose logging')
    
    args = parser.parse_args()
    
    # Configure colored logging
    handler = logging.StreamHandler()
    formatter = ColoredFormatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    handler.setFormatter(formatter)
    
    # Set up root logger - clear any existing handlers first
    root_logger = logging.getLogger()
    root_logger.handlers.clear()  # Remove any existing handlers
    root_logger.addHandler(handler)
    root_logger.setLevel(logging.INFO)
    
    if args.verbose:
        root_logger.setLevel(logging.DEBUG)
    
    # Reduce noise from HTTP libraries unless in verbose mode
    if not args.verbose:
        logging.getLogger('httpx').setLevel(logging.WARNING)
        logging.getLogger('httpcore').setLevel(logging.WARNING)
    
    analyzer = DatasetIntelligenceAnalyzer()
    
    try:
        await analyzer.initialize_database()
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
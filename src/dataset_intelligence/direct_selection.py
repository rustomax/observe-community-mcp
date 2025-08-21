"""
Direct dataset selection based on clear field requirements and interface types.

This replaces complex semantic matching with simple, reliable pattern matching.
"""

from typing import List, Dict, Any, Optional
import asyncio
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

class DirectDatasetSelector:
    """
    Simple, reliable dataset selection based on actual field requirements.
    """
    
    def __init__(self):
        # Clear field requirements for different query types
        self.query_patterns = {
            "error_analysis": {
                "required_fields": ["error", "span_error_count", "status_code", "response_status"],
                "preferred_interfaces": ["trace", "span"],
                "keywords": ["error", "errors", "exception", "failed", "failure"],
                "description": "Needs boolean error field or error counts"
            },
            "performance_analysis": {
                "required_fields": ["duration", "latency", "response_time", "elapsed_time"],
                "preferred_interfaces": ["trace", "span"], 
                "keywords": ["slow", "latency", "duration", "performance", "response time"],
                "description": "Needs duration/timing fields"
            },
            "log_analysis": {
                "required_fields": ["body", "message", "log", "content", "text"],
                "preferred_interfaces": ["log", "event"],
                "keywords": ["log", "logs", "message", "pattern", "exception"],
                "description": "Needs message/body fields"
            },
            "service_metrics": {
                "required_fields": ["service_name", "for_service_name", "service"],
                "preferred_interfaces": ["metric", "measurement"],
                "keywords": ["service", "microservice", "application"],
                "description": "Needs service identification"
            },
            "resource_monitoring": {
                "required_fields": ["cpu", "memory", "pod_name", "container", "node"],
                "preferred_interfaces": ["metric", "resource"],
                "keywords": ["cpu", "memory", "pod", "container", "resource"],
                "description": "Needs infrastructure fields"
            }
        }
    
    async def select_datasets_simple(self, user_query: str, available_datasets: List[Dict]) -> List[Dict]:
        """
        Simple dataset selection based on field requirements and interface types.
        
        Args:
            user_query: User's natural language query
            available_datasets: List of dataset metadata from list_datasets()
            
        Returns:
            Ranked list of suitable datasets
        """
        query_lower = user_query.lower()
        print(f"[DIRECT_SELECTOR] Analyzing query: '{user_query[:60]}...'")
        
        # Step 1: Classify query type
        query_type = self._classify_query_type(query_lower)
        if not query_type:
            print(f"[DIRECT_SELECTOR] Could not classify query type, using general approach")
            return self._general_dataset_ranking(available_datasets)
        
        print(f"[DIRECT_SELECTOR] Classified as: {query_type}")
        pattern = self.query_patterns[query_type]
        print(f"[DIRECT_SELECTOR] Looking for fields: {pattern['required_fields']}")
        print(f"[DIRECT_SELECTOR] Preferred interfaces: {pattern['preferred_interfaces']}")
        
        # Step 2: Score datasets based on field availability and interface type
        scored_datasets = []
        
        for dataset in available_datasets:
            score = await self._score_dataset_direct(dataset, pattern, query_lower)
            if score > 0:
                dataset_copy = dataset.copy()
                dataset_copy["selection_score"] = score
                scored_datasets.append(dataset_copy)
        
        # Step 3: Sort by score and return top matches
        scored_datasets.sort(key=lambda x: x["selection_score"], reverse=True)
        
        if scored_datasets:
            print(f"[DIRECT_SELECTOR] Found {len(scored_datasets)} suitable datasets:")
            for i, ds in enumerate(scored_datasets[:5], 1):
                print(f"  {i}. {ds.get('name', ds.get('dataset_id'))} (score: {ds['selection_score']:.1f})")
        else:
            print(f"[DIRECT_SELECTOR] No suitable datasets found, falling back to general selection")
            return self._general_dataset_ranking(available_datasets)
        
        return scored_datasets
    
    def _classify_query_type(self, query_lower: str) -> Optional[str]:
        """Classify query type based on keywords."""
        
        # Check for specific patterns first (most specific to least specific)
        if any(keyword in query_lower for keyword in ["error rate", "error percentage", "failure rate"]):
            return "error_analysis"
        
        if any(keyword in query_lower for keyword in ["slow", "latency", "duration", "response time", "performance"]):
            return "performance_analysis"
        
        if any(keyword in query_lower for keyword in ["log", "message", "exception", "pattern"]):
            return "log_analysis"
        
        if any(keyword in query_lower for keyword in ["cpu", "memory", "pod", "container", "resource"]):
            return "resource_monitoring"
        
        if any(keyword in query_lower for keyword in ["service", "microservice", "application"]):
            return "service_metrics"
        
        return None
    
    async def _score_dataset_direct(self, dataset: Dict, pattern: Dict, query_lower: str) -> float:
        """Score a dataset based on field availability and interface matching."""
        score = 0.0
        
        # Handle different possible dataset structures from API
        # The API returns datasets with 'meta' containing id and 'config' containing name
        if 'meta' in dataset and 'config' in dataset:
            # Standard Observe API format
            dataset_id = dataset['meta'].get('id', '')
            name = dataset['config'].get('name', '').lower()
        else:
            # Fallback for other formats
            dataset_id = dataset.get('dataset_id') or dataset.get('id', '')
            name = dataset.get('name', '').lower()
        
        # Use cached key_fields instead of expensive API calls
        available_fields = dataset.get('key_fields', [])
        if isinstance(available_fields, list):
            available_fields = [f.lower() for f in available_fields]
        else:
            available_fields = []
        
        print(f"[DIRECT_SELECTOR]   Checking {name}: {len(available_fields)} fields available")
        
        # Score 1: Field availability (most important - 60 points max)
        required_fields = [f.lower() for f in pattern["required_fields"]]
        field_matches = 0
        
        for required_field in required_fields:
            if any(required_field in field or field in required_field for field in available_fields):
                field_matches += 1
                score += 15  # High weight for field matches
        
        if field_matches > 0:
            print(f"[DIRECT_SELECTOR]     ✅ {field_matches} required fields found")
        
        # Score 2: Interface/Type matching (30 points max)
        dataset_type = dataset.get('dataset_type', '').lower()
        technical_category = dataset.get('technical_category', '').lower()
        business_category = dataset.get('business_category', '').lower()
        interfaces = dataset.get('interfaces', {})
        
        # Check interfaces JSON data
        interface_str = ""
        if isinstance(interfaces, dict):
            interface_str = " ".join(str(v).lower() for v in interfaces.values())
        
        for preferred_interface in pattern["preferred_interfaces"]:
            if (preferred_interface in dataset_type or 
                preferred_interface in technical_category or
                preferred_interface in business_category or
                preferred_interface in interface_str):
                score += 20
                print(f"[DIRECT_SELECTOR]     ✅ Interface match: {preferred_interface}")
                break
        
        # Score 3: Name/description keywords (10 points max)
        description = dataset.get('description', '').lower()
        
        keyword_matches = sum(1 for keyword in pattern["keywords"] 
                             if keyword in name or keyword in description)
        score += keyword_matches * 2
        
        # Score 4: Direct query keywords in dataset (bonus points)
        query_words = query_lower.split()
        name_matches = sum(1 for word in query_words if len(word) > 3 and word in name)
        score += name_matches * 5
        
        return score
    
    def _general_dataset_ranking(self, available_datasets: List[Dict]) -> List[Dict]:
        """Fallback ranking when we can't classify the query."""
        
        # Prefer datasets with common analysis fields
        common_fields = ["service_name", "timestamp", "duration", "error"]
        
        scored = []
        for dataset in available_datasets:
            score = 10  # Base score
            name = dataset.get('name', '').lower()
            
            # Prefer trace/metric datasets for general analysis
            if any(t in name for t in ["trace", "span", "metric", "service"]):
                score += 20
            
            # Avoid system/internal datasets
            if any(sys in name for sys in ["system", "internal", "monitor/"]):
                score -= 10
            
            dataset_copy = dataset.copy()
            dataset_copy["selection_score"] = score
            scored.append(dataset_copy)
        
        scored.sort(key=lambda x: x["selection_score"], reverse=True)
        return scored


async def get_cached_datasets() -> List[Dict[str, Any]]:
    """Get dataset data from our PostgreSQL cache (much faster than API calls)."""
    try:
        # Import database connection from our existing search module
        from .search import get_db_connection
        
        print(f"[DIRECT_SELECTOR] Loading datasets from cache...")
        
        conn = await get_db_connection()
        
        try:
            # Get all non-excluded datasets with their metadata
            query = """
            SELECT 
                dataset_id,
                name,
                description,
                typical_usage,
                business_category,
                technical_category,
                key_fields,
                dataset_type,
                interfaces,
                last_updated
            FROM dataset_intelligence 
            WHERE excluded = FALSE
            ORDER BY name
            """
            
            results = await conn.fetch(query)
            
            datasets = []
            for row in results:
                # Convert to dictionary format compatible with our scoring logic
                dataset = {
                    "dataset_id": row["dataset_id"],
                    "meta": {"id": row["dataset_id"]},  # For compatibility with API format
                    "config": {"name": row["name"]},    # For compatibility with API format
                    "name": row["name"],
                    "description": row["description"],
                    "typical_usage": row["typical_usage"],
                    "business_category": row["business_category"],
                    "technical_category": row["technical_category"],
                    "key_fields": row["key_fields"] or [],
                    "dataset_type": row["dataset_type"],
                    "interfaces": row["interfaces"] or {},
                    "last_updated": row["last_updated"]
                }
                datasets.append(dataset)
            
            print(f"[DIRECT_SELECTOR] Loaded {len(datasets)} datasets from cache")
            return datasets
            
        finally:
            await conn.close()
            
    except Exception as e:
        print(f"[DIRECT_SELECTOR] Error getting cached datasets: {e}")
        import traceback
        traceback.print_exc()
        return []


async def find_datasets_direct(user_query: str, limit: int = 3) -> List[Dict[str, Any]]:
    """
    Direct dataset selection using field requirements and interface types.
    
    This is a simpler, more reliable alternative to semantic search.
    """
    try:
        print(f"[DIRECT_SELECTOR] Starting direct dataset selection")
        
        # Get all available datasets from cache (much faster!)
        all_datasets = await get_cached_datasets()
        if not all_datasets:
            print(f"[DIRECT_SELECTOR] No datasets available")
            return []
        
        print(f"[DIRECT_SELECTOR] Found {len(all_datasets)} total datasets")
        
        # Use direct selector
        selector = DirectDatasetSelector()
        suitable_datasets = await selector.select_datasets_simple(user_query, all_datasets)
        
        # Return top results
        return suitable_datasets[:limit]
        
    except Exception as e:
        print(f"[DIRECT_SELECTOR] Error in direct selection: {e}")
        import traceback
        traceback.print_exc()
        return []


# Test the direct selector
if __name__ == "__main__":
    async def test_direct_selector():
        test_queries = [
            "Show me error rates by service",
            "Find slow traces over 2 seconds", 
            "Analyze log patterns for exceptions",
            "Display CPU usage by pod",
            "Service performance metrics"
        ]
        
        for query in test_queries:
            print(f"\n{'='*60}")
            print(f"Testing: {query}")
            results = await find_datasets_direct(query, limit=3)
            print(f"Found {len(results)} datasets")
            for r in results:
                print(f"  - {r.get('name', 'Unknown')} (score: {r.get('selection_score', 0)})")
    
    asyncio.run(test_direct_selector())
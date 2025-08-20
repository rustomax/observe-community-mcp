"""
High-level query operations for the OPAL Memory System
"""

import os
import sys
from datetime import datetime
from typing import List, Optional, Tuple
from .database import get_db
from .models import SuccessfulQuery, QueryMatch
from .similarity import QueryMatcher


# Configuration from environment variables
SIMILARITY_THRESHOLD = float(os.getenv("OPAL_MEMORY_SIMILARITY_THRESHOLD", "0.85"))
MAX_ENTRIES_PER_DATASET = int(os.getenv("OPAL_MEMORY_MAX_ENTRIES_PER_DATASET", "50000"))
CLEANUP_DAYS = int(os.getenv("OPAL_MEMORY_CLEANUP_DAYS", "90"))
MEMORY_ENABLED = os.getenv("OPAL_MEMORY_ENABLED", "true").lower() == "true"


async def is_memory_enabled() -> bool:
    """Check if the OPAL memory system is enabled"""
    return MEMORY_ENABLED


async def store_successful_query(
    dataset_id: str,
    nlp_query: str,
    opal_query: str,
    row_count: Optional[int] = None,
    time_range: Optional[str] = None
) -> bool:
    """
    Store a successful OPAL query pattern.
    Returns True if stored successfully, False otherwise.
    """
    if not await is_memory_enabled():
        print("OPAL Memory system is disabled", file=sys.stderr)
        return False
    
    try:
        # Create query matcher to generate hash
        matcher = QueryMatcher(SIMILARITY_THRESHOLD)
        query_hash = matcher.hash_query(nlp_query)
        
        # Generate semantic embedding using OpenAI
        semantic_embedding = None
        try:
            from .embeddings import generate_query_embedding, get_embedding_generator
            generator = get_embedding_generator()
            if generator.is_available:
                embedding_list = await generate_query_embedding(nlp_query)
                if embedding_list:
                    semantic_embedding = generator.embedding_to_pgvector(embedding_list)
                    print(f"Generated OpenAI semantic embedding for query", file=sys.stderr)
        except Exception as embed_error:
            print(f"Error generating OpenAI embedding: {embed_error}", file=sys.stderr)
        
        # Create the successful query record
        successful_query = SuccessfulQuery(
            dataset_id=dataset_id,
            nlp_query_hash=query_hash,
            nlp_query=nlp_query,
            opal_query=opal_query,
            execution_time=datetime.utcnow(),
            row_count=row_count,
            time_range=time_range,
            semantic_embedding=semantic_embedding
        )
        
        # Get database connection and store
        db = await get_db()
        query_id = await db.store_successful_query(successful_query)
        
        print(f"Stored successful OPAL query (ID: {query_id}) for dataset {dataset_id}", file=sys.stderr)
        return True
        
    except Exception as e:
        print(f"Error storing successful query: {e}", file=sys.stderr)
        return False


async def find_matching_queries(
    dataset_id: str,
    nlp_query: str,
    time_range: Optional[str] = None,
    max_matches: int = 3
) -> List[QueryMatch]:
    """
    Find matching queries for a natural language request using semantic search.
    Returns a list of QueryMatch objects sorted by confidence.
    
    Strategy:
    1. Try exact hash match first (fastest)
    2. Try semantic similarity search within same dataset
    3. Try cross-dataset semantic matching as fallback
    4. Fallback to string-only matching if semantic unavailable
    """
    if not await is_memory_enabled():
        return []
    
    try:
        db = await get_db()
        matcher = QueryMatcher(SIMILARITY_THRESHOLD)
        
        # Step 1: Try exact match
        query_hash = matcher.hash_query(nlp_query)
        exact_match = await db.find_exact_match(dataset_id, query_hash)
        
        if exact_match:
            print(f"Found exact hash match for query in dataset {dataset_id}", file=sys.stderr)
            return [QueryMatch(
                query=exact_match,
                similarity_score=1.0,
                match_type='exact',
                confidence=1.0
            )]
        
        # Step 2: Try semantic similarity search
        try:
            from .semantic import create_semantic_matcher
            semantic_matcher = create_semantic_matcher()
            
            if semantic_matcher.is_semantic_available:
                # Generate embedding for target query using OpenAI
                from .embeddings import generate_query_embedding, get_embedding_generator
                generator = get_embedding_generator()
                target_embedding = await generate_query_embedding(nlp_query)
                
                if target_embedding:
                    # Convert to pgvector format
                    embedding_str = generator.embedding_to_pgvector(target_embedding)
                    
                    # Search for semantic matches in same dataset
                    semantic_results = await db.find_semantic_similar_queries(
                        dataset_id, embedding_str, SIMILARITY_THRESHOLD, limit=max_matches * 2
                    )
                    
                    if semantic_results:
                        print(f"Found {len(semantic_results)} semantic matches in same dataset", file=sys.stderr)
                        
                        # Convert to QueryMatch objects with hybrid scoring and time-aware matching
                        matches = []
                        for query, db_similarity in semantic_results:
                            # Calculate string similarity for hybrid score
                            string_similarity = matcher.calculate_similarity(nlp_query, query.nlp_query)
                            
                            # Hybrid score (semantic 60%, string 40%)
                            hybrid_score = 0.6 * db_similarity + 0.4 * string_similarity
                            
                            # Apply enhanced time-aware matching
                            confidence = hybrid_score
                            
                            # Time-aware similarity assessment
                            try:
                                from .domain import get_domain_mapper
                                domain_mapper = get_domain_mapper()
                                
                                # Classify time contexts
                                target_time_context = domain_mapper.classify_time_context(nlp_query)
                                candidate_time_context = domain_mapper.classify_time_context(query.nlp_query)
                                
                                print(f"[TIME_AWARE] Target: {target_time_context}, Candidate: {candidate_time_context}", file=sys.stderr)
                                
                                # Enhanced time compatibility scoring
                                time_aware_similarity = domain_mapper.calculate_time_aware_similarity(
                                    nlp_query, query.nlp_query
                                )
                                
                                # Boost confidence for high time compatibility
                                if time_aware_similarity > 0.8:
                                    confidence *= 1.15
                                    print(f"[TIME_AWARE] High compatibility boost: {time_aware_similarity:.2f}", file=sys.stderr)
                                elif time_aware_similarity < 0.4:
                                    confidence *= 0.85
                                    print(f"[TIME_AWARE] Low compatibility penalty: {time_aware_similarity:.2f}", file=sys.stderr)
                                else:
                                    confidence *= (0.95 + 0.1 * time_aware_similarity)  # Gradual scaling
                                    
                            except Exception as time_error:
                                print(f"[TIME_AWARE] Error in time-aware matching: {time_error}", file=sys.stderr)
                                # Fallback to original time range compatibility
                                if time_range and not _is_time_range_compatible(query.time_range, time_range):
                                    confidence *= 0.9
                            
                            # Apply recency and quality factors
                            from datetime import datetime, timedelta
                            age_days = (datetime.utcnow() - query.created_at).days
                            if age_days <= 7:
                                confidence *= 1.05
                            elif age_days > 90:
                                confidence *= 0.95
                            
                            if query.row_count is not None and 10 <= query.row_count <= 10000:
                                confidence *= 1.02
                            
                            match = QueryMatch(
                                query=query,
                                similarity_score=hybrid_score,
                                match_type='semantic_time_aware',
                                confidence=min(1.0, max(0.0, confidence))
                            )
                            matches.append(match)
                        
                        # Sort by confidence and return top matches
                        matches.sort(key=lambda x: x.confidence, reverse=True)
                        return matches[:max_matches]
                
        except ImportError:
            print("Semantic search dependencies not available, falling back to string matching", file=sys.stderr)
        except Exception as semantic_error:
            print(f"Error in semantic search: {semantic_error}, falling back to string matching", file=sys.stderr)
        
        # Step 3: Fallback to original string-based fuzzy matching
        same_dataset_queries = await db.find_similar_queries(dataset_id, nlp_query, limit=20)
        if same_dataset_queries:
            print(f"Searching {len(same_dataset_queries)} queries from same dataset for fuzzy matches", file=sys.stderr)
            fuzzy_matches = matcher.find_fuzzy_matches(nlp_query, same_dataset_queries)
            
            if fuzzy_matches:
                # Filter by time range compatibility if specified
                if time_range:
                    compatible_matches = []
                    for match in fuzzy_matches:
                        if _is_time_range_compatible(match.query.time_range, time_range):
                            compatible_matches.append(match)
                        else:
                            # Reduce confidence for incompatible time ranges
                            match.confidence *= 0.9
                            compatible_matches.append(match)
                    fuzzy_matches = compatible_matches
                
                print(f"Found {len(fuzzy_matches)} fuzzy matches in same dataset", file=sys.stderr)
                return fuzzy_matches[:max_matches]
        
        # Step 4: Try cross-dataset matching as last resort
        cross_dataset_queries = await db.find_cross_dataset_queries(nlp_query, dataset_id, limit=30)
        if cross_dataset_queries:
            print(f"Searching {len(cross_dataset_queries)} queries from other datasets for cross-dataset matches", file=sys.stderr)
            cross_matches = matcher.find_cross_dataset_matches(nlp_query, cross_dataset_queries)
            
            if cross_matches:
                print(f"Found {len(cross_matches)} cross-dataset matches", file=sys.stderr)
                return cross_matches[:max_matches]
        
        print(f"No matching queries found for: {nlp_query[:50]}...", file=sys.stderr)
        return []
        
    except Exception as e:
        print(f"Error finding matching queries: {e}", file=sys.stderr)
        return []


def _is_time_range_compatible(stored_range: Optional[str], requested_range: Optional[str]) -> bool:
    """
    Check if stored time range is compatible with requested time range.
    Compatible means they're similar enough that the query pattern would work.
    """
    if not stored_range or not requested_range:
        return True  # Assume compatible if either is missing
    
    # Normalize time ranges for comparison
    stored_norm = _normalize_time_range(stored_range)
    requested_norm = _normalize_time_range(requested_range)
    
    if stored_norm == requested_norm:
        return True
    
    # Check if they're in the same category (minutes, hours, days)
    stored_category = _get_time_range_category(stored_norm)
    requested_category = _get_time_range_category(requested_norm)
    
    return stored_category == requested_category


def _normalize_time_range(time_range: str) -> str:
    """Normalize time range string for comparison"""
    return time_range.lower().strip().replace(' ', '')


def _get_time_range_category(time_range: str) -> str:
    """Get the category of a time range (minutes, hours, days, etc.)"""
    if 'm' in time_range or 'min' in time_range:
        return 'minutes'
    elif 'h' in time_range or 'hour' in time_range:
        return 'hours'  
    elif 'd' in time_range or 'day' in time_range:
        return 'days'
    elif 'w' in time_range or 'week' in time_range:
        return 'weeks'
    else:
        return 'other'


async def get_memory_stats() -> dict:
    """Get statistics about the memory system"""
    if not await is_memory_enabled():
        return {"enabled": False}
    
    try:
        db = await get_db()
        stats = await db.get_stats()
        
        return {
            "enabled": True,
            "total_queries": stats.total_queries,
            "unique_datasets": stats.unique_datasets,
            "hit_rate": stats.hit_rate,
            "similarity_threshold": SIMILARITY_THRESHOLD,
            "max_entries_per_dataset": MAX_ENTRIES_PER_DATASET,
            "cleanup_days": CLEANUP_DAYS,
            "oldest_entry": stats.oldest_entry.isoformat() if stats.oldest_entry else None,
            "newest_entry": stats.newest_entry.isoformat() if stats.newest_entry else None
        }
        
    except Exception as e:
        print(f"Error getting memory stats: {e}", file=sys.stderr)
        return {"enabled": True, "error": str(e)}


async def cleanup_memory(
    days_old: Optional[int] = None,
    dataset_id: Optional[str] = None,
    max_entries: Optional[int] = None
) -> dict:
    """
    Perform cleanup operations on the memory system.
    
    Args:
        days_old: Remove entries older than this many days (default: CLEANUP_DAYS)
        dataset_id: If specified, only cleanup this dataset
        max_entries: If specified, limit dataset to this many entries (default: MAX_ENTRIES_PER_DATASET)
    """
    if not await is_memory_enabled():
        return {"enabled": False}
    
    try:
        db = await get_db()
        results = []
        
        # Age-based cleanup
        if days_old is None:
            days_old = CLEANUP_DAYS
            
        age_result = await db.cleanup_old_entries(days_old)
        results.append({
            "type": "age_based",
            "days": days_old,
            "entries_removed": age_result.entries_removed,
            "execution_time": age_result.execution_time,
            "errors": age_result.errors
        })
        
        # Size-based cleanup for specific dataset or all datasets
        if dataset_id:
            if max_entries is None:
                max_entries = MAX_ENTRIES_PER_DATASET
            
            size_result = await db.cleanup_by_dataset_limit(dataset_id, max_entries)
            results.append({
                "type": "size_based",
                "dataset_id": dataset_id,
                "max_entries": max_entries,
                "entries_removed": size_result.entries_removed,
                "execution_time": size_result.execution_time,
                "errors": size_result.errors
            })
        
        total_removed = sum(result["entries_removed"] for result in results)
        total_time = sum(result["execution_time"] for result in results)
        
        print(f"Memory cleanup completed: {total_removed} entries removed in {total_time:.2f}s", file=sys.stderr)
        
        return {
            "enabled": True,
            "success": True,
            "total_entries_removed": total_removed,
            "total_execution_time": total_time,
            "operations": results
        }
        
    except Exception as e:
        print(f"Error during memory cleanup: {e}", file=sys.stderr)
        return {"enabled": True, "success": False, "error": str(e)}


async def health_check() -> dict:
    """Check health of the memory system"""
    if not await is_memory_enabled():
        return {"enabled": False, "healthy": True, "message": "Memory system is disabled"}
    
    try:
        db = await get_db()
        is_healthy = await db.health_check()
        
        if is_healthy:
            stats = await get_memory_stats()
            return {
                "enabled": True,
                "healthy": True,
                "message": "Memory system is operational",
                "stats": stats
            }
        else:
            return {
                "enabled": True,
                "healthy": False,
                "message": "Database connection failed"
            }
            
    except Exception as e:
        print(f"Memory system health check failed: {e}", file=sys.stderr)
        return {
            "enabled": True,
            "healthy": False,
            "message": f"Health check error: {str(e)}"
        }
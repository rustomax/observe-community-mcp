"""
Semantic dataset discovery using dataset intelligence database.
"""

import os
import asyncio
import asyncpg
from typing import List, Optional, Dict, Any
from openai import AsyncOpenAI
import json
from .intent_classification import IntentClassifier, DatasetScorer
from src.logging import get_logger

logger = get_logger('DATASET_SEARCH')


async def get_db_connection():
    """Get a connection to the semantic graph database."""
    # Use Docker service name when running in container, localhost for local development
    host = os.getenv("POSTGRES_HOST", "localhost")
    return await asyncpg.connect(
        host=host,
        port=5432,
        database=os.getenv("POSTGRES_DB", "semantic_graph"), 
        user=os.getenv("POSTGRES_USER", "semantic_graph"),
        password=os.getenv("POSTGRES_PASSWORD", os.getenv("SEMANTIC_GRAPH_PASSWORD", "semantic_graph_secure_2024!"))
    )


async def generate_query_embedding(query: str) -> Optional[List[float]]:
    """Generate embedding for a user query."""
    try:
        openai_client = AsyncOpenAI()
        response = await openai_client.embeddings.create(
            model="text-embedding-3-small",
            input=query
        )
        return response.data[0].embedding
    except Exception as e:
        logger.error(f"error generating embedding | error:{e}")
        return None


async def find_relevant_datasets(
    user_query: str, 
    limit: int = 5,
    similarity_threshold: float = 0.5  # Lowered to allow intent scoring to dominate
) -> List[Dict[str, Any]]:
    """
    Find datasets most relevant to a user's natural language query.
    
    Uses semantic similarity search on dataset descriptions and typical usage patterns.
    
    Args:
        user_query: Natural language description of what the user wants to analyze
        limit: Maximum number of datasets to return
        similarity_threshold: Minimum similarity score (0-1) to include results
        
    Returns:
        List of dictionaries containing dataset information:
        - dataset_id: The dataset ID to use for queries
        - name: Human-readable dataset name
        - description: What the dataset contains
        - similarity_score: How well it matches the query (0-1)
        - business_category: e.g., Application, Infrastructure, etc.
        - technical_category: e.g., Events, Metrics, Traces, etc.
        - key_fields: Important fields for investigations
    """
    try:
        logger.debug(f"enhanced search for: '{user_query[:50]}...'")
        
        # Step 1: Classify query intent
        classifier = IntentClassifier()
        scorer = DatasetScorer()
        
        intent = classifier.classify_intent(user_query)
        logger.debug(f"intent: {intent.primary} (confidence: {intent.confidence:.2f})")
        logger.debug(f"required fields: {intent.required_fields}")
        
        # Step 2: Get broader set of candidates via semantic search
        query_embedding = await generate_query_embedding(user_query)
        if not query_embedding:
            logger.warning("failed to generate embedding")
            return []
        
        # Convert embedding to PostgreSQL vector format
        embedding_str = "[" + ",".join(map(str, query_embedding)) + "]"
        
        conn = await get_db_connection()
        
        try:
            # Search using combined embedding (description + schema + typical usage)
            # Get more candidates for intent-based scoring
            query = """
            SELECT 
                dataset_id,
                name,
                description,
                typical_usage,
                business_category,
                technical_category,
                key_fields,
                (combined_embedding <=> $1::vector) AS similarity_distance,
                (1 - (combined_embedding <=> $1::vector)) AS similarity_score
            FROM dataset_intelligence 
            WHERE excluded = FALSE 
                AND combined_embedding IS NOT NULL
                AND (1 - (combined_embedding <=> $1::vector)) >= $2
            ORDER BY combined_embedding <=> $1::vector
            LIMIT $3
            """
            
            # Get more candidates for intent scoring (up to limit * 3)
            results = await conn.fetch(query, embedding_str, similarity_threshold, limit * 3)
            
            if not results:
                logger.debug("no semantic matches found")
                return []
            
            # Step 3: Apply intent-based scoring to refine selection
            scored_datasets = []
            for row in results:
                dataset = {
                    "dataset_id": row["dataset_id"],
                    "name": row["name"],
                    "description": row["description"],
                    "typical_usage": row["typical_usage"],
                    "business_category": row["business_category"],
                    "technical_category": row["technical_category"],
                    "key_fields": row["key_fields"] or [],
                    "similarity_score": float(row["similarity_score"])
                }
                
                # Get schema fields for better scoring
                schema_fields = row["key_fields"] or []
                
                # Calculate intent-based score
                intent_score = scorer.score_dataset_for_intent(dataset, intent, schema_fields)
                dataset["intent_score"] = intent_score
                dataset["combined_score"] = (intent_score + dataset["similarity_score"] * 30) / 2
                
                scored_datasets.append(dataset)
            
            # Sort by combined score and take top results
            scored_datasets.sort(key=lambda x: x["combined_score"], reverse=True)
            final_datasets = scored_datasets[:limit]
            
            if final_datasets:
                logger.info(f"selected intent-scored matches | count:{len(final_datasets)}")
                for i, ds in enumerate(final_datasets, 1):
                    logger.info(f"dataset match {i} | name:{ds['name']} | intent:{ds['intent_score']:.1f} | semantic:{ds['similarity_score']:.3f}")
            else:
                logger.warning("no suitable datasets found after intent scoring")
            
            return final_datasets
            
        finally:
            await conn.close()
            
    except Exception as e:
        logger.error(f"enhanced search error | error:{e}")
        return []


async def find_datasets_by_keywords(
    user_query: str,
    limit: int = 5
) -> List[Dict[str, Any]]:
    """
    Fallback function to find datasets using keyword matching when semantic search fails.
    
    This is used when the semantic search doesn't return enough results or embeddings fail.
    """
    try:
        logger.debug(f"keyword search fallback | query:{user_query[:50]}...")
        
        conn = await get_db_connection()
        
        try:
            # Extract keywords from query for text search
            keywords = user_query.lower().split()
            
            query = """
            SELECT 
                dataset_id,
                name,
                description,
                typical_usage,
                business_category,
                technical_category,
                key_fields,
                0.5 AS similarity_score  -- Default score for keyword matches
            FROM dataset_intelligence 
            WHERE excluded = FALSE 
                AND (
                    LOWER(name) LIKE ANY($1) 
                    OR LOWER(description) LIKE ANY($1)
                    OR LOWER(typical_usage) LIKE ANY($1)
                    OR LOWER(business_category) LIKE ANY($1)
                    OR LOWER(technical_category) LIKE ANY($1)
                )
            ORDER BY 
                CASE 
                    WHEN LOWER(name) LIKE ANY($1) THEN 1
                    WHEN LOWER(description) LIKE ANY($1) THEN 2
                    WHEN LOWER(typical_usage) LIKE ANY($1) THEN 3
                    ELSE 4
                END
            LIMIT $2
            """
            
            # Create patterns for LIKE search
            patterns = [f"%{keyword}%" for keyword in keywords]
            
            results = await conn.fetch(query, patterns, limit)
            
            datasets = []
            for row in results:
                datasets.append({
                    "dataset_id": row["dataset_id"],
                    "name": row["name"],
                    "description": row["description"],
                    "typical_usage": row["typical_usage"],
                    "business_category": row["business_category"],
                    "technical_category": row["technical_category"],
                    "key_fields": row["key_fields"] or [],
                    "similarity_score": float(row["similarity_score"])
                })
            
            if datasets:
                logger.info(f"found keyword matches | count:{len(datasets)}")
                for i, ds in enumerate(datasets[:3], 1):  # Show top 3
                    logger.info(f"dataset match {i} | name:{ds['name']} | categories:{ds['business_category']}/{ds['technical_category']}")
            else:
                logger.warning("no keyword matches found")
            
            return datasets
            
        finally:
            await conn.close()
            
    except Exception as e:
        logger.error(f"keyword search error | error:{e}")
        return []
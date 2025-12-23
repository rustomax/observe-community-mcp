"""
Skills documentation search using ParadeDB BM25

Provides fast, local skill documentation search without external API dependencies.
Uses BM25 ranking algorithm via ParadeDB for better results than PostgreSQL full-text.
"""

import asyncpg
import os
from typing import List, Dict, Any, Optional
from src.logging import get_logger

logger = get_logger('SKILLS')

# Cache for database connection pool
_db_pool: Optional[asyncpg.Pool] = None


async def get_db_pool() -> asyncpg.Pool:
    """Get or create database connection pool."""
    global _db_pool

    if _db_pool is None:
        db_password = os.getenv('SEMANTIC_GRAPH_PASSWORD')
        if not db_password:
            raise ValueError("SEMANTIC_GRAPH_PASSWORD environment variable not set")

        db_config = {
            'host': os.getenv('POSTGRES_HOST', 'localhost'),
            'port': int(os.getenv('POSTGRES_PORT', '5432')),
            'database': os.getenv('POSTGRES_DB', 'semantic_graph'),
            'user': os.getenv('POSTGRES_USER', 'semantic_graph'),
            'password': db_password
        }

        _db_pool = await asyncpg.create_pool(**db_config, min_size=1, max_size=10)
        logger.info("Skills search database pool created")

    return _db_pool


async def search_skills_bm25(
    query: str,
    n_results: int = 5,
    category_filter: Optional[str] = None,
    difficulty_filter: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Search skills using BM25 ranking via ParadeDB.

    Args:
        query: Search query text
        n_results: Number of results to return (default: 5)
        category_filter: Optional category filter (e.g., "Aggregation", "Filtering")
        difficulty_filter: Optional difficulty filter (e.g., "beginner", "intermediate", "advanced")

    Returns:
        List of skill results with BM25 scores, compatible with MCP tool format
    """
    try:
        pool = await get_db_pool()

        logger.info(f"BM25 skills search | query:'{query[:100]}' | n_results:{n_results}")

        async with pool.acquire() as conn:
            # Use the helper function from schema
            results = await conn.fetch("""
                SELECT * FROM search_skills_bm25($1, $2, $3, $4)
            """, query, n_results, category_filter, difficulty_filter)

            if not results:
                # Try fuzzy search as fallback
                logger.debug(f"No BM25 results, trying fuzzy search for: {query}")
                results = await conn.fetch("""
                    SELECT * FROM search_skills_fuzzy($1, $2)
                """, query, n_results)

            # Format results for MCP tool
            formatted_results = []
            for i, row in enumerate(results):
                score = row.get('relevance_score', row.get('similarity_score', 1.0))

                formatted_results.append({
                    "id": row['skill_id'],
                    "score": float(score),
                    "text": row['content'],
                    "source": f"skill:{row['skill_id']}",
                    "title": row['skill_name'],
                    "metadata": {
                        "category": row.get('category'),
                        "difficulty": row.get('difficulty'),
                        "tags": row.get('tags', []),
                        "description": row.get('description', '')
                    }
                })

            logger.info(f"BM25 search complete | results:{len(formatted_results)} | query:'{query}'")
            return formatted_results

    except Exception as e:
        logger.error(f"Skills search error | error:{e} | query:'{query}'")
        return [{
            "id": "error",
            "score": 1.0,
            "text": f"Error searching skills: {str(e)}",
            "source": "error",
            "title": "Search Error"
        }]


async def get_skill_by_id(skill_id: str) -> Optional[Dict[str, Any]]:
    """
    Get a specific skill by ID.

    Args:
        skill_id: Skill identifier

    Returns:
        Skill data or None if not found
    """
    try:
        pool = await get_db_pool()

        async with pool.acquire() as conn:
            result = await conn.fetchrow("""
                SELECT * FROM skills_intelligence WHERE skill_id = $1
            """, skill_id)

            if result:
                return {
                    "id": result['skill_id'],
                    "score": 1.0,
                    "text": result['content'],
                    "source": f"skill:{result['skill_id']}",
                    "title": result['skill_name'],
                    "metadata": {
                        "category": result.get('category'),
                        "difficulty": result.get('difficulty'),
                        "tags": result.get('tags', []),
                        "description": result.get('description', '')
                    }
                }

            return None

    except Exception as e:
        logger.error(f"Error fetching skill {skill_id}: {e}")
        return None


async def list_all_skills() -> List[Dict[str, str]]:
    """
    List all available skills.

    Returns:
        List of skill summaries (id, name, category, difficulty)
    """
    try:
        pool = await get_db_pool()

        async with pool.acquire() as conn:
            results = await conn.fetch("""
                SELECT skill_id, skill_name, category, difficulty, description
                FROM skills_intelligence
                ORDER BY category, skill_name
            """)

            return [
                {
                    "id": row['skill_id'],
                    "name": row['skill_name'],
                    "category": row.get('category', 'General'),
                    "difficulty": row.get('difficulty', 'intermediate'),
                    "description": row.get('description', '')[:200]  # Truncate for list view
                }
                for row in results
            ]

    except Exception as e:
        logger.error(f"Error listing skills: {e}")
        return []


async def get_skills_stats() -> Dict[str, Any]:
    """
    Get statistics about the skills database.

    Returns:
        Dictionary with skill counts by category, difficulty, etc.
    """
    try:
        pool = await get_db_pool()

        async with pool.acquire() as conn:
            total = await conn.fetchval("SELECT COUNT(*) FROM skills_intelligence")

            by_category = await conn.fetch("""
                SELECT category, COUNT(*) as count
                FROM skills_intelligence
                GROUP BY category
                ORDER BY count DESC
            """)

            by_difficulty = await conn.fetch("""
                SELECT difficulty, COUNT(*) as count
                FROM skills_intelligence
                GROUP BY difficulty
                ORDER BY count DESC
            """)

            return {
                "total_skills": total,
                "by_category": {row['category']: row['count'] for row in by_category},
                "by_difficulty": {row['difficulty']: row['count'] for row in by_difficulty}
            }

    except Exception as e:
        logger.error(f"Error getting skills stats: {e}")
        return {"error": str(e)}


# Cleanup function for graceful shutdown
async def close_db_pool():
    """Close the database connection pool."""
    global _db_pool
    if _db_pool:
        await _db_pool.close()
        _db_pool = None
        logger.info("Skills search database pool closed")

"""
PostgreSQL BM25 document search operations

Provides BM25-based semantic search functionality for docs,
replacing Pinecone vector search with PostgreSQL full-text search.
"""

import os
import sys
import asyncpg
from typing import List, Dict, Any, Optional
from src.logging import semantic_logger

# Import telemetry decorators
try:
    from src.telemetry.decorators import trace_database_operation
    from src.telemetry.utils import add_database_context
except ImportError:
    # Fallback decorators if telemetry is not available
    def trace_database_operation(operation=None, table=None):
        def decorator(func):
            return func
        return decorator

    def add_database_context(span, **kwargs):
        pass

# Database connection configuration
# Supports both Docker (port 5433) and local PostgreSQL (port 5432)
DATABASE_URL = f"postgresql://{os.getenv('POSTGRES_USER', 'semantic_graph')}:{os.getenv('SEMANTIC_GRAPH_PASSWORD', 'g83hbeyB32792r3Gsjnfwe0ihf2')}@{os.getenv('POSTGRES_HOST', 'localhost')}:{os.getenv('POSTGRES_PORT', '5432')}/{os.getenv('POSTGRES_DB', 'semantic_graph')}"


@trace_database_operation(operation="bm25_search", table="documentation_chunks")
async def search_docs_bm25(query: str, n_results: int = 5) -> List[Dict[str, Any]]:
    """
    Perform BM25-based document search using PostgreSQL

    Args:
        query: Search query text
        n_results: Number of results to return (default: 5)

    Returns:
        List of search results with metadata, compatible with Pinecone format
    """
    try:
        semantic_logger.debug(f"BM25 docs search | query:{query[:100]} | results:{n_results}")

        # Connect to database
        conn = await asyncpg.connect(DATABASE_URL)

        try:
            # Check if ParadeDB search extension is available
            ext_exists = await conn.fetchval("""
                SELECT EXISTS(SELECT 1 FROM pg_extension WHERE extname = 'pg_search')
            """)

            if ext_exists:
                # Use BM25 search
                results = await _search_with_bm25(conn, query, n_results)
                semantic_logger.debug("using BM25 search")
            else:
                # Fallback to basic full-text search
                results = await _search_with_fulltext(conn, query, n_results)
                semantic_logger.debug("using full-text search fallback")

            # Format results to match Pinecone format
            formatted_results = []
            for row in results:
                formatted_results.append({
                    "id": str(row['id']),
                    "score": float(row['score']),
                    "text": row['text'],
                    "source": row['source'],
                    "title": row['title']
                })

            semantic_logger.debug(f"BM25 search complete | found:{len(formatted_results)} results")
            return formatted_results

        finally:
            await conn.close()

    except Exception as e:
        semantic_logger.error(f"BM25 search error | error:{e}")
        return [{
            "id": "error",
            "score": 1.0,
            "text": f"Error in BM25 search: {str(e)}. Your query was: {query}",
            "source": "error",
            "title": "PostgreSQL Search Error"
        }]


@trace_database_operation(operation="bm25_query", table="documentation_chunks")
async def _search_with_bm25(conn: asyncpg.Connection, query: str, n_results: int) -> List[Dict[str, Any]]:
    """Search using ParadeDB BM25 with @@@ operator"""
    try:
        # ParadeDB BM25 search - uses @@@ operator and paradedb.score() for scoring
        # Note: ParadeDB requires the BM25 index to be created with the exact syntax
        results = await conn.fetch("""
            SELECT
                id,
                text,
                source,
                title,
                paradedb.score(id) as score
            FROM documentation_chunks
            WHERE text @@@ $1 OR title @@@ $1
            ORDER BY paradedb.score(id) DESC
            LIMIT $2
        """, query, n_results)

        return [dict(row) for row in results]

    except Exception as e:
        semantic_logger.error(f"ParadeDB BM25 query error | error:{e}")
        # Fallback to simple text search without scoring
        try:
            results = await conn.fetch("""
                SELECT
                    id,
                    text,
                    source,
                    title,
                    1.0 as score
                FROM documentation_chunks
                WHERE text @@@ $1
                ORDER BY id
                LIMIT $2
            """, query, n_results)

            return [dict(row) for row in results]

        except Exception as e2:
            semantic_logger.error(f"fallback BM25 query error | error:{e2}")
            raise


@trace_database_operation(operation="fulltext_search", table="documentation_chunks")
async def _search_with_fulltext(conn: asyncpg.Connection, query: str, n_results: int) -> List[Dict[str, Any]]:
    """Fallback search using PostgreSQL full-text search"""
    try:
        results = await conn.fetch("""
            SELECT
                id,
                text,
                source,
                title,
                (
                    ts_rank(to_tsvector('english', text), plainto_tsquery('english', $1)) +
                    (ts_rank(to_tsvector('english', title), plainto_tsquery('english', $1)) * 2.0)
                ) as score
            FROM documentation_chunks
            WHERE to_tsvector('english', text || ' ' || title) @@ plainto_tsquery('english', $1)
            ORDER BY score DESC
            LIMIT $2
        """, query, n_results)

        return [dict(row) for row in results]

    except Exception as e:
        semantic_logger.error(f"full-text search error | error:{e}")
        raise


@trace_database_operation(operation="stats_query", table="documentation_chunks")
async def get_documentation_stats() -> Dict[str, Any]:
    """Get statistics about the documentation corpus"""
    try:
        conn = await asyncpg.connect(DATABASE_URL)

        try:
            stats = await conn.fetchrow("""
                SELECT
                    COUNT(*) as total_chunks,
                    COUNT(DISTINCT source) as total_documents,
                    AVG(chunk_size) as avg_chunk_size,
                    MAX(updated_at) as last_updated
                FROM documentation_chunks
            """)

            # Check if ParadeDB search extension is available
            ext_exists = await conn.fetchval("""
                SELECT EXISTS(SELECT 1 FROM pg_extension WHERE extname = 'pg_search')
            """)

            return {
                "total_chunks": stats['total_chunks'],
                "total_documents": stats['total_documents'],
                "avg_chunk_size": float(stats['avg_chunk_size']) if stats['avg_chunk_size'] else 0,
                "last_updated": stats['last_updated'].isoformat() if stats['last_updated'] else None,
                "search_type": "BM25" if ext_exists else "Full-Text",
                "extension_available": ext_exists
            }

        finally:
            await conn.close()

    except Exception as e:
        semantic_logger.error(f"error getting documentation stats | error:{e}")
        return {
            "total_chunks": 0,
            "total_documents": 0,
            "avg_chunk_size": 0,
            "last_updated": None,
            "search_type": "Error",
            "extension_available": False,
            "error": str(e)
        }


async def test_search_quality(test_queries: List[str] = None) -> Dict[str, Any]:
    """Test search quality with common queries"""
    if test_queries is None:
        test_queries = [
            "OPAL filter syntax",
            "error analysis logs",
            "dataset discovery",
            "metrics aggregation",
            "time series queries"
        ]

    results = {}

    for query in test_queries:
        try:
            search_results = await search_docs_bm25(query, n_results=3)
            results[query] = {
                "result_count": len(search_results),
                "top_score": search_results[0]['score'] if search_results else 0,
                "sources": [r['source'] for r in search_results if r.get('source') != 'error']
            }
        except Exception as e:
            results[query] = {
                "error": str(e),
                "result_count": 0,
                "top_score": 0,
                "sources": []
            }

    return results
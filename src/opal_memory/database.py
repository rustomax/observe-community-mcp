"""
Database operations for the OPAL Memory System using PostgreSQL
"""

import os
import sys
import asyncio
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime, timedelta
import asyncpg
from asyncpg import Pool, Connection

from .models import SuccessfulQuery, MemoryStats, CleanupResult


class OPALMemoryDB:
    """PostgreSQL database manager for OPAL memory system"""
    
    def __init__(self):
        self.pool: Optional[Pool] = None
        self.host = os.getenv("POSTGRES_HOST", "postgres")
        self.port = int(os.getenv("POSTGRES_PORT", "5432"))
        self.database = os.getenv("POSTGRES_DB", "opal_memory") 
        self.user = os.getenv("POSTGRES_USER", "opal")
        self.password = os.getenv("POSTGRES_PASSWORD", "")
        
        if not self.password:
            raise ValueError("POSTGRES_PASSWORD environment variable is required")

    async def initialize(self) -> None:
        """Initialize database connection pool and create tables if needed"""
        try:
            print(f"Connecting to PostgreSQL at {self.host}:{self.port}", file=sys.stderr)
            
            # Create connection pool
            self.pool = await asyncpg.create_pool(
                host=self.host,
                port=self.port,
                database=self.database,
                user=self.user,
                password=self.password,
                min_size=2,
                max_size=10,
                command_timeout=30
            )
            
            # Create tables if they don't exist
            await self.create_tables()
            print("OPAL Memory database initialized successfully", file=sys.stderr)
            
        except Exception as e:
            print(f"Failed to initialize OPAL Memory database: {e}", file=sys.stderr)
            raise

    async def create_tables(self) -> None:
        """Create database tables if they don't exist"""
        create_table_sql = """
        -- Enable vector extension
        CREATE EXTENSION IF NOT EXISTS vector;
        
        CREATE TABLE IF NOT EXISTS successful_opal_queries (
            id SERIAL PRIMARY KEY,
            dataset_id VARCHAR(255) NOT NULL,
            nlp_query_hash VARCHAR(64) NOT NULL,
            nlp_query TEXT NOT NULL,
            opal_query TEXT NOT NULL,
            execution_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            row_count INTEGER,
            time_range VARCHAR(50),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            semantic_embedding vector(1536), -- Vector embeddings for semantic search (OpenAI text-embedding-3-small)
            UNIQUE(nlp_query_hash, dataset_id)
        );
        
        CREATE INDEX IF NOT EXISTS idx_dataset_hash 
        ON successful_opal_queries(dataset_id, nlp_query_hash);
        
        CREATE INDEX IF NOT EXISTS idx_dataset_created 
        ON successful_opal_queries(dataset_id, created_at DESC);
        
        CREATE INDEX IF NOT EXISTS idx_created_at 
        ON successful_opal_queries(created_at DESC);
        
        -- Vector similarity index for fast semantic search
        CREATE INDEX IF NOT EXISTS idx_semantic_embedding 
        ON successful_opal_queries 
        USING ivfflat (semantic_embedding vector_cosine_ops) WITH (lists = 100);
        """
        
        async with self.pool.acquire() as conn:
            await conn.execute(create_table_sql)

    async def close(self) -> None:
        """Close database connection pool"""
        if self.pool:
            await self.pool.close()
            print("OPAL Memory database connections closed", file=sys.stderr)

    async def store_successful_query(self, query: SuccessfulQuery) -> int:
        """
        Store a successful query pattern. Returns the ID of the stored query.
        Uses ON CONFLICT to handle duplicate hash+dataset combinations.
        """
        insert_sql = """
        INSERT INTO successful_opal_queries 
        (dataset_id, nlp_query_hash, nlp_query, opal_query, execution_time, row_count, time_range, created_at, semantic_embedding)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
        ON CONFLICT (nlp_query_hash, dataset_id) 
        DO UPDATE SET 
            opal_query = EXCLUDED.opal_query,
            execution_time = EXCLUDED.execution_time,
            row_count = EXCLUDED.row_count,
            time_range = EXCLUDED.time_range,
            created_at = EXCLUDED.created_at,
            semantic_embedding = EXCLUDED.semantic_embedding
        RETURNING id;
        """
        
        async with self.pool.acquire() as conn:
            result = await conn.fetchval(
                insert_sql,
                query.dataset_id,
                query.nlp_query_hash,
                query.nlp_query,
                query.opal_query,
                query.execution_time,
                query.row_count,
                query.time_range,
                query.created_at,
                query.semantic_embedding
            )
            return result

    async def find_exact_match(self, dataset_id: str, nlp_query_hash: str) -> Optional[SuccessfulQuery]:
        """Find an exact hash match for a query"""
        select_sql = """
        SELECT * FROM successful_opal_queries 
        WHERE dataset_id = $1 AND nlp_query_hash = $2
        ORDER BY created_at DESC 
        LIMIT 1;
        """
        
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(select_sql, dataset_id, nlp_query_hash)
            if row:
                return SuccessfulQuery(**dict(row))
            return None

    async def find_similar_queries(
        self, 
        dataset_id: str, 
        nlp_query: str, 
        limit: int = 10
    ) -> List[SuccessfulQuery]:
        """
        Find similar queries for fuzzy matching.
        Returns queries from the same dataset, ordered by recency.
        """
        select_sql = """
        SELECT * FROM successful_opal_queries 
        WHERE dataset_id = $1
        ORDER BY created_at DESC 
        LIMIT $2;
        """
        
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(select_sql, dataset_id, limit)
            return [SuccessfulQuery(**dict(row)) for row in rows]

    async def find_cross_dataset_queries(
        self, 
        nlp_query: str, 
        exclude_dataset: str,
        limit: int = 20
    ) -> List[SuccessfulQuery]:
        """
        Find similar queries from other datasets for cross-dataset matching.
        Excludes the current dataset and orders by recency.
        """
        select_sql = """
        SELECT * FROM successful_opal_queries 
        WHERE dataset_id != $1
        ORDER BY created_at DESC 
        LIMIT $2;
        """
        
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(select_sql, exclude_dataset, limit)
            return [SuccessfulQuery(**dict(row)) for row in rows]

    async def find_semantic_similar_queries(
        self,
        dataset_id: str,
        query_embedding: str,  # pgvector format string
        similarity_threshold: float = 0.7,
        limit: int = 10
    ) -> List[Tuple[SuccessfulQuery, float]]:
        """
        Find semantically similar queries using vector similarity.
        Returns list of (query, similarity_score) tuples.
        
        Args:
            dataset_id: Dataset to search within
            query_embedding: Query embedding in pgvector format '[1.0,2.0,...]'
            similarity_threshold: Minimum cosine similarity (0-1)
            limit: Maximum number of results
        
        Returns:
            List of (SuccessfulQuery, similarity_score) sorted by similarity desc
        """
        select_sql = """
        SELECT *, (semantic_embedding <=> $2::vector) as similarity_distance
        FROM successful_opal_queries 
        WHERE dataset_id = $1 
        AND semantic_embedding IS NOT NULL
        AND (1 - (semantic_embedding <=> $2::vector)) >= $3
        ORDER BY semantic_embedding <=> $2::vector ASC
        LIMIT $4;
        """
        
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(select_sql, dataset_id, query_embedding, similarity_threshold, limit)
            
            results = []
            for row in rows:
                # Convert distance to similarity (cosine distance -> cosine similarity)
                similarity_score = 1.0 - row['similarity_distance']
                
                # Create SuccessfulQuery (exclude similarity_distance field)
                row_dict = dict(row)
                del row_dict['similarity_distance']
                query = SuccessfulQuery(**row_dict)
                
                results.append((query, similarity_score))
            
            return results

    async def find_cross_dataset_semantic_queries(
        self,
        exclude_dataset: str,
        query_embedding: str,  # pgvector format string
        similarity_threshold: float = 0.8,  # Higher threshold for cross-dataset
        limit: int = 10
    ) -> List[Tuple[SuccessfulQuery, float]]:
        """
        Find semantically similar queries from other datasets.
        Uses higher similarity threshold since cross-dataset matches are riskier.
        """
        select_sql = """
        SELECT *, (semantic_embedding <=> $2::vector) as similarity_distance
        FROM successful_opal_queries 
        WHERE dataset_id != $1 
        AND semantic_embedding IS NOT NULL
        AND (1 - (semantic_embedding <=> $2::vector)) >= $3
        ORDER BY semantic_embedding <=> $2::vector ASC
        LIMIT $4;
        """
        
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(select_sql, exclude_dataset, query_embedding, similarity_threshold, limit)
            
            results = []
            for row in rows:
                # Convert distance to similarity
                similarity_score = 1.0 - row['similarity_distance']
                
                # Create SuccessfulQuery
                row_dict = dict(row)
                del row_dict['similarity_distance']
                query = SuccessfulQuery(**row_dict)
                
                results.append((query, similarity_score))
            
            return results

    async def get_stats(self) -> MemoryStats:
        """Get statistics about the memory system"""
        stats_sql = """
        SELECT 
            COUNT(*) as total_queries,
            COUNT(DISTINCT dataset_id) as unique_datasets,
            MIN(created_at) as oldest_entry,
            MAX(created_at) as newest_entry
        FROM successful_opal_queries;
        """
        
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(stats_sql)
            return MemoryStats(
                total_queries=row['total_queries'],
                unique_datasets=row['unique_datasets'],
                hit_rate=0.0,  # This would be calculated from usage metrics
                avg_similarity_threshold=0.85,  # Default threshold
                oldest_entry=row['oldest_entry'],
                newest_entry=row['newest_entry']
            )

    async def cleanup_old_entries(self, days_old: int = 90) -> CleanupResult:
        """Remove entries older than specified days"""
        start_time = datetime.utcnow()
        cutoff_date = datetime.utcnow() - timedelta(days=days_old)
        
        delete_sql = """
        DELETE FROM successful_opal_queries 
        WHERE created_at < $1;
        """
        
        try:
            async with self.pool.acquire() as conn:
                result = await conn.execute(delete_sql, cutoff_date)
                # Extract number of deleted rows from result string
                entries_removed = int(result.split()[-1]) if result.startswith("DELETE") else 0
                
                end_time = datetime.utcnow()
                execution_time = (end_time - start_time).total_seconds()
                
                return CleanupResult(
                    entries_removed=entries_removed,
                    cleanup_type=f"age_based_{days_old}_days",
                    execution_time=execution_time,
                    errors=[]
                )
                
        except Exception as e:
            end_time = datetime.utcnow()
            execution_time = (end_time - start_time).total_seconds()
            
            return CleanupResult(
                entries_removed=0,
                cleanup_type=f"age_based_{days_old}_days",
                execution_time=execution_time,
                errors=[str(e)]
            )

    async def cleanup_by_dataset_limit(self, dataset_id: str, max_entries: int = 50000) -> CleanupResult:
        """Remove oldest entries for a dataset if it exceeds the limit"""
        start_time = datetime.utcnow()
        
        delete_sql = """
        DELETE FROM successful_opal_queries 
        WHERE dataset_id = $1 
        AND id NOT IN (
            SELECT id FROM successful_opal_queries 
            WHERE dataset_id = $1 
            ORDER BY created_at DESC 
            LIMIT $2
        );
        """
        
        try:
            async with self.pool.acquire() as conn:
                result = await conn.execute(delete_sql, dataset_id, max_entries)
                entries_removed = int(result.split()[-1]) if result.startswith("DELETE") else 0
                
                end_time = datetime.utcnow()
                execution_time = (end_time - start_time).total_seconds()
                
                return CleanupResult(
                    entries_removed=entries_removed,
                    cleanup_type=f"size_limit_{max_entries}",
                    execution_time=execution_time,
                    errors=[]
                )
                
        except Exception as e:
            end_time = datetime.utcnow()
            execution_time = (end_time - start_time).total_seconds()
            
            return CleanupResult(
                entries_removed=0,
                cleanup_type=f"size_limit_{max_entries}",
                execution_time=execution_time,
                errors=[str(e)]
            )

    async def health_check(self) -> bool:
        """Check if database connection is healthy"""
        try:
            async with self.pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
                return True
        except Exception as e:
            print(f"OPAL Memory database health check failed: {e}", file=sys.stderr)
            return False


# Global database instance
_db_instance: Optional[OPALMemoryDB] = None


async def get_db() -> OPALMemoryDB:
    """Get or create the global database instance"""
    global _db_instance
    
    if _db_instance is None:
        _db_instance = OPALMemoryDB()
        await _db_instance.initialize()
    
    return _db_instance


async def close_db() -> None:
    """Close the global database instance"""
    global _db_instance
    
    if _db_instance is not None:
        await _db_instance.close()
        _db_instance = None
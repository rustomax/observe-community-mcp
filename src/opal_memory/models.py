"""
Pydantic models for the OPAL Memory System
"""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class SuccessfulQuery(BaseModel):
    """Model for a successful OPAL query pattern"""
    id: Optional[int] = None
    dataset_id: str = Field(..., description="The dataset ID this query was successful on")
    nlp_query_hash: str = Field(..., description="SHA256 hash of the normalized NLP query")
    nlp_query: str = Field(..., description="Original natural language query")
    opal_query: str = Field(..., description="Successful OPAL statement")
    execution_time: datetime = Field(default_factory=datetime.utcnow, description="When the query was executed")
    row_count: Optional[int] = Field(None, description="Number of rows returned")
    time_range: Optional[str] = Field(None, description="Time range used in the query")
    created_at: datetime = Field(default_factory=datetime.utcnow, description="When this record was created")
    semantic_embedding: Optional[str] = Field(None, description="Vector embedding for semantic similarity (pgvector format)")

    class Config:
        from_attributes = True


class QueryMatch(BaseModel):
    """Model for a query match result"""
    query: SuccessfulQuery
    similarity_score: float = Field(..., ge=0.0, le=1.0, description="Similarity score between 0 and 1")
    match_type: str = Field(..., description="Type of match: 'exact', 'fuzzy', or 'cross_dataset'")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence in this match")

    class Config:
        from_attributes = True


class MemoryStats(BaseModel):
    """Statistics about the memory system"""
    total_queries: int = Field(..., description="Total number of stored queries")
    unique_datasets: int = Field(..., description="Number of unique datasets")
    hit_rate: float = Field(..., ge=0.0, le=1.0, description="Cache hit rate")
    avg_similarity_threshold: float = Field(..., description="Average similarity threshold used")
    oldest_entry: Optional[datetime] = Field(None, description="Timestamp of oldest entry")
    newest_entry: Optional[datetime] = Field(None, description="Timestamp of newest entry")

    class Config:
        from_attributes = True


class CleanupResult(BaseModel):
    """Result of a cleanup operation"""
    entries_removed: int = Field(..., description="Number of entries removed")
    cleanup_type: str = Field(..., description="Type of cleanup performed")
    execution_time: float = Field(..., description="Time taken for cleanup in seconds")
    errors: list[str] = Field(default_factory=list, description="Any errors encountered")

    class Config:
        from_attributes = True
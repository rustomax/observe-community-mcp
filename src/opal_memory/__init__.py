"""
OPAL Memory System

This module provides memory functionality for successful OPAL queries to reduce
LLM API calls and improve response times for repeated patterns.
"""

from .database import OPALMemoryDB
from .models import SuccessfulQuery, QueryMatch
from .similarity import QueryMatcher
from .queries import store_successful_query, find_matching_queries
from .embeddings import get_embedding_generator, generate_query_embedding
from .semantic import create_semantic_matcher
from .domain import get_domain_mapper

__all__ = [
    'OPALMemoryDB',
    'SuccessfulQuery', 
    'QueryMatch',
    'QueryMatcher',
    'store_successful_query',
    'find_matching_queries',
    'get_embedding_generator',
    'generate_query_embedding',
    'create_semantic_matcher',
    'get_domain_mapper'
]
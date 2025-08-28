"""
Pinecone operations package

Centralized Pinecone functionality for vector search, indexing, and embedding operations.
Supports docs with consistent interfaces and error handling.
"""

from .client import initialize_pinecone
from .embeddings import get_embedding, get_embeddings_batch
from .search import semantic_search
from .indexing import index_documents

__all__ = [
    'initialize_pinecone',
    'get_embedding', 
    'get_embeddings_batch',
    'semantic_search',
    'index_documents'
]
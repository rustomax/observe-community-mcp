"""
PostgreSQL-based search operations

Provides BM25-based document search as an alternative to Pinecone vector search.
"""

from .doc_search import search_docs_bm25

__all__ = [
    'search_docs_bm25'
]
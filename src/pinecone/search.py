"""
Pinecone semantic search operations

Provides unified semantic search functionality for docs,
with consistent error handling and result formatting.
"""

import sys
from typing import List, Dict, Any, Optional
from .client import initialize_pinecone, PINECONE_API_KEY
from .embeddings import get_embedding


def semantic_search(query: str, n_results: int = 5, index_type: str = "docs", namespace: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Perform semantic search using Pinecone
    
    Args:
        query: Search query text
        n_results: Number of results to return (default: 5)
        index_type: Type of index to search ("docs")
        namespace: Optional namespace to search within
        
    Returns:
        List of search results with metadata
    """
    try:
        print(f"Searching {index_type} for: '{query}' with n_results={n_results}", file=sys.stderr)
        
        # Check if PINECONE_API_KEY is set
        if not PINECONE_API_KEY:
            print("WARNING: PINECONE_API_KEY is not set. Using fallback empty results.", file=sys.stderr)
            return [{
                "id": "error",
                "score": 1.0,
                "text": f"Error: PINECONE_API_KEY environment variable is not set. Please set it in your .env file. Your query was: {query}",
                "source": "error",
                "title": "Configuration Error"
            }]
        
        # Initialize Pinecone
        try:
            print(f"Initializing Pinecone for {index_type}...", file=sys.stderr)
            pc, index = initialize_pinecone(index_type=index_type)
            print("Pinecone initialized successfully", file=sys.stderr)
        except Exception as e:
            print(f"ERROR initializing Pinecone: {e}", file=sys.stderr)
            return [{
                "id": "error",
                "score": 1.0,
                "text": f"Error initializing Pinecone: {str(e)}. Your query was: {query}",
                "source": "error",
                "title": "Pinecone Error"
            }]
        
        # Generate embedding for the query
        try:
            print("Generating embedding for query...", file=sys.stderr)
            query_embedding = get_embedding(pc, query, is_query=True)
            print("Embedding generated successfully", file=sys.stderr)
        except Exception as e:
            print(f"ERROR generating embedding: {e}", file=sys.stderr)
            return [{
                "id": "error",
                "score": 1.0,
                "text": f"Error generating embedding: {str(e)}. Your query was: {query}",
                "source": "error",
                "title": "Embedding Error"
            }]
        
        # Query Pinecone with the embedding
        try:
            print("Querying Pinecone...", file=sys.stderr)
            query_params = {
                "vector": query_embedding,
                "top_k": n_results,
                "include_metadata": True
            }
            if namespace:
                query_params["namespace"] = namespace
                
            results = index.query(**query_params)
            print(f"Query successful. Found {len(results.get('matches', []))} results", file=sys.stderr)
        except Exception as e:
            print(f"ERROR querying Pinecone: {e}", file=sys.stderr)
            return [{
                "id": "error",
                "score": 1.0,
                "text": f"Error querying Pinecone: {str(e)}. Your query was: {query}",
                "source": "error",
                "title": "Query Error"
            }]
        
        # Format results
        formatted_results = []
        for match in results.get("matches", []):
            metadata = match.get("metadata", {})
            
            # Get text content
            text_content = metadata.get("text", "")
            
            formatted_results.append({
                "id": match.get("id", "unknown"),
                "score": match.get("score", 0.0),
                "text": text_content,
                "source": metadata.get("source", ""),
                "title": metadata.get("title", "")
            })
        
        return formatted_results
        
    except Exception as e:
        print(f"ERROR in semantic search: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        return [{
            "id": "error",
            "score": 1.0,
            "text": f"Unexpected error in semantic search: {str(e)}. Your query was: {query}",
            "source": "error",
            "title": "Search Error"
        }]




def search_docs(query: str, n_results: int = 5) -> List[Dict[str, Any]]:
    """
    Convenience function for searching docs specifically
    
    Args:
        query: Search query text
        n_results: Number of results to return (default: 5)
        
    Returns:
        List of docs search results with metadata
    """
    return semantic_search(query, n_results=n_results, index_type="docs")
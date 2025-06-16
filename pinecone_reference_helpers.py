import os
import sys
from typing import List, Dict, Any, Optional
from pinecone import Pinecone
from dotenv import load_dotenv
import time
from tqdm import tqdm

# Load environment variables
load_dotenv()

# Configuration
PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
INDEX_NAME = os.getenv("PINECONE_DOCS_INDEX", "observe-docs")
EMBEDDING_MODEL = "llama-text-embed-v2"  # Pinecone's integrated embedding model

def initialize_pinecone(index_name=None):
    """Initialize Pinecone client and ensure index exists
    
    Args:
        index_name: Optional name of the index to use. If not provided, uses INDEX_NAME from config
    
    Returns:
        Tuple of (Pinecone client, Pinecone index)
    """
    try:
        # Use provided index_name or default to INDEX_NAME
        target_index = index_name if index_name else INDEX_NAME
        
        if not PINECONE_API_KEY:
            print("ERROR: PINECONE_API_KEY environment variable is not set", file=sys.stderr)
            raise ValueError("PINECONE_API_KEY environment variable is not set")
        
        print(f"Initializing Pinecone client", file=sys.stderr)
        pc = Pinecone(api_key=PINECONE_API_KEY)
        
        # Check if index exists, create if it doesn't
        try:
            has_index = pc.has_index(target_index)
            print(f"Checking for index {target_index}: {'exists' if has_index else 'does not exist'}", file=sys.stderr)
        except Exception as e:
            print(f"Error checking if index exists: {e}", file=sys.stderr)
            raise
            
        if not has_index:
            print(f"Creating new Pinecone index with integrated embedding model: {target_index}", file=sys.stderr)
            try:
                pc.create_index_for_model(
                    name=target_index,
                    cloud="aws",
                    region="us-east-1",
                    embed={
                        "model": EMBEDDING_MODEL,
                        "field_map": {"text": "text"}
                    }
                )
                # Wait for index to be ready
                print("Waiting for index to be ready...", file=sys.stderr)
                time.sleep(10)
            except Exception as e:
                print(f"Error creating index: {e}", file=sys.stderr)
                raise
        
        # Get the index
        try:
            print(f"Getting index {target_index}...", file=sys.stderr)
            index = pc.Index(target_index)
            print(f"Connected to Pinecone index: {target_index}", file=sys.stderr)
            return pc, index
        except Exception as e:
            print(f"Error getting index: {e}", file=sys.stderr)
            raise
    except Exception as e:
        print(f"ERROR in initialize_pinecone: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        raise

def get_embedding(pc, text: str, is_query: bool = False) -> List[float]:
    """Get embedding for a single text using Pinecone's inference API
    
    Args:
        pc: Pinecone client instance
        text: Text to get embedding for
        is_query: Whether this is a query (True) or document (False)
        
    Returns:
        List of embedding values
    """
    try:
        # Use Pinecone's inference API to generate embedding
        # Use 'query' input_type for queries and 'passage' for documents
        input_type = "query" if is_query else "passage"
        
        embeddings = pc.inference.embed(
            model=EMBEDDING_MODEL,
            inputs=[text],
            parameters={
                "input_type": input_type
            }
        )
        
        # Return the values from the first (and only) embedding
        if embeddings and len(embeddings) > 0:
            return embeddings[0]["values"]
        else:
            print("Warning: No embeddings returned from Pinecone", file=sys.stderr)
            return [0.0]
    except Exception as e:
        print(f"Error getting embedding: {e}", file=sys.stderr)
        # Return empty embedding as a fallback
        return [0.0]

def semantic_search(query: str, n_results: int = 5) -> List[Dict[str, Any]]:
    """Perform semantic search using Pinecone"""
    try:
        print(f"Searching for: '{query}' with n_results={n_results}", file=sys.stderr)
        
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
            print("Initializing Pinecone...", file=sys.stderr)
            pc, index = initialize_pinecone()
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
            results = index.query(
                vector=query_embedding,
                top_k=n_results,
                include_metadata=True
            )
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
            formatted_results.append({
                "id": match.get("id", "unknown"),
                "score": match.get("score", 0.0),
                "text": match.get("metadata", {}).get("text", ""),
                "source": match.get("metadata", {}).get("source", ""),
                "title": match.get("metadata", {}).get("title", "")
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

def list_all_entities() -> List[Dict[str, Any]]:
    """List all documents in the Pinecone index"""
    try:
        pc, index = initialize_pinecone()
        stats = index.describe_stats()
        vector_count = stats.get("total_vector_count", 0)
        print(f"Index contains {vector_count} vectors")
        
        # Pinecone doesn't have a direct way to list all vectors
        # This is a placeholder - in a real implementation you might
        # need to maintain a separate metadata store
        return [{"count": vector_count}]
    except Exception as e:
        print(f"Error listing entities: {e}")
        return []

def get_document_by_id(doc_id: str) -> Optional[Dict[str, Any]]:
    """Get a specific document by ID"""
    try:
        _, index = initialize_pinecone()  # Fix: initialize_pinecone returns a tuple (pc, index)
        result = index.fetch(ids=[doc_id])
        
        if doc_id in result["vectors"]:
            vector_data = result["vectors"][doc_id]
            return {
                "id": doc_id,
                "text": vector_data["metadata"].get("text", ""),
                "source": vector_data["metadata"].get("source", ""),
                "title": vector_data["metadata"].get("title", "")
            }
        return None
    except Exception as e:
        print(f"Error getting document by ID: {e}")
        import traceback
        traceback.print_exc()
        return None

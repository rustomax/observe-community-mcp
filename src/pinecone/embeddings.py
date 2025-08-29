"""
Pinecone embedding generation

Provides unified embedding generation for both single texts and batches,
with consistent error handling and support for query vs document embedding types.
"""

import sys
from typing import List
from pinecone import Pinecone
from .client import get_embedding_model
from src.logging import get_logger

logger = get_logger('PINECONE_EMBED')


def get_embedding(pc: Pinecone, text: str, is_query: bool = False) -> List[float]:
    """
    Get embedding for a single text using Pinecone's inference API
    
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
            model=get_embedding_model(),
            inputs=[text],
            parameters={
                "input_type": input_type
            }
        )
        
        # Return the values from the first (and only) embedding
        if embeddings and len(embeddings) > 0:
            return embeddings[0]["values"]
        else:
            logger.warning("no embeddings returned from Pinecone")
            return [0.0]
            
    except Exception as e:
        logger.error(f"error getting embedding | error:{e}")
        # Return empty embedding as a fallback
        return [0.0]


def get_embeddings_batch(pc: Pinecone, texts: List[str], batch_size: int = 10, is_query: bool = False) -> List[List[float]]:
    """
    Get embeddings for a list of texts in batches
    
    Args:
        pc: Pinecone client instance
        texts: List of texts to get embeddings for
        batch_size: Number of texts to process in each batch (default: 10)
        is_query: Whether these are queries (True) or documents (False)
        
    Returns:
        List of embedding vectors, one for each input text
    """
    all_embeddings = []
    
    # Use 'query' input_type for queries and 'passage' for documents
    input_type = "query" if is_query else "passage"
    
    # Process in smaller batches to avoid API limits
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i+batch_size]
        logger.debug(f"generating embeddings | batch:{i//batch_size + 1}/{(len(texts)-1)//batch_size + 1} | texts:{len(batch)}")
        
        try:
            # Generate embeddings for the batch
            batch_embeddings = pc.inference.embed(
                model=get_embedding_model(),
                inputs=batch,
                parameters={
                    "input_type": input_type
                }
            )
            
            # Extract the values from each embedding
            for embedding in batch_embeddings:
                all_embeddings.append(embedding["values"])
                
        except Exception as e:
            logger.error(f"error in batch embedding | error:{e}")
            # Fall back to individual embeddings on batch failure
            for text in batch:
                try:
                    embedding = get_embedding(pc, text, is_query=is_query)
                    all_embeddings.append(embedding)
                except Exception as e2:
                    logger.error(f"error in individual embedding | error:{e2}")
                    all_embeddings.append([0.0])  # Add dummy embedding on failure
    
    return all_embeddings
"""
Pinecone client initialization and connection management

Provides centralized Pinecone client setup with consistent error handling
and support for different indexes (docs, custom).
"""

import os
import sys
import time
from typing import Tuple, Optional
from pinecone import Pinecone
from dotenv import load_dotenv
from src.logging import get_logger

logger = get_logger('PINECONE')

# Load environment variables
load_dotenv()

# Configuration
PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
EMBEDDING_MODEL = "llama-text-embed-v2"  # Pinecone's integrated embedding model

# Index configurations
INDEX_CONFIGS = {
    "docs": {
        "index_name": os.getenv("PINECONE_DOCS_INDEX", "observe-docs"),
        "field_map": {"text": "text"}
    }
}


def initialize_pinecone(index_type: str = "docs", index_name: Optional[str] = None) -> Tuple[Pinecone, any]:
    """
    Initialize Pinecone client and ensure index exists
    
    Args:
        index_type: Type of index ("docs") for configuration lookup
        index_name: Optional explicit index name. If not provided, uses config for index_type
    
    Returns:
        Tuple of (Pinecone client, Pinecone index)
    
    Raises:
        ValueError: If PINECONE_API_KEY is not set or index_type is invalid
        Exception: If index creation or connection fails
    """
    try:
        # Validate index type
        if index_type not in INDEX_CONFIGS and index_name is None:
            raise ValueError(f"Invalid index_type '{index_type}'. Must be one of: {list(INDEX_CONFIGS.keys())}")
        
        # Determine target index and field mapping
        if index_name:
            target_index = index_name
            # Use docs field mapping as default for custom index names
            field_map = INDEX_CONFIGS["docs"]["field_map"]
        else:
            config = INDEX_CONFIGS[index_type]
            target_index = config["index_name"]
            field_map = config["field_map"]
        
        if not PINECONE_API_KEY:
            logger.error("PINECONE_API_KEY environment variable is not set")
            raise ValueError("PINECONE_API_KEY environment variable is not set")
        
        logger.debug(f"initializing Pinecone client | index_type:{index_type} | target_index:{target_index}")
        pc = Pinecone(api_key=PINECONE_API_KEY)
        
        # Check if index exists, create if it doesn't
        try:
            has_index = pc.has_index(target_index)
            logger.debug(f"checking for index | index:{target_index} | exists:{has_index}")
        except Exception as e:
            logger.error(f"error checking if index exists | error:{e}")
            raise
            
        if not has_index:
            logger.info(f"creating new Pinecone index | index:{target_index} | model:integrated_embedding")
            try:
                pc.create_index_for_model(
                    name=target_index,
                    cloud="aws",
                    region="us-east-1",
                    embed={
                        "model": EMBEDDING_MODEL,
                        "field_map": field_map
                    }
                )
                # Wait for index to be ready
                logger.debug("waiting for index to be ready")
                time.sleep(10)
            except Exception as e:
                logger.error(f"error creating index | error:{e}")
                raise
        
        # Get the index
        try:
            logger.debug(f"getting index | index:{target_index}")
            index = pc.Index(target_index)
            logger.info(f"connected to Pinecone index | index:{target_index}")
            return pc, index
        except Exception as e:
            logger.error(f"error getting index | error:{e}")
            raise
            
    except Exception as e:
        logger.error(f"error in initialize_pinecone | error:{e}")
        import traceback
        traceback.print_exc(file=sys.stderr)
        raise


def get_index_config(index_type: str) -> dict:
    """
    Get configuration for a specific index type
    
    Args:
        index_type: Type of index ("docs")
        
    Returns:
        Dictionary with index configuration
        
    Raises:
        ValueError: If index_type is invalid
    """
    if index_type not in INDEX_CONFIGS:
        raise ValueError(f"Invalid index_type '{index_type}'. Must be one of: {list(INDEX_CONFIGS.keys())}")
    
    return INDEX_CONFIGS[index_type].copy()


def get_embedding_model() -> str:
    """Get the configured embedding model name"""
    return EMBEDDING_MODEL
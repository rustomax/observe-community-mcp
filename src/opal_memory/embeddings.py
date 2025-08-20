"""
Semantic embeddings for OPAL query similarity matching using OpenAI API
"""

import os
import sys
from typing import List, Optional
import asyncio

try:
    from openai import AsyncOpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False
    print("Warning: openai not available, semantic search disabled", file=sys.stderr)


class EmbeddingGenerator:
    """Handles generation of semantic embeddings for queries using OpenAI API"""
    
    def __init__(self, model_name: str = "text-embedding-3-small"):
        self.model_name = model_name
        self.embedding_dimension = 1536  # text-embedding-3-small dimension
        self.is_available = OPENAI_AVAILABLE and bool(os.getenv("OPENAI_API_KEY"))
        self.client = None
        
        if self.is_available:
            try:
                self.client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
                print(f"Initialized OpenAI embeddings: {model_name} (dimension: {self.embedding_dimension})", file=sys.stderr)
            except Exception as e:
                print(f"Failed to initialize OpenAI client: {e}", file=sys.stderr)
                self.is_available = False
        else:
            print(f"OpenAI API not available - embeddings disabled (missing OPENAI_API_KEY)", file=sys.stderr)

    async def _generate_embedding_async(self, text: str) -> Optional[List[float]]:
        """Generate embedding using OpenAI API"""
        try:
            if not self.client:
                return None
                
            # Clean and truncate text for embedding
            clean_text = self._normalize_text(text)
            if len(clean_text) > 8000:  # OpenAI limit is ~8191 tokens
                clean_text = clean_text[:8000]
            
            response = await self.client.embeddings.create(
                input=clean_text,
                model=self.model_name
            )
            
            embedding = response.data[0].embedding
            print(f"Generated {len(embedding)}d embedding for query: {text[:50]}...", file=sys.stderr)
            return embedding
            
        except Exception as e:
            print(f"Error generating OpenAI embedding: {e}", file=sys.stderr)
            return None

    def generate_embedding(self, text: str) -> Optional[List[float]]:
        """Generate embedding for a single text (sync wrapper)"""
        if not self.is_available:
            return None
            
        try:
            # Run async function in event loop
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # If we're already in an async context, this won't work
                # Return None and caller should use async version
                print("Warning: sync embedding called from async context, use generate_embedding_async", file=sys.stderr)
                return None
            else:
                return loop.run_until_complete(self._generate_embedding_async(text))
        except Exception as e:
            print(f"Error in sync embedding generation: {e}", file=sys.stderr)
            return None
    
    async def generate_embedding_async(self, text: str) -> Optional[List[float]]:
        """Generate embedding for a single text (async)"""
        return await self._generate_embedding_async(text)

    def calculate_similarity(self, embedding1: List[float], embedding2: List[float]) -> float:
        """Calculate cosine similarity between two embeddings"""
        try:
            # Simple dot product calculation (OpenAI embeddings are normalized)
            if len(embedding1) != len(embedding2):
                return 0.0
            
            # Calculate dot product for normalized vectors (cosine similarity)
            dot_product = sum(a * b for a, b in zip(embedding1, embedding2))
            return float(max(-1.0, min(1.0, dot_product)))  # Clamp to [-1, 1]
            
        except Exception as e:
            print(f"Error calculating similarity: {e}", file=sys.stderr)
            return 0.0

    def embedding_to_pgvector(self, embedding: List[float]) -> str:
        """Convert embedding list to pgvector format string"""
        try:
            # Format as PostgreSQL vector: [1.0,2.0,3.0]
            vector_str = "[" + ",".join(f"{x:.8f}" for x in embedding) + "]"
            return vector_str
        except Exception as e:
            print(f"Error converting to pgvector format: {e}", file=sys.stderr)
            return "[]"

    def pgvector_to_embedding(self, pgvector_str: str) -> Optional[List[float]]:
        """Convert PostgreSQL vector string back to embedding list"""
        try:
            # Remove brackets and split
            clean_str = pgvector_str.strip('[]')
            values = clean_str.split(',')
            return [float(x.strip()) for x in values]
        except Exception as e:
            print(f"Error parsing pgvector string: {e}", file=sys.stderr)
            return None
    
    def _normalize_text(self, text: str) -> str:
        """
        Normalize text for consistent embedding generation.
        Apply domain-specific preprocessing for observability queries.
        """
        # Basic normalization
        normalized = text.lower().strip()
        
        # Remove extra whitespace
        import re
        normalized = re.sub(r'\s+', ' ', normalized)
        
        # Apply domain-specific concept mapping for better semantic matching
        domain_mappings = {
            # Error concepts
            r'\b(errors?|failures?|issues?|problems?)\b': 'errors',
            r'\b(failed|failing|broken)\b': 'failed', 
            
            # Performance concepts
            r'\b(latency|response\s*time|performance)\b': 'latency',
            r'\b(throughput|requests?\s*per\s*second|rps)\b': 'throughput',
            
            # Aggregation concepts  
            r'\b(count|total|number\s*of|how\s*many)\b': 'count',
            r'\b(average|avg|mean)\b': 'average',
            r'\b(sum|total)\b': 'sum',
            
            # Time concepts
            r'\b(last|past|recent|latest)\b': 'recent',
            r'\b(hour|hr|h)\b': 'hour',
            r'\b(minute|min|m)\b': 'minute',
            r'\b(day|d)\b': 'day',
            
            # Action concepts
            r'\b(show|display|get|find|list)\b': 'show',
            r'\b(group\s*by|by)\b': 'group_by',
            r'\b(filter|where)\b': 'filter',
            
            # Service concepts
            r'\b(service|microservice|component)\b': 'service',
            r'\b(endpoint|api|route)\b': 'endpoint',
            r'\b(host|server|instance)\b': 'host'
        }
        
        # Apply mappings
        for pattern, replacement in domain_mappings.items():
            normalized = re.sub(pattern, replacement, normalized)
        
        return normalized.strip()


# Global instance
_embedding_generator = None

def get_embedding_generator() -> EmbeddingGenerator:
    """Get the global embedding generator instance"""
    global _embedding_generator
    if _embedding_generator is None:
        model_name = os.getenv("OPAL_MEMORY_EMBEDDING_MODEL", "text-embedding-3-small")
        _embedding_generator = EmbeddingGenerator(model_name)
    return _embedding_generator

async def generate_query_embedding(query: str) -> Optional[List[float]]:
    """Generate embedding for a query string (async)"""
    generator = get_embedding_generator()
    if not generator.is_available:
        return None
    
    return await generator.generate_embedding_async(query)

async def calculate_semantic_similarity(query1: str, query2: str) -> Optional[float]:
    """
    Calculate semantic similarity between two queries using OpenAI embeddings.
    Returns None if embeddings are not available.
    """
    generator = get_embedding_generator()
    
    if not generator.is_available:
        return None
    
    embedding1 = await generator.generate_embedding_async(query1)
    embedding2 = await generator.generate_embedding_async(query2)
    
    if embedding1 is None or embedding2 is None:
        return None
        
    return generator.calculate_similarity(embedding1, embedding2)
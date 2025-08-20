"""
Semantic similarity calculations and hybrid scoring for OPAL memory system
"""

import sys
from typing import List, Optional, Tuple
from .models import SuccessfulQuery, QueryMatch
from .embeddings import get_embedding_generator, generate_query_embedding
from .similarity import QueryMatcher


class SemanticQueryMatcher:
    """Enhanced query matcher with semantic similarity capabilities"""
    
    def __init__(self, 
                 semantic_weight: float = 0.6,
                 string_weight: float = 0.4,
                 similarity_threshold: float = 0.75):
        self.semantic_weight = semantic_weight
        self.string_weight = string_weight  
        self.similarity_threshold = similarity_threshold
        
        # Initialize components
        self.string_matcher = QueryMatcher(similarity_threshold)
        self.embedding_generator = get_embedding_generator()
        
        # Log availability
        if self.embedding_generator.is_available:
            print(f"Semantic matching enabled with {self.embedding_generator.embedding_dimension}d embeddings", file=sys.stderr)
        else:
            print("Semantic matching disabled - falling back to string similarity only", file=sys.stderr)
    
    @property
    def is_semantic_available(self) -> bool:
        """Check if semantic similarity is available"""
        return self.embedding_generator.is_available
    
    def find_semantic_matches(
        self,
        target_query: str,
        candidate_queries: List[SuccessfulQuery],
        max_matches: int = 5
    ) -> List[QueryMatch]:
        """
        Find matches using semantic similarity with hybrid scoring.
        
        Uses both semantic and string similarity with weighted combination.
        Falls back to string-only matching if embeddings unavailable.
        """
        if not candidate_queries:
            return []
        
        # Generate embedding for target query
        target_embedding = None
        if self.is_semantic_available:
            target_embedding = self.embedding_generator.generate_embedding(target_query)
            
        matches = []
        
        for candidate in candidate_queries:
            # Calculate individual similarity scores
            semantic_score = 0.0
            string_score = self.string_matcher.calculate_similarity(target_query, candidate.nlp_query)
            
            # Calculate semantic similarity if available
            if target_embedding and candidate.semantic_embedding:
                try:
                    # Convert stored embedding back to list if needed
                    candidate_embedding = candidate.semantic_embedding
                    if isinstance(candidate_embedding, str):
                        candidate_embedding = self.embedding_generator.pgvector_to_embedding(candidate_embedding)
                    
                    if candidate_embedding:
                        semantic_score = self.embedding_generator.calculate_similarity(
                            target_embedding, candidate_embedding
                        )
                        # Convert from [-1,1] to [0,1] range
                        semantic_score = (semantic_score + 1.0) / 2.0
                        
                except Exception as e:
                    print(f"Error calculating semantic similarity: {e}", file=sys.stderr)
                    semantic_score = 0.0
            
            # Calculate hybrid score
            if self.is_semantic_available and semantic_score > 0:
                # Use weighted combination
                hybrid_score = (
                    self.semantic_weight * semantic_score + 
                    self.string_weight * string_score
                )
                match_type = 'semantic'
            else:
                # Fall back to string similarity only
                hybrid_score = string_score
                match_type = 'fuzzy'
            
            # Apply threshold filter
            if hybrid_score >= self.similarity_threshold:
                # Calculate confidence with additional factors
                confidence = self._calculate_confidence(
                    hybrid_score, semantic_score, string_score, candidate, target_query
                )
                
                match = QueryMatch(
                    query=candidate,
                    similarity_score=hybrid_score,
                    match_type=match_type,
                    confidence=confidence
                )
                matches.append(match)
        
        # Sort by similarity score descending
        matches.sort(key=lambda x: x.similarity_score, reverse=True)
        
        # Log matching results
        if matches:
            best = matches[0]
            print(f"[SEMANTIC] Found {len(matches)} matches, best: {best.match_type} "
                  f"(similarity: {best.similarity_score:.2f}, confidence: {best.confidence:.2f})", 
                  file=sys.stderr)
        
        return matches[:max_matches]
    
    def find_cross_dataset_semantic_matches(
        self,
        target_query: str,
        candidate_queries: List[SuccessfulQuery],
        min_similarity: float = 0.80,  # Higher threshold for cross-dataset
        max_matches: int = 3
    ) -> List[QueryMatch]:
        """
        Find cross-dataset matches with higher semantic similarity requirements.
        """
        # Temporarily increase threshold for cross-dataset matching
        original_threshold = self.similarity_threshold
        self.similarity_threshold = min_similarity
        
        try:
            matches = self.find_semantic_matches(target_query, candidate_queries, max_matches)
            
            # Mark as cross-dataset and reduce confidence
            for match in matches:
                match.match_type = 'cross_dataset_semantic'
                match.confidence *= 0.8  # Reduce confidence for cross-dataset
            
            return matches
            
        finally:
            # Restore original threshold
            self.similarity_threshold = original_threshold
    
    def _calculate_confidence(
        self, 
        hybrid_score: float, 
        semantic_score: float, 
        string_score: float, 
        candidate: SuccessfulQuery,
        target_query: str = None
    ) -> float:
        """
        Calculate confidence score based on multiple factors including time context.
        """
        # Start with hybrid similarity score
        confidence = hybrid_score
        
        # Boost confidence for high semantic similarity
        if semantic_score > 0.8:
            confidence *= 1.1
        elif semantic_score > 0.9:
            confidence *= 1.15
        
        # Boost confidence when both semantic and string scores are high
        if semantic_score > 0.7 and string_score > 0.7:
            confidence *= 1.05
        
        # Apply time-aware similarity boost
        if target_query:
            try:
                from .domain import get_domain_mapper
                domain_mapper = get_domain_mapper()
                time_similarity = domain_mapper.calculate_time_aware_similarity(
                    target_query, candidate.nlp_query
                )
                
                # Boost confidence for high time-aware similarity
                if time_similarity > 0.8:
                    confidence *= 1.1
                    print(f"[TIME_AWARE] High time similarity boost: {time_similarity:.2f}", file=sys.stderr)
                elif time_similarity < 0.4:
                    confidence *= 0.9  # Reduce confidence for poor time compatibility
                    print(f"[TIME_AWARE] Low time similarity penalty: {time_similarity:.2f}", file=sys.stderr)
                    
            except Exception as e:
                print(f"[TIME_AWARE] Error calculating time-aware similarity: {e}", file=sys.stderr)
        
        # Apply recency factor
        from datetime import datetime, timedelta
        age_days = (datetime.utcnow() - candidate.created_at).days
        if age_days <= 7:
            confidence *= 1.05  # Recent queries get boost
        elif age_days <= 30:
            confidence *= 1.02
        elif age_days > 90:
            confidence *= 0.95  # Very old queries get penalty
        
        # Apply result quality factor
        if candidate.row_count is not None:
            if 10 <= candidate.row_count <= 10000:
                confidence *= 1.02  # Good result size
            elif candidate.row_count == 0:
                confidence *= 0.95  # No results - slightly lower confidence
            elif candidate.row_count > 50000:
                confidence *= 0.98  # Very large results - might be too broad
        
        # Ensure confidence stays within bounds
        return max(0.0, min(1.0, confidence))
    
    def get_matching_stats(self) -> dict:
        """Get statistics about the matching system"""
        return {
            "semantic_available": self.is_semantic_available,
            "embedding_model": self.embedding_generator.model_name if self.is_semantic_available else None,
            "embedding_dimension": self.embedding_generator.embedding_dimension if self.is_semantic_available else 0,
            "semantic_weight": self.semantic_weight,
            "string_weight": self.string_weight,
            "similarity_threshold": self.similarity_threshold
        }


def create_semantic_matcher() -> SemanticQueryMatcher:
    """Create a semantic query matcher with default settings"""
    import os
    
    # Get configuration from environment
    semantic_weight = float(os.getenv("OPAL_MEMORY_SEMANTIC_WEIGHT", "0.6"))
    string_weight = float(os.getenv("OPAL_MEMORY_STRING_WEIGHT", "0.4"))
    threshold = float(os.getenv("OPAL_MEMORY_SIMILARITY_THRESHOLD", "0.75"))
    
    return SemanticQueryMatcher(
        semantic_weight=semantic_weight,
        string_weight=string_weight, 
        similarity_threshold=threshold
    )
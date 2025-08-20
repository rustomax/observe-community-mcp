"""
Query similarity matching algorithms for the OPAL Memory System
"""

import hashlib
import re
from typing import List, Optional, Tuple
from difflib import SequenceMatcher

from .models import SuccessfulQuery, QueryMatch


class QueryMatcher:
    """Handles matching of natural language queries to stored patterns"""
    
    def __init__(self, similarity_threshold: float = 0.85):
        self.similarity_threshold = similarity_threshold
    
    @staticmethod
    def normalize_query(query: str) -> str:
        """
        Normalize a natural language query for better matching.
        Removes extra whitespace, converts to lowercase, standardizes common terms.
        """
        # Convert to lowercase
        normalized = query.lower().strip()
        
        # Remove extra whitespace
        normalized = re.sub(r'\s+', ' ', normalized)
        
        # Standardize common terms
        replacements = {
            r'\berror rates?\b': 'errors',
            r'\blatency\b': 'latency',
            r'\bresponse times?\b': 'latency', 
            r'\bin the (last|past) (\d+) (hour|hours|h)\b': r'last \2h',
            r'\bin the (last|past) (\d+) (minute|minutes|m)\b': r'last \2m',
            r'\bin the (last|past) (\d+) (day|days|d)\b': r'last \2d',
            r'\bshow me\b': 'show',
            r'\bfind\b': 'show',
            r'\bget\b': 'show',
            r'\bhow many\b': 'count',
            r'\blist\b': 'show',
            r'\bdisplay\b': 'show'
        }
        
        for pattern, replacement in replacements.items():
            normalized = re.sub(pattern, replacement, normalized)
        
        return normalized.strip()
    
    @staticmethod
    def hash_query(query: str) -> str:
        """Generate SHA256 hash of normalized query for exact matching"""
        normalized = QueryMatcher.normalize_query(query)
        return hashlib.sha256(normalized.encode('utf-8')).hexdigest()
    
    def calculate_similarity(self, query1: str, query2: str) -> float:
        """
        Calculate similarity score between two queries using SequenceMatcher.
        Returns a score between 0.0 and 1.0.
        """
        norm1 = self.normalize_query(query1)
        norm2 = self.normalize_query(query2)
        
        return SequenceMatcher(None, norm1, norm2).ratio()
    
    def find_fuzzy_matches(
        self, 
        target_query: str, 
        candidate_queries: List[SuccessfulQuery]
    ) -> List[QueryMatch]:
        """
        Find fuzzy matches for a target query from a list of candidates.
        Returns matches above the similarity threshold, sorted by similarity score.
        """
        matches = []
        
        for candidate in candidate_queries:
            similarity = self.calculate_similarity(target_query, candidate.nlp_query)
            
            if similarity >= self.similarity_threshold:
                # Calculate confidence based on similarity and recency
                confidence = self._calculate_confidence(similarity, candidate)
                
                match = QueryMatch(
                    query=candidate,
                    similarity_score=similarity,
                    match_type='fuzzy',
                    confidence=confidence
                )
                matches.append(match)
        
        # Sort by similarity score (descending)
        matches.sort(key=lambda x: x.similarity_score, reverse=True)
        return matches
    
    def find_cross_dataset_matches(
        self,
        target_query: str,
        candidate_queries: List[SuccessfulQuery],
        min_similarity: float = 0.9  # Higher threshold for cross-dataset
    ) -> List[QueryMatch]:
        """
        Find cross-dataset matches with higher similarity requirements.
        These are patterns from other datasets that might be applicable.
        """
        matches = []
        
        for candidate in candidate_queries:
            similarity = self.calculate_similarity(target_query, candidate.nlp_query)
            
            if similarity >= min_similarity:
                # Lower confidence for cross-dataset matches
                confidence = self._calculate_confidence(similarity, candidate) * 0.8
                
                match = QueryMatch(
                    query=candidate,
                    similarity_score=similarity,
                    match_type='cross_dataset',
                    confidence=confidence
                )
                matches.append(match)
        
        matches.sort(key=lambda x: x.similarity_score, reverse=True)
        return matches
    
    def _calculate_confidence(self, similarity: float, query: SuccessfulQuery) -> float:
        """
        Calculate confidence score based on similarity and other factors.
        Factors in recency, success rate, and query complexity.
        """
        # Base confidence from similarity
        confidence = similarity
        
        # Recency factor (newer queries get slight boost)
        from datetime import datetime, timedelta
        age_days = (datetime.utcnow() - query.created_at).days
        if age_days <= 7:
            confidence *= 1.05  # 5% boost for recent queries
        elif age_days <= 30:
            confidence *= 1.02  # 2% boost for month-old queries
        elif age_days > 90:
            confidence *= 0.95  # 5% penalty for very old queries
        
        # Row count factor (queries that returned reasonable data get boost)
        if query.row_count is not None:
            if 10 <= query.row_count <= 10000:
                confidence *= 1.02  # Reasonable result size
            elif query.row_count == 0:
                confidence *= 0.9   # No results - less confident
            elif query.row_count > 50000:
                confidence *= 0.95  # Very large results - might be too broad
        
        # Ensure confidence stays within bounds
        return max(0.0, min(1.0, confidence))
    
    def extract_key_terms(self, query: str) -> List[str]:
        """
        Extract key terms from a query for advanced matching.
        Used for semantic similarity beyond string matching.
        """
        normalized = self.normalize_query(query)
        
        # Remove common stop words
        stop_words = {
            'show', 'get', 'find', 'the', 'in', 'of', 'for', 'by', 'with',
            'and', 'or', 'from', 'to', 'a', 'an', 'is', 'are', 'was', 'were'
        }
        
        # Extract potential key terms
        words = re.findall(r'\b\w+\b', normalized)
        key_terms = [word for word in words if word not in stop_words and len(word) > 2]
        
        return key_terms
    
    def calculate_semantic_similarity(self, query1: str, query2: str) -> float:
        """
        Calculate semantic similarity based on key terms overlap.
        This is a simple implementation - could be enhanced with embeddings.
        """
        terms1 = set(self.extract_key_terms(query1))
        terms2 = set(self.extract_key_terms(query2))
        
        if not terms1 or not terms2:
            return 0.0
        
        # Jaccard similarity
        intersection = terms1.intersection(terms2)
        union = terms1.union(terms2)
        
        return len(intersection) / len(union) if union else 0.0
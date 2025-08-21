"""
Dataset Intelligence module for semantic dataset discovery.

This module provides functions to query the dataset intelligence database
to find the most relevant datasets for natural language queries.
"""

from .search import find_relevant_datasets, find_datasets_by_keywords
from .intent_classification import IntentClassifier, DatasetScorer

__all__ = [
    "find_relevant_datasets",
    "find_datasets_by_keywords", 
    "IntentClassifier",
    "DatasetScorer"
]
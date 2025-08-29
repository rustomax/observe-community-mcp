"""
OPAL Visualization Module

Provides chart generation capabilities for OPAL query results, converting CSV data
into base64-encoded images optimized for observability dashboards.
"""

from .chart_generator import ChartGenerator
from .data_parser import DataParser
from .themes import OBSERVABILITY_THEME, CLEAN_THEME
from .auto_detection import detect_chart_type, detect_columns
from .utils import encode_image, validate_csv

__all__ = [
    'ChartGenerator',
    'DataParser', 
    'OBSERVABILITY_THEME',
    'CLEAN_THEME',
    'detect_chart_type',
    'detect_columns',
    'encode_image',
    'validate_csv'
]
"""
CSV data parsing and type detection for OPAL query results.
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Tuple, Optional
from datetime import datetime
import re


class DataParser:
    """Handles CSV parsing and data type detection for visualization."""
    
    # Observability column patterns
    TIME_PATTERNS = [
        'timestamp', 'start_time', 'end_time', '_time', 'datetime',
        'created_at', 'updated_at', 'event_time', 'log_time'
    ]
    
    COUNT_PATTERNS = [
        'count', '_count', 'total', '_total', 'num_', 'number_',
        'requests', 'hits', 'events', 'occurrences'
    ]
    
    DURATION_PATTERNS = [
        'duration', '_duration', 'latency', '_latency', '_ms', '_ns',
        'response_time', 'execution_time', 'processing_time'
    ]
    
    RATE_PATTERNS = [
        'rate', '_rate', 'percent', '_percent', 'ratio', '_ratio',
        'throughput', 'qps', 'rps', 'tps'
    ]
    
    ERROR_PATTERNS = [
        'error', '_error', 'fail', '_fail', 'exception', 'fault',
        'error_rate', 'failure_rate', 'exception_count'
    ]
    
    SERVICE_PATTERNS = [
        'service_name', 'service', 'app', 'application', 'component',
        'microservice', 'pod', 'container', 'host'
    ]
    
    ENDPOINT_PATTERNS = [
        'span_name', 'endpoint', 'method', 'operation', 'function',
        'api', 'route', 'path', 'url'
    ]
    
    def __init__(self):
        self.df: Optional[pd.DataFrame] = None
        self.column_types: Dict[str, str] = {}
        self.column_patterns: Dict[str, str] = {}
    
    def parse(self, csv_data: str) -> pd.DataFrame:
        """
        Parse CSV data and detect column types.
        
        Args:
            csv_data: Raw CSV string
            
        Returns:
            Parsed pandas DataFrame
            
        Raises:
            ValueError: If CSV is invalid
        """
        # Basic validation and parsing
        if not csv_data or not csv_data.strip():
            raise ValueError("CSV data is empty")
        
        try:
            # Parse CSV with automatic type inference
            self.df = pd.read_csv(pd.io.common.StringIO(csv_data))
            
            if self.df.empty:
                raise ValueError("CSV contains no data")
                
            # Detect column types and patterns
            self._detect_column_types()
            self._detect_column_patterns()
            
            return self.df
            
        except pd.errors.EmptyDataError:
            raise ValueError("CSV data is empty or malformed")
        except pd.errors.ParserError as e:
            raise ValueError(f"CSV parsing error: {str(e)}")
    
    def _detect_column_types(self):
        """Detect data types for each column."""
        self.column_types = {}
        
        for col in self.df.columns:
            # Skip if already processed
            if col in self.column_types:
                continue
                
            # Get non-null values
            non_null = self.df[col].dropna()
            if len(non_null) == 0:
                self.column_types[col] = 'unknown'
                continue
            
            # Try to detect type
            col_type = self._infer_column_type(non_null, col)
            self.column_types[col] = col_type
            
            # Convert datetime columns
            if col_type == 'datetime':
                self.df[col] = pd.to_datetime(self.df[col], errors='coerce')
    
    def _infer_column_type(self, series: pd.Series, col_name: str) -> str:
        """
        Infer the type of a pandas Series.
        
        Args:
            series: Non-null pandas Series
            col_name: Column name for pattern matching
            
        Returns:
            Detected type: 'datetime', 'numeric', 'categorical', 'text'
        """
        col_lower = col_name.lower()
        
        # Check for time patterns in column name
        if any(pattern in col_lower for pattern in self.TIME_PATTERNS):
            if self._is_datetime_like(series):
                return 'datetime'
        
        # Check if numeric
        if pd.api.types.is_numeric_dtype(series):
            return 'numeric'
        
        # Check if datetime-like values
        if self._is_datetime_like(series):
            return 'datetime'
        
        # Check if boolean-like
        if self._is_boolean_like(series):
            return 'boolean'
        
        # Check if categorical (limited unique values)
        if self._is_categorical(series):
            return 'categorical'
        
        # Default to text
        return 'text'
    
    def _is_datetime_like(self, series: pd.Series) -> bool:
        """Check if series contains datetime-like values."""
        try:
            # Try to convert a sample to datetime
            sample = series.iloc[:min(10, len(series))]
            pd.to_datetime(sample, errors='raise')
            return True
        except (ValueError, TypeError):
            return False
    
    def _is_boolean_like(self, series: pd.Series) -> bool:
        """Check if series contains boolean-like values."""
        unique_vals = set(str(v).lower() for v in series.unique())
        bool_patterns = {
            'true', 'false', '1', '0', 'yes', 'no', 
            't', 'f', 'y', 'n', 'on', 'off'
        }
        return len(unique_vals) <= 2 and unique_vals.issubset(bool_patterns)
    
    def _is_categorical(self, series: pd.Series) -> bool:
        """Check if series should be treated as categorical."""
        total_count = len(series)
        unique_count = len(series.unique())
        
        # If less than 20 unique values, consider categorical
        if unique_count < 20:
            return True
        
        # If unique ratio is less than 50%, consider categorical
        if unique_count / total_count < 0.5:
            return True
        
        return False
    
    def _detect_column_patterns(self):
        """Detect observability patterns in column names."""
        self.column_patterns = {}
        
        for col in self.df.columns:
            col_lower = col.lower()
            
            # Check each pattern type
            if any(pattern in col_lower for pattern in self.TIME_PATTERNS):
                self.column_patterns[col] = 'time'
            elif any(pattern in col_lower for pattern in self.COUNT_PATTERNS):
                self.column_patterns[col] = 'count'
            elif any(pattern in col_lower for pattern in self.DURATION_PATTERNS):
                self.column_patterns[col] = 'duration'
            elif any(pattern in col_lower for pattern in self.RATE_PATTERNS):
                self.column_patterns[col] = 'rate'
            elif any(pattern in col_lower for pattern in self.ERROR_PATTERNS):
                self.column_patterns[col] = 'error'
            elif any(pattern in col_lower for pattern in self.SERVICE_PATTERNS):
                self.column_patterns[col] = 'service'
            elif any(pattern in col_lower for pattern in self.ENDPOINT_PATTERNS):
                self.column_patterns[col] = 'endpoint'
            else:
                self.column_patterns[col] = 'other'
    
    def get_columns_by_type(self, data_type: str) -> List[str]:
        """Get column names by detected type."""
        return [col for col, col_type in self.column_types.items() if col_type == data_type]
    
    def get_columns_by_pattern(self, pattern: str) -> List[str]:
        """Get column names by detected pattern."""
        return [col for col, col_pattern in self.column_patterns.items() if col_pattern == pattern]
    
    def get_numeric_columns(self) -> List[str]:
        """Get all numeric columns."""
        return self.get_columns_by_type('numeric')
    
    def get_categorical_columns(self) -> List[str]:
        """Get all categorical columns."""
        return self.get_columns_by_type('categorical')
    
    def get_datetime_columns(self) -> List[str]:
        """Get all datetime columns."""
        return self.get_columns_by_type('datetime')
    
    def get_time_columns(self) -> List[str]:
        """Get time-related columns (datetime type or time pattern)."""
        datetime_cols = self.get_datetime_columns()
        time_pattern_cols = self.get_columns_by_pattern('time')
        return list(set(datetime_cols + time_pattern_cols))
    
    def suggest_x_column(self) -> Optional[str]:
        """Suggest the best X-axis column."""
        # Prefer time columns for X-axis
        time_cols = self.get_time_columns()
        if time_cols:
            return time_cols[0]
        
        # Then categorical columns
        cat_cols = self.get_categorical_columns()
        if cat_cols:
            return cat_cols[0]
        
        # Finally, first column
        if len(self.df.columns) > 0:
            return self.df.columns[0]
        
        return None
    
    def suggest_y_column(self) -> Optional[str]:
        """Suggest the best Y-axis column."""
        # Prefer numeric columns
        numeric_cols = self.get_numeric_columns()
        if numeric_cols:
            # Prefer count/duration columns
            for col in numeric_cols:
                if self.column_patterns.get(col) in ['count', 'duration', 'rate']:
                    return col
            return numeric_cols[0]
        
        return None
    
    def get_data_summary(self) -> Dict:
        """Get summary of parsed data."""
        if self.df is None:
            return {}
        
        return {
            'total_rows': len(self.df),
            'total_columns': len(self.df.columns),
            'column_types': self.column_types,
            'column_patterns': self.column_patterns,
            'numeric_columns': self.get_numeric_columns(),
            'categorical_columns': self.get_categorical_columns(),
            'datetime_columns': self.get_datetime_columns(),
            'suggested_x': self.suggest_x_column(),
            'suggested_y': self.suggest_y_column()
        }
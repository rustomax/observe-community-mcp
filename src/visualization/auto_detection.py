"""
Auto-detection logic for chart types and column mappings.
"""

import pandas as pd
from typing import Optional, Dict, List, Tuple
from .data_parser import DataParser


def detect_chart_type(df: pd.DataFrame, data_parser: Optional[DataParser] = None) -> str:
    """
    Recommend optimal chart type based on data characteristics.
    
    Args:
        df: pandas DataFrame
        data_parser: Optional DataParser instance with type information
        
    Returns:
        Recommended chart type
    """
    if data_parser is None:
        data_parser = DataParser()
        data_parser.df = df
        data_parser._detect_column_types()
        data_parser._detect_column_patterns()
    
    n_rows = len(df)
    n_cols = len(df.columns)
    
    # Get column classifications
    time_cols = data_parser.get_time_columns()
    numeric_cols = data_parser.get_numeric_columns()
    categorical_cols = data_parser.get_categorical_columns()
    
    # Time series data -> line chart
    if time_cols and numeric_cols:
        return 'line'
    
    # Two numeric columns -> scatter plot
    if len(numeric_cols) >= 2:
        if n_rows > 50:
            return 'scatter'  # Large datasets work better as scatter
        else:
            return 'bar'      # Small datasets work better as bar
    
    # One categorical, one numeric -> bar chart
    if categorical_cols and numeric_cols:
        unique_cats = df[categorical_cols[0]].nunique()
        if unique_cats <= 10:
            return 'bar'
        else:
            return 'scatter'  # Too many categories for bar
    
    # Single numeric column -> histogram
    if len(numeric_cols) == 1 and len(categorical_cols) == 0:
        return 'histogram'
    
    # Single categorical with counts -> pie chart
    if len(categorical_cols) == 1 and len(numeric_cols) <= 1:
        unique_cats = df[categorical_cols[0]].nunique()
        if unique_cats <= 8:  # Pie charts work best with few categories
            return 'pie'
        else:
            return 'bar'
    
    # Default fallback
    return 'bar'


def detect_columns(df: pd.DataFrame, chart_type: str, 
                  data_parser: Optional[DataParser] = None) -> Dict[str, Optional[str]]:
    """
    Auto-detect optimal column mappings for given chart type.
    
    Args:
        df: pandas DataFrame
        chart_type: Target chart type
        data_parser: Optional DataParser instance
        
    Returns:
        Dictionary with suggested column mappings
    """
    if data_parser is None:
        data_parser = DataParser()
        data_parser.df = df
        data_parser._detect_column_types()
        data_parser._detect_column_patterns()
    
    time_cols = data_parser.get_time_columns()
    numeric_cols = data_parser.get_numeric_columns()
    categorical_cols = data_parser.get_categorical_columns()
    
    # Initialize result
    result = {
        'x_column': None,
        'y_column': None,
        'group_by_column': None,
        'value_column': None,
        'label_column': None
    }
    
    if chart_type == 'line':
        # X: time, Y: numeric, Group: categorical
        result['x_column'] = time_cols[0] if time_cols else (categorical_cols[0] if categorical_cols else None)
        result['y_column'] = _get_best_numeric_column(numeric_cols, data_parser)
        result['group_by_column'] = _get_best_grouping_column(categorical_cols, df)
        
    elif chart_type == 'bar':
        # X: categorical, Y: numeric, Group: categorical
        result['x_column'] = _get_best_categorical_column(categorical_cols, df)
        result['y_column'] = _get_best_numeric_column(numeric_cols, data_parser)
        if len(categorical_cols) > 1:
            result['group_by_column'] = categorical_cols[1]
            
    elif chart_type == 'scatter':
        # X: numeric, Y: numeric, Group: categorical
        if len(numeric_cols) >= 2:
            result['x_column'] = numeric_cols[0]
            result['y_column'] = numeric_cols[1]
        result['group_by_column'] = _get_best_grouping_column(categorical_cols, df)
        
    elif chart_type == 'pie':
        # Label: categorical, Value: numeric
        result['label_column'] = _get_best_categorical_column(categorical_cols, df)
        result['value_column'] = _get_best_numeric_column(numeric_cols, data_parser)
        
    elif chart_type == 'histogram':
        # X: numeric (for binning)
        result['x_column'] = _get_best_numeric_column(numeric_cols, data_parser)
        result['group_by_column'] = _get_best_grouping_column(categorical_cols, df)
        
    elif chart_type == 'box':
        # X: categorical, Y: numeric, Group: categorical
        result['x_column'] = _get_best_categorical_column(categorical_cols, df)
        result['y_column'] = _get_best_numeric_column(numeric_cols, data_parser)
        if len(categorical_cols) > 1:
            result['group_by_column'] = categorical_cols[1]
            
    elif chart_type == 'heatmap':
        # X: categorical, Y: categorical, Value: numeric
        if len(categorical_cols) >= 2:
            result['x_column'] = categorical_cols[0]
            result['y_column'] = categorical_cols[1]
        result['value_column'] = _get_best_numeric_column(numeric_cols, data_parser)
    
    return result


def _get_best_numeric_column(numeric_cols: List[str], data_parser: DataParser) -> Optional[str]:
    """Select the best numeric column based on patterns."""
    if not numeric_cols:
        return None
    
    # Priority order for observability metrics
    priority_patterns = ['count', 'duration', 'rate', 'error']
    
    for pattern in priority_patterns:
        for col in numeric_cols:
            if data_parser.column_patterns.get(col) == pattern:
                return col
    
    # Default to first numeric column
    return numeric_cols[0]


def _get_best_categorical_column(categorical_cols: List[str], df: pd.DataFrame) -> Optional[str]:
    """Select the best categorical column."""
    if not categorical_cols:
        return None
    
    # Prefer columns with moderate number of unique values
    best_col = None
    best_score = float('inf')
    
    for col in categorical_cols:
        unique_count = df[col].nunique()
        
        # Ideal range: 2-10 unique values
        if 2 <= unique_count <= 10:
            score = abs(unique_count - 5)  # Prefer around 5 categories
        else:
            score = unique_count  # Penalize too many categories
        
        if score < best_score:
            best_score = score
            best_col = col
    
    return best_col if best_col else categorical_cols[0]


def _get_best_grouping_column(categorical_cols: List[str], df: pd.DataFrame) -> Optional[str]:
    """Select the best column for grouping/color coding."""
    if not categorical_cols:
        return None
    
    # Look for service/application columns first
    service_patterns = ['service', 'app', 'component', 'host', 'pod']
    
    for col in categorical_cols:
        col_lower = col.lower()
        if any(pattern in col_lower for pattern in service_patterns):
            unique_count = df[col].nunique()
            if 2 <= unique_count <= 20:  # Reasonable for grouping
                return col
    
    # Fall back to best categorical column
    return _get_best_categorical_column(categorical_cols, df)


def recommend_chart_and_columns(df: pd.DataFrame) -> Tuple[str, Dict[str, Optional[str]]]:
    """
    Complete auto-detection: recommend chart type and column mappings.
    
    Args:
        df: pandas DataFrame
        
    Returns:
        Tuple of (chart_type, column_mappings)
    """
    # Parse data
    parser = DataParser()
    parser.df = df
    parser._detect_column_types()
    parser._detect_column_patterns()
    
    # Detect chart type
    chart_type = detect_chart_type(df, parser)
    
    # Detect columns for that chart type
    columns = detect_columns(df, chart_type, parser)
    
    return chart_type, columns


def validate_column_mapping(df: pd.DataFrame, chart_type: str, 
                           column_mapping: Dict[str, Optional[str]]) -> List[str]:
    """
    Validate column mapping and return list of issues.
    
    Args:
        df: pandas DataFrame
        chart_type: Chart type
        column_mapping: Column mapping to validate
        
    Returns:
        List of validation error messages
    """
    issues = []
    
    # Check if specified columns exist
    for role, col_name in column_mapping.items():
        if col_name is not None and col_name not in df.columns:
            issues.append(f"{role} column '{col_name}' not found in data")
    
    # Chart-specific validations
    if chart_type in ['line', 'bar', 'scatter']:
        if not column_mapping.get('x_column'):
            issues.append(f"{chart_type} chart requires x_column")
        if not column_mapping.get('y_column'):
            issues.append(f"{chart_type} chart requires y_column")
    
    elif chart_type == 'pie':
        if not column_mapping.get('label_column'):
            issues.append("Pie chart requires label_column")
        if not column_mapping.get('value_column'):
            issues.append("Pie chart requires value_column")
    
    elif chart_type == 'histogram':
        if not column_mapping.get('x_column'):
            issues.append("Histogram requires x_column")
    
    elif chart_type == 'heatmap':
        if not column_mapping.get('x_column'):
            issues.append("Heatmap requires x_column")
        if not column_mapping.get('y_column'):
            issues.append("Heatmap requires y_column")
        if not column_mapping.get('value_column'):
            issues.append("Heatmap requires value_column")
    
    return issues
"""
Utility functions for visualization module.
"""

import base64
import io
from typing import Union
import pandas as pd
from PIL import Image as PILImage
import matplotlib.pyplot as plt


def encode_image(fig_or_bytes: Union[plt.Figure, bytes]) -> str:
    """
    Encode matplotlib figure or bytes to base64 string.
    
    Args:
        fig_or_bytes: matplotlib Figure object or raw bytes
        
    Returns:
        Base64 encoded string of PNG image
    """
    if isinstance(fig_or_bytes, plt.Figure):
        # Convert matplotlib figure to bytes
        buffer = io.BytesIO()
        fig_or_bytes.savefig(buffer, format='png', dpi=150, bbox_inches='tight')
        buffer.seek(0)
        image_bytes = buffer.getvalue()
        buffer.close()
    else:
        image_bytes = fig_or_bytes
    
    # Encode to base64
    return base64.b64encode(image_bytes).decode('utf-8')


def validate_csv(csv_data: str) -> pd.DataFrame:
    """
    Validate and parse CSV data into pandas DataFrame.
    
    Args:
        csv_data: Raw CSV string
        
    Returns:
        pandas DataFrame
        
    Raises:
        ValueError: If CSV is invalid or empty
    """
    if not csv_data or not csv_data.strip():
        raise ValueError("CSV data is empty")
    
    try:
        # Try to parse CSV
        df = pd.read_csv(io.StringIO(csv_data))
        
        if df.empty:
            raise ValueError("CSV contains no data")
            
        if len(df.columns) == 0:
            raise ValueError("CSV contains no columns")
            
        return df
        
    except pd.errors.EmptyDataError:
        raise ValueError("CSV data is empty or malformed")
    except pd.errors.ParserError as e:
        raise ValueError(f"CSV parsing error: {str(e)}")


def optimize_image_size(image_bytes: bytes, max_size_mb: float = 1.0) -> bytes:
    """
    Optimize image size to stay under specified limit.
    
    Args:
        image_bytes: Raw image bytes
        max_size_mb: Maximum size in MB
        
    Returns:
        Optimized image bytes
    """
    max_size_bytes = max_size_mb * 1024 * 1024
    
    if len(image_bytes) <= max_size_bytes:
        return image_bytes
    
    # Reduce quality if too large
    img = PILImage.open(io.BytesIO(image_bytes))
    
    # Try different quality levels
    for quality in [85, 75, 65, 55, 45]:
        buffer = io.BytesIO()
        img.save(buffer, format='JPEG', optimize=True, quality=quality)
        optimized_bytes = buffer.getvalue()
        
        if len(optimized_bytes) <= max_size_bytes:
            return optimized_bytes
    
    # If still too large, reduce resolution
    width, height = img.size
    scale_factor = 0.8
    
    while len(image_bytes) > max_size_bytes and scale_factor > 0.3:
        new_width = int(width * scale_factor)
        new_height = int(height * scale_factor)
        
        resized_img = img.resize((new_width, new_height), PILImage.Resampling.LANCZOS)
        
        buffer = io.BytesIO()
        resized_img.save(buffer, format='JPEG', optimize=True, quality=75)
        image_bytes = buffer.getvalue()
        
        scale_factor -= 0.1
    
    return image_bytes


def format_axis_labels(values, column_name: str = "") -> list:
    """
    Format axis labels based on detected patterns.
    
    Args:
        values: List of values to format
        column_name: Name of the column for context
        
    Returns:
        List of formatted labels
    """
    column_lower = column_name.lower()
    
    # Duration formatting
    if any(pattern in column_lower for pattern in ['duration', 'latency', '_ms', '_ns']):
        return [format_duration(v) if pd.notna(v) else str(v) for v in values]
    
    # Percentage formatting  
    if any(pattern in column_lower for pattern in ['percent', 'rate', 'ratio']):
        return [f"{v:.1f}%" if pd.notna(v) and isinstance(v, (int, float)) else str(v) for v in values]
    
    # Default formatting
    return [str(v) for v in values]


def format_duration(duration_ms: Union[int, float]) -> str:
    """
    Format duration in milliseconds to human-readable string.
    
    Args:
        duration_ms: Duration in milliseconds
        
    Returns:
        Formatted duration string
    """
    if duration_ms < 1:
        return f"{duration_ms:.2f}ms"
    elif duration_ms < 1000:
        return f"{int(duration_ms)}ms"
    elif duration_ms < 60000:  # < 1 minute
        return f"{duration_ms/1000:.1f}s"
    elif duration_ms < 3600000:  # < 1 hour
        return f"{duration_ms/60000:.1f}m"
    else:
        return f"{duration_ms/3600000:.1f}h"
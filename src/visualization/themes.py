"""
Theme definitions for observability visualization.
"""

OBSERVABILITY_THEME = {
    # Color palette optimized for service monitoring
    'colors': {
        'healthy': '#28A745',      # Green - healthy metrics
        'warning': '#FFC107',      # Amber - warning thresholds  
        'critical': '#DC3545',     # Red - critical/error states
        'info': '#17A2B8',         # Teal - informational
        'neutral': '#6C757D',      # Gray - neutral data
        'palette': ['#28A745', '#17A2B8', '#FFC107', '#DC3545', '#6F42C1', '#FD7E14']
    },
    
    # Chart styling for observability dashboards
    'style': {
        'figure_size': (12, 8),
        'dpi': 150,
        'background': '#FFFFFF',
        'grid': True,
        'grid_alpha': 0.3,
        'font_family': 'DejaVu Sans',
        'title_size': 16,
        'axis_label_size': 12,
        'tick_label_size': 10,
        'legend_size': 10,
        'line_width': 2,
        'marker_size': 6,
        'bar_edge_color': '#000000',
        'bar_edge_width': 0.5
    },
    
    # Observability-specific enhancements
    'enhancements': {
        'add_sla_lines': True,        # Add threshold lines
        'highlight_errors': True,     # Red highlighting for errors
        'time_formatting': True,      # Smart time axis formatting  
        'unit_detection': True,       # Auto-detect units (ms, %, count)
        'outlier_annotation': True    # Mark statistical outliers
    }
}

CLEAN_THEME = {
    'colors': {
        'palette': ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd', '#8c564b']
    },
    'style': {
        'figure_size': (10, 6),
        'dpi': 150,
        'background': '#FFFFFF',
        'grid': False,
        'font_family': 'DejaVu Sans',
        'title_size': 14,
        'axis_label_size': 11,
        'tick_label_size': 9,
        'legend_size': 9,
        'line_width': 1.5,
        'marker_size': 4,
        'bar_edge_color': 'none',
        'bar_edge_width': 0
    },
    'enhancements': {
        'add_sla_lines': False,
        'highlight_errors': False,
        'time_formatting': True,
        'unit_detection': False,
        'outlier_annotation': False
    }
}


def apply_theme(ax, theme: dict, chart_type: str = ""):
    """
    Apply theme styling to matplotlib axes.
    
    Args:
        ax: matplotlib axes object
        theme: Theme dictionary
        chart_type: Type of chart for specific styling
    """
    style = theme.get('style', {})
    
    # Grid styling
    if style.get('grid', False):
        ax.grid(True, alpha=style.get('grid_alpha', 0.3))
    
    # Font styling
    font_family = style.get('font_family', 'Arial')
    
    ax.tick_params(
        axis='both',
        which='major',
        labelsize=style.get('tick_label_size', 10)
    )
    
    # Set font family for labels
    for label in ax.get_xticklabels() + ax.get_yticklabels():
        label.set_fontfamily(font_family)
    
    # Background color
    ax.set_facecolor(style.get('background', '#FFFFFF'))
    
    return ax


def get_color_palette(theme: dict, n_colors: int = None) -> list:
    """
    Get color palette from theme.
    
    Args:
        theme: Theme dictionary
        n_colors: Number of colors needed (cycles if needed)
        
    Returns:
        List of color codes
    """
    palette = theme.get('colors', {}).get('palette', ['#1f77b4'])
    
    if n_colors is None:
        return palette
    
    # Cycle through palette if we need more colors
    colors = []
    for i in range(n_colors):
        colors.append(palette[i % len(palette)])
    
    return colors


def get_error_color(theme: dict) -> str:
    """Get error/critical color from theme."""
    return theme.get('colors', {}).get('critical', '#DC3545')


def get_warning_color(theme: dict) -> str:
    """Get warning color from theme."""
    return theme.get('colors', {}).get('warning', '#FFC107')


def get_healthy_color(theme: dict) -> str:
    """Get healthy/success color from theme."""
    return theme.get('colors', {}).get('healthy', '#28A745')
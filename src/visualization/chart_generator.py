"""
Chart generation using matplotlib for OPAL query results.
"""

import matplotlib
matplotlib.use('Agg')  # Use non-interactive backend for server environments

import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import pandas as pd
import numpy as np
import io
from typing import Dict, List, Optional, Union, Tuple
from datetime import datetime

# Optional seaborn import for enhanced heatmaps
try:
    import seaborn as sns
    HAS_SEABORN = True
except ImportError:
    HAS_SEABORN = False
    sns = None

from .themes import OBSERVABILITY_THEME, CLEAN_THEME, apply_theme, get_color_palette
from .data_parser import DataParser
from .auto_detection import detect_chart_type, detect_columns
from .utils import encode_image, optimize_image_size


class ChartGenerator:
    """Generates various chart types from pandas DataFrames."""
    
    SUPPORTED_CHART_TYPES = [
        'line', 'bar', 'scatter', 'heatmap', 'pie', 'histogram', 'box'
    ]
    
    def __init__(self, theme: str = "observability"):
        """
        Initialize chart generator.
        
        Args:
            theme: Theme name ("observability" or "clean")
        """
        self.theme_name = theme
        self.theme = OBSERVABILITY_THEME if theme == "observability" else CLEAN_THEME
        
        # Set matplotlib style
        plt.style.use('default')
        self._configure_matplotlib()
    
    def _configure_matplotlib(self):
        """Configure matplotlib global settings."""
        # Font settings
        style = self.theme.get('style', {})
        plt.rcParams.update({
            'font.family': style.get('font_family', 'Arial'),
            'font.size': style.get('tick_label_size', 10),
            'axes.titlesize': style.get('title_size', 16),
            'axes.labelsize': style.get('axis_label_size', 12),
            'xtick.labelsize': style.get('tick_label_size', 10),
            'ytick.labelsize': style.get('tick_label_size', 10),
            'legend.fontsize': style.get('legend_size', 10),
            'figure.facecolor': style.get('background', '#FFFFFF'),
            'axes.facecolor': style.get('background', '#FFFFFF')
        })
    
    def create_chart(self, df: pd.DataFrame, chart_type: str, 
                    title: str = "", x_column: str = None, y_column: str = None,
                    group_by_column: str = None, **kwargs) -> bytes:
        """
        Create a chart from DataFrame.
        
        Args:
            df: pandas DataFrame with data
            chart_type: Type of chart to create
            title: Chart title
            x_column: X-axis column name (auto-detected if None)
            y_column: Y-axis column name (auto-detected if None)
            group_by_column: Grouping column for multi-series (optional)
            **kwargs: Additional chart-specific parameters
            
        Returns:
            PNG image as bytes
            
        Raises:
            ValueError: If chart type is not supported or data is invalid
        """
        if chart_type not in self.SUPPORTED_CHART_TYPES:
            raise ValueError(f"Unsupported chart type: {chart_type}. "
                           f"Supported types: {', '.join(self.SUPPORTED_CHART_TYPES)}")
        
        if df.empty:
            raise ValueError("DataFrame is empty")
        
        # Auto-detect columns if not specified
        if not x_column or not y_column:
            auto_columns = detect_columns(df, chart_type)
            x_column = x_column or auto_columns.get('x_column')
            y_column = y_column or auto_columns.get('y_column')
            if not group_by_column:
                group_by_column = auto_columns.get('group_by_column')
        
        # Create figure
        style = self.theme.get('style', {})
        fig, ax = plt.subplots(figsize=style.get('figure_size', (12, 8)), 
                              dpi=style.get('dpi', 150))
        
        # Generate chart based on type
        try:
            if chart_type == 'line':
                self._create_line_chart(ax, df, x_column, y_column, group_by_column, **kwargs)
            elif chart_type == 'bar':
                self._create_bar_chart(ax, df, x_column, y_column, group_by_column, **kwargs)
            elif chart_type == 'scatter':
                self._create_scatter_chart(ax, df, x_column, y_column, group_by_column, **kwargs)
            elif chart_type == 'pie':
                self._create_pie_chart(ax, df, x_column, y_column, **kwargs)
            elif chart_type == 'histogram':
                self._create_histogram(ax, df, x_column, group_by_column, **kwargs)
            elif chart_type == 'box':
                self._create_box_chart(ax, df, x_column, y_column, group_by_column, **kwargs)
            elif chart_type == 'heatmap':
                self._create_heatmap(ax, df, x_column, y_column, kwargs.get('value_column'), **kwargs)
                
            # Apply theme and styling
            apply_theme(ax, self.theme, chart_type)
            
            # Set title
            if title:
                ax.set_title(title, fontsize=style.get('title_size', 16), pad=20)
            
            # Tight layout
            plt.tight_layout()
            
            # Convert to bytes - use JPEG for better compatibility with Claude Desktop
            buffer = io.BytesIO()
            fig.savefig(buffer, format='jpeg', dpi=style.get('dpi', 150), 
                       bbox_inches='tight', facecolor=style.get('background', '#FFFFFF'))
            buffer.seek(0)
            image_bytes = buffer.getvalue()
            
            # Optimize size if needed
            image_bytes = optimize_image_size(image_bytes)
            
            return image_bytes
            
        finally:
            plt.close(fig)  # Clean up memory
    
    def _create_line_chart(self, ax, df: pd.DataFrame, x_column: str, y_column: str, 
                          group_by_column: str = None, **kwargs):
        """Create line chart."""
        if not x_column or not y_column:
            raise ValueError("Line chart requires both x_column and y_column")
        
        # Handle grouping
        if group_by_column and group_by_column in df.columns:
            groups = df.groupby(group_by_column)
            colors = get_color_palette(self.theme, len(groups))
            
            for i, (name, group) in enumerate(groups):
                # Sort by x column for proper line drawing
                group_sorted = group.sort_values(x_column)
                ax.plot(group_sorted[x_column], group_sorted[y_column], 
                       label=str(name), color=colors[i], 
                       linewidth=self.theme.get('style', {}).get('line_width', 2),
                       marker='o', markersize=self.theme.get('style', {}).get('marker_size', 6))
            
            ax.legend()
        else:
            # Single series
            df_sorted = df.sort_values(x_column)
            colors = get_color_palette(self.theme, 1)
            ax.plot(df_sorted[x_column], df_sorted[y_column], 
                   color=colors[0],
                   linewidth=self.theme.get('style', {}).get('line_width', 2),
                   marker='o', markersize=self.theme.get('style', {}).get('marker_size', 6))
        
        # Format time axis if needed
        if pd.api.types.is_datetime64_any_dtype(df[x_column]):
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
            ax.xaxis.set_major_locator(mdates.HourLocator(interval=1))
            plt.setp(ax.xaxis.get_majorticklabels(), rotation=45)
        
        ax.set_xlabel(x_column.replace('_', ' ').title())
        ax.set_ylabel(y_column.replace('_', ' ').title())
    
    def _create_bar_chart(self, ax, df: pd.DataFrame, x_column: str, y_column: str,
                         group_by_column: str = None, **kwargs):
        """Create bar chart."""
        if not x_column or not y_column:
            raise ValueError("Bar chart requires both x_column and y_column")
        
        style = self.theme.get('style', {})
        
        # Handle grouping
        if group_by_column and group_by_column in df.columns:
            # Pivot data for grouped bars
            pivot_df = df.pivot_table(values=y_column, index=x_column, 
                                    columns=group_by_column, aggfunc='mean', fill_value=0)
            
            colors = get_color_palette(self.theme, len(pivot_df.columns))
            pivot_df.plot(kind='bar', ax=ax, color=colors,
                         edgecolor=style.get('bar_edge_color', '#000000'),
                         linewidth=style.get('bar_edge_width', 0.5))
            ax.legend(title=group_by_column.replace('_', ' ').title())
        else:
            # Single series bar chart
            colors = get_color_palette(self.theme, 1)
            ax.bar(df[x_column], df[y_column], color=colors[0],
                  edgecolor=style.get('bar_edge_color', '#000000'),
                  linewidth=style.get('bar_edge_width', 0.5))
        
        ax.set_xlabel(x_column.replace('_', ' ').title())
        ax.set_ylabel(y_column.replace('_', ' ').title())
        
        # Rotate x labels if too many categories
        if len(df[x_column].unique()) > 8:
            plt.setp(ax.xaxis.get_majorticklabels(), rotation=45, ha='right')
    
    def _create_scatter_chart(self, ax, df: pd.DataFrame, x_column: str, y_column: str,
                             group_by_column: str = None, **kwargs):
        """Create scatter plot."""
        if not x_column or not y_column:
            raise ValueError("Scatter chart requires both x_column and y_column")
        
        style = self.theme.get('style', {})
        
        # Handle grouping
        if group_by_column and group_by_column in df.columns:
            groups = df.groupby(group_by_column)
            colors = get_color_palette(self.theme, len(groups))
            
            for i, (name, group) in enumerate(groups):
                ax.scatter(group[x_column], group[y_column], 
                          label=str(name), color=colors[i], alpha=0.7,
                          s=style.get('marker_size', 6) * 10)  # Scale marker size
            
            ax.legend()
        else:
            # Single series
            colors = get_color_palette(self.theme, 1)
            ax.scatter(df[x_column], df[y_column], color=colors[0], alpha=0.7,
                      s=style.get('marker_size', 6) * 10)
        
        ax.set_xlabel(x_column.replace('_', ' ').title())
        ax.set_ylabel(y_column.replace('_', ' ').title())
    
    def _create_pie_chart(self, ax, df: pd.DataFrame, label_column: str, value_column: str, **kwargs):
        """Create pie chart."""
        # Use label_column as x_column for consistency
        if not label_column:
            label_column = df.columns[0]
        
        if not value_column and len(df.columns) > 1:
            value_column = df.columns[1]
        elif not value_column:
            # If no value column, create counts
            pie_data = df[label_column].value_counts()
            labels = pie_data.index
            values = pie_data.values
        else:
            # Group by label and sum values
            pie_data = df.groupby(label_column)[value_column].sum()
            labels = pie_data.index
            values = pie_data.values
        
        colors = get_color_palette(self.theme, len(labels))
        
        wedges, texts, autotexts = ax.pie(values, labels=labels, colors=colors,
                                         autopct='%1.1f%%', startangle=90)
        
        # Style the text
        for text in texts:
            text.set_fontsize(self.theme.get('style', {}).get('tick_label_size', 10))
        for autotext in autotexts:
            autotext.set_color('white')
            autotext.set_fontweight('bold')
        
        ax.set_aspect('equal')  # Equal aspect ratio ensures circular pie
    
    def _create_histogram(self, ax, df: pd.DataFrame, x_column: str, 
                         group_by_column: str = None, **kwargs):
        """Create histogram."""
        if not x_column:
            raise ValueError("Histogram requires x_column")
        
        bins = kwargs.get('bins', 20)
        
        # Handle grouping
        if group_by_column and group_by_column in df.columns:
            groups = df.groupby(group_by_column)
            colors = get_color_palette(self.theme, len(groups))
            
            for i, (name, group) in enumerate(groups):
                ax.hist(group[x_column].dropna(), bins=bins, alpha=0.7, 
                       label=str(name), color=colors[i])
            
            ax.legend()
        else:
            # Single series
            colors = get_color_palette(self.theme, 1)
            ax.hist(df[x_column].dropna(), bins=bins, color=colors[0])
        
        ax.set_xlabel(x_column.replace('_', ' ').title())
        ax.set_ylabel('Frequency')
    
    def _create_box_chart(self, ax, df: pd.DataFrame, x_column: str, y_column: str,
                         group_by_column: str = None, **kwargs):
        """Create box plot."""
        if not y_column:
            raise ValueError("Box chart requires y_column")
        
        # If no x_column, create single box plot
        if not x_column:
            box_data = [df[y_column].dropna()]
            labels = [y_column]
        else:
            # Group by x_column
            groups = df.groupby(x_column)
            box_data = [group[y_column].dropna() for name, group in groups]
            labels = [str(name) for name, group in groups]
        
        colors = get_color_palette(self.theme, len(box_data))
        
        bp = ax.boxplot(box_data, labels=labels, patch_artist=True)
        
        # Color the boxes
        for patch, color in zip(bp['boxes'], colors):
            patch.set_facecolor(color)
            patch.set_alpha(0.7)
        
        ax.set_xlabel(x_column.replace('_', ' ').title() if x_column else '')
        ax.set_ylabel(y_column.replace('_', ' ').title())
        
        # Rotate labels if needed
        if len(labels) > 8:
            plt.setp(ax.xaxis.get_majorticklabels(), rotation=45, ha='right')
    
    def _create_heatmap(self, ax, df: pd.DataFrame, x_column: str, y_column: str,
                       value_column: str, **kwargs):
        """Create heatmap."""
        if not all([x_column, y_column, value_column]):
            raise ValueError("Heatmap requires x_column, y_column, and value_column")
        
        # Create pivot table
        pivot_data = df.pivot_table(values=value_column, index=y_column, 
                                   columns=x_column, aggfunc='mean', fill_value=0)
        
        if HAS_SEABORN:
            # Create heatmap using seaborn (enhanced)
            colors = self.theme.get('colors', {}).get('palette', ['#1f77b4'])
            cmap = sns.color_palette(colors, as_cmap=True)
            
            sns.heatmap(pivot_data, ax=ax, cmap=cmap, annot=True, fmt='.1f',
                       cbar_kws={'shrink': 0.8})
        else:
            # Fallback to matplotlib-only heatmap
            colors = self.theme.get('colors', {}).get('palette', ['#1f77b4'])
            
            # Create colormap from theme colors
            from matplotlib.colors import LinearSegmentedColormap
            if len(colors) >= 2:
                cmap = LinearSegmentedColormap.from_list('custom', colors)
            else:
                cmap = 'viridis'
            
            # Create heatmap
            im = ax.imshow(pivot_data, cmap=cmap, aspect='auto')
            
            # Add colorbar
            plt.colorbar(im, ax=ax, shrink=0.8)
            
            # Set ticks and labels
            ax.set_xticks(range(len(pivot_data.columns)))
            ax.set_yticks(range(len(pivot_data.index)))
            ax.set_xticklabels(pivot_data.columns)
            ax.set_yticklabels(pivot_data.index)
            
            # Add value annotations
            for i in range(len(pivot_data.index)):
                for j in range(len(pivot_data.columns)):
                    text = ax.text(j, i, f'{pivot_data.iloc[i, j]:.1f}',
                                 ha="center", va="center", color="white")
        
        ax.set_xlabel(x_column.replace('_', ' ').title())
        ax.set_ylabel(y_column.replace('_', ' ').title())
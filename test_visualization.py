#!/usr/bin/env python3
"""
Test script for visualization functionality.
Tests the core visualization components independently.
"""

import sys
import os
import pandas as pd
from io import StringIO

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

def test_data_parser():
    """Test CSV parsing and type detection."""
    print("🧪 Testing DataParser...")
    
    from visualization.data_parser import DataParser
    
    # Sample observability CSV data
    csv_data = """timestamp,service_name,response_time,error_count,request_count
2024-01-01T10:00:00Z,api-gateway,150,2,100
2024-01-01T10:01:00Z,api-gateway,180,1,120
2024-01-01T10:02:00Z,api-gateway,120,0,90
2024-01-01T10:00:00Z,user-service,200,5,200
2024-01-01T10:01:00Z,user-service,250,3,180
2024-01-01T10:02:00Z,user-service,180,1,220"""
    
    parser = DataParser()
    df = parser.parse(csv_data)
    
    print(f"✅ Parsed {len(df)} rows, {len(df.columns)} columns")
    print(f"   Column types: {parser.column_types}")
    print(f"   Column patterns: {parser.column_patterns}")
    print(f"   Suggested X: {parser.suggest_x_column()}")
    print(f"   Suggested Y: {parser.suggest_y_column()}")
    
    return df, parser

def test_auto_detection(df, parser):
    """Test auto-detection logic."""
    print("\n🎯 Testing Auto-detection...")
    
    from visualization.auto_detection import detect_chart_type, recommend_chart_and_columns
    
    chart_type = detect_chart_type(df, parser)
    print(f"✅ Recommended chart type: {chart_type}")
    
    chart_type_full, columns = recommend_chart_and_columns(df)
    print(f"   Full recommendation: {chart_type_full}")
    print(f"   Column mapping: {columns}")
    
    return chart_type, columns

def test_chart_generation(df, chart_type, columns):
    """Test chart generation."""
    print(f"\n📊 Testing Chart Generation ({chart_type})...")
    
    from visualization.chart_generator import ChartGenerator
    
    generator = ChartGenerator(theme="observability")
    
    try:
        # Test line chart (time series)
        image_bytes = generator.create_chart(
            df, 
            chart_type="line",
            title="Service Response Time Over Time",
            x_column="timestamp",
            y_column="response_time",
            group_by_column="service_name"
        )
        
        print(f"✅ Generated line chart: {len(image_bytes)} bytes")
        
        # Test bar chart 
        image_bytes = generator.create_chart(
            df,
            chart_type="bar", 
            title="Error Count by Service",
            x_column="service_name",
            y_column="error_count"
        )
        
        print(f"✅ Generated bar chart: {len(image_bytes)} bytes")
        
        return True
        
    except Exception as e:
        print(f"❌ Chart generation failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_base64_encoding():
    """Test base64 encoding."""
    print("\n🔐 Testing Base64 Encoding...")
    
    from visualization.utils import encode_image
    
    # Create a simple test image (1x1 pixel PNG)
    test_bytes = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xdb\x00\x00\x00\x00IEND\xaeB`\x82'
    
    base64_str = encode_image(test_bytes)
    print(f"✅ Encoded {len(test_bytes)} bytes to {len(base64_str)} character base64 string")
    
    # Verify it's valid base64
    import base64
    try:
        decoded = base64.b64decode(base64_str)
        print(f"✅ Successfully decoded back to {len(decoded)} bytes")
        return True
    except Exception as e:
        print(f"❌ Base64 validation failed: {e}")
        return False

def main():
    """Run all tests."""
    print("🚀 Testing OPAL Visualization Module")
    print("=" * 50)
    
    try:
        # Test 1: Data parsing
        df, parser = test_data_parser()
        
        # Test 2: Auto-detection  
        chart_type, columns = test_auto_detection(df, parser)
        
        # Test 3: Chart generation
        chart_success = test_chart_generation(df, chart_type, columns)
        
        # Test 4: Base64 encoding
        base64_success = test_base64_encoding()
        
        # Summary
        print(f"\n{'=' * 50}")
        if chart_success and base64_success:
            print("🎉 All tests passed! Visualization module is ready.")
            print("\n📋 Next steps:")
            print("   1. Test in Docker environment")
            print("   2. Test with real OPAL data")
            print("   3. Test all chart types")
            return 0
        else:
            print("❌ Some tests failed. Check the errors above.")
            return 1
            
    except ImportError as e:
        print(f"❌ Import error: {e}")
        print("💡 Missing dependencies. In Docker/venv, run:")
        print("   pip install matplotlib pandas numpy pillow seaborn")
        return 1
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    sys.exit(main())
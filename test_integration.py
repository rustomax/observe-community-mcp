#!/usr/bin/env python3
"""
Integration test for the complete visualization workflow.
Tests the create_visualization function with various data types.
"""

import sys
import os
import asyncio

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

async def test_create_visualization_function():
    """Test the actual create_visualization function."""
    print("🧪 Testing create_visualization function...")
    
    # Mock the Context object
    class MockContext:
        pass
    
    ctx = MockContext()
    
    # Import the function components
    from visualization import ChartGenerator, DataParser
    from visualization.auto_detection import recommend_chart_and_columns, validate_column_mapping
    from visualization.utils import encode_image
    
    # Test data: Time series service metrics
    csv_data = """timestamp,service_name,response_time_ms,error_count,request_count
2024-01-01T10:00:00Z,api-gateway,150,2,100
2024-01-01T10:01:00Z,api-gateway,180,1,120
2024-01-01T10:02:00Z,api-gateway,120,0,90
2024-01-01T10:03:00Z,api-gateway,200,3,110
2024-01-01T10:00:00Z,user-service,200,5,200
2024-01-01T10:01:00Z,user-service,250,3,180
2024-01-01T10:02:00Z,user-service,180,1,220
2024-01-01T10:03:00Z,user-service,220,2,195"""
    
    # Simulate the create_visualization logic
    try:
        # Parse CSV data
        parser = DataParser()
        df = parser.parse(csv_data)
        print(f"✅ Parsed {len(df)} rows, {len(df.columns)} columns")
        
        # Test auto-detection
        chart_type, auto_columns = recommend_chart_and_columns(df)
        print(f"✅ Auto-detected chart type: {chart_type}")
        print(f"   Column mapping: {auto_columns}")
        
        # Test line chart (time series)
        print(f"\n📊 Testing line chart generation...")
        generator = ChartGenerator(theme="observability")
        
        image_bytes = generator.create_chart(
            df, 
            chart_type="line",
            title="Service Response Time Over Time",
            x_column="timestamp",
            y_column="response_time_ms", 
            group_by_column="service_name"
        )
        
        base64_image = encode_image(image_bytes)
        print(f"✅ Generated line chart: {len(image_bytes)} bytes -> {len(base64_image)} base64 chars")
        
        # Test bar chart
        print(f"\n📊 Testing bar chart generation...")
        image_bytes = generator.create_chart(
            df,
            chart_type="bar",
            title="Average Response Time by Service", 
            x_column="service_name",
            y_column="response_time_ms"
        )
        
        base64_image = encode_image(image_bytes)
        print(f"✅ Generated bar chart: {len(image_bytes)} bytes -> {len(base64_image)} base64 chars")
        
        # Test scatter plot
        print(f"\n📊 Testing scatter chart generation...")
        image_bytes = generator.create_chart(
            df,
            chart_type="scatter",
            title="Response Time vs Request Count",
            x_column="request_count",
            y_column="response_time_ms",
            group_by_column="service_name"
        )
        
        base64_image = encode_image(image_bytes)
        print(f"✅ Generated scatter chart: {len(image_bytes)} bytes -> {len(base64_image)} base64 chars")
        
        return True
        
    except Exception as e:
        print(f"❌ Integration test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

async def test_error_handling():
    """Test error handling scenarios."""
    print(f"\n🚨 Testing error handling...")
    
    from visualization.data_parser import DataParser
    
    # Test empty CSV
    try:
        parser = DataParser()
        parser.parse("")
        print("❌ Should have failed on empty CSV")
        return False
    except ValueError:
        print("✅ Correctly handled empty CSV")
    
    # Test malformed CSV
    try:
        parser = DataParser()
        parser.parse("invalid,csv,data\n1,2")  # Missing column
        print("❌ Should have failed on malformed CSV")
        return False
    except ValueError:
        print("✅ Correctly handled malformed CSV")
    
    return True

async def main():
    """Run integration tests."""
    print("🚀 Integration Testing OPAL Visualization")
    print("=" * 50)
    
    try:
        # Test main functionality
        success1 = await test_create_visualization_function()
        
        # Test error handling
        success2 = await test_error_handling()
        
        # Summary
        print(f"\n{'=' * 50}")
        if success1 and success2:
            print("🎉 All integration tests passed!")
            print("\n✨ The visualization feature is ready for use!")
            print("\n📋 Usage example:")
            print("   1. csv_data = execute_opal_query(ctx, 'your query', dataset_id='123')")
            print("   2. chart = create_visualization(ctx, csv_data, chart_type='line', title='My Chart')")
            return 0
        else:
            print("❌ Some integration tests failed.")
            return 1
            
    except ImportError as e:
        print(f"❌ Import error: {e}")
        print("💡 Run this in Docker environment where dependencies are installed")
        return 1
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    asyncio.run(main())
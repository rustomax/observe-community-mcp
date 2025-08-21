#!/usr/bin/env python3

import asyncio
import sys
import os
import time

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

async def test_cached_vs_api_speed():
    """Test the speed difference between cached and API-based dataset selection"""
    
    print("🚀 Testing Dataset Selection Performance...")
    print("=" * 60)
    
    # Test query
    test_query = "Show me error rates by service"
    
    # Test cached approach
    print("\n📊 Testing CACHED dataset selection:")
    start_time = time.time()
    
    try:
        from src.dataset_intelligence.direct_selection import get_cached_datasets
        cached_datasets = await get_cached_datasets()
        cached_time = time.time() - start_time
        
        print(f"✅ Cached approach: {len(cached_datasets)} datasets in {cached_time:.3f}s")
        
        # Show some examples
        if cached_datasets:
            print("📋 Sample cached datasets:")
            for i, ds in enumerate(cached_datasets[:3], 1):
                name = ds.get('name', 'Unknown')
                fields = ds.get('key_fields', [])
                category = ds.get('business_category', 'N/A')
                print(f"  {i}. {name} ({category}, {len(fields)} fields)")
        
    except Exception as e:
        print(f"❌ Cached approach failed: {e}")
        import traceback
        traceback.print_exc()
    
    print("\n" + "=" * 60)
    print(f"🎯 Performance Summary:")
    print(f"   Cached: {cached_time:.3f}s")
    print(f"   Benefits: No API calls, field data available immediately")

async def test_direct_selection():
    """Test the new direct selection with cached data"""
    
    print("\n🎯 Testing Direct Selection Logic:")
    print("=" * 60)
    
    test_queries = [
        "Show me error rates by service",
        "Find slow traces over 2 seconds",
        "Analyze log patterns for exceptions"
    ]
    
    try:
        from src.dataset_intelligence.direct_selection import find_datasets_direct
        
        for query in test_queries:
            print(f"\n📝 Query: {query}")
            
            start_time = time.time()
            results = await find_datasets_direct(query, limit=2)
            elapsed = time.time() - start_time
            
            print(f"⏱️  Selection time: {elapsed:.3f}s")
            print(f"📊 Found {len(results)} suitable datasets:")
            
            for i, ds in enumerate(results, 1):
                name = ds.get('name', 'Unknown')
                score = ds.get('selection_score', 0)
                fields = ds.get('key_fields', [])
                print(f"  {i}. {name} (score: {score:.1f}, {len(fields)} fields)")
                
    except Exception as e:
        print(f"❌ Direct selection failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    async def main():
        await test_cached_vs_api_speed()
        await test_direct_selection()
    
    asyncio.run(main())
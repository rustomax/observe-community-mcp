#!/usr/bin/env python3

import asyncio
import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

async def test_simple_nlp():
    """Test the simplified NLP query without dataset_id"""
    try:
        from src.nlp_agent import execute_nlp_query
        
        print("Testing enhanced NLP query tool...")
        
        result = await execute_nlp_query(
            request="Show me service error rates by service name in the last hour",
            time_range="1h"
        )
        
        print(f"Result: {result}")
        
    except Exception as e:
        import traceback
        print(f"Error: {e}")
        print(f"Traceback: {traceback.format_exc()}")

if __name__ == "__main__":
    asyncio.run(test_simple_nlp())
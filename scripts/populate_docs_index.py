#!/usr/bin/env python3
"""
Populate Pinecone docs index

Uses the unified indexing module to populate the docs index with markdown documents.
This script has been refactored to use the centralized src.pinecone modules.
"""

import os
import sys
import argparse
from dotenv import load_dotenv

# Add parent directory to Python path so we can import src modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# Load environment variables
load_dotenv()

# Import the new indexing module
from src.pinecone.indexing import index_documents

# Configuration
DOCS_DIR = os.getenv("OBSERVE_DOCS_DIR", "observe-docs")


def main():
    parser = argparse.ArgumentParser(description='Populate Pinecone with markdown documents')
    parser.add_argument('--docs-dir', type=str, default=DOCS_DIR, help='Directory containing markdown files')
    parser.add_argument('--force', action='store_true', help='Force recreation of the index')
    parser.add_argument('--batch-size', type=int, default=50, help='Batch size for uploads')
    args = parser.parse_args()
    
    try:
        print(f"Starting document indexing from: {args.docs_dir}")
        
        # Use the unified indexing function
        total_chunks = index_documents(
            docs_dir=args.docs_dir,
            batch_size=args.batch_size,
            force_recreate=args.force
        )
        
        print(f"Successfully indexed {total_chunks} document chunks!")
        
    except Exception as e:
        print(f"Error during indexing: {e}")
        import traceback
        traceback.print_exc()
        exit(1)


if __name__ == "__main__":
    main()
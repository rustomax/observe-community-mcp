#!/usr/bin/env python3
"""
Populate Pinecone runbooks index

Uses the unified indexing module to populate the runbooks index with markdown runbooks.
This script has been refactored to use the centralized src.pinecone modules.
"""

import os
import argparse
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Import the new indexing module
from src.pinecone.indexing import index_runbooks

# Configuration
RUNBOOKS_DIR = os.getenv("OBSERVE_RUNBOOKS_DIR", "runbooks")


def main():
    parser = argparse.ArgumentParser(description='Populate Pinecone with runbook markdown files')
    parser.add_argument('--runbooks-dir', type=str, default=RUNBOOKS_DIR,
                        help=f'Directory containing runbook markdown files (default: {RUNBOOKS_DIR})')
    parser.add_argument('--force', action='store_true',
                        help='Force recreation of the index')
    
    args = parser.parse_args()
    
    try:
        print(f"Starting runbook indexing from: {args.runbooks_dir}")
        
        # Use the unified indexing function
        total_chunks = index_runbooks(
            runbooks_dir=args.runbooks_dir,
            force_recreate=args.force
        )
        
        print(f"Successfully indexed {total_chunks} runbook chunks!")
        
    except Exception as e:
        print(f"Error during indexing: {e}")
        import traceback
        traceback.print_exc()
        exit(1)


if __name__ == "__main__":
    main()
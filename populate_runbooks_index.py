#!/usr/bin/env python3
import os
import glob
import argparse
from typing import List, Dict, Any
from pinecone import Pinecone
from dotenv import load_dotenv
import time
from tqdm import tqdm
import uuid
import re
import sys

# Load environment variables
load_dotenv()

# Configuration
PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
INDEX_NAME = os.getenv("PINECONE_RUNBOOKS_INDEX", "observe-runbooks")
EMBEDDING_MODEL = "llama-text-embed-v2"  # Pinecone's integrated embedding model
RUNBOOKS_DIR = os.getenv("OBSERVE_RUNBOOKS_DIR", "runbooks")

def find_markdown_files(directory: str) -> List[str]:
    """Find all markdown files in the given directory recursively"""
    if not os.path.exists(directory):
        print(f"Error: Directory {directory} does not exist")
        return []
    
    md_files = []
    for ext in ["md", "markdown"]:
        md_files.extend(glob.glob(f"{directory}/**/*.{ext}", recursive=True))
    
    return md_files

def chunk_markdown(file_path: str, chunk_size: int = 1000) -> List[Dict[str, Any]]:
    """Split markdown file into chunks of approximately chunk_size characters"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Extract title from the first heading or filename
        title_match = re.search(r'^# (.*?)$', content, re.MULTILINE)
        if title_match:
            title = title_match.group(1)
        else:
            title = os.path.basename(file_path).replace('.md', '').replace('_', ' ').title()
        
        # Split by paragraphs (blank lines)
        paragraphs = re.split(r'\n\s*\n', content)
        
        chunks = []
        current_chunk = ""
        current_chunk_size = 0
        
        for para in paragraphs:
            # Skip empty paragraphs
            if not para.strip():
                continue
                
            para_size = len(para)
            
            # If paragraph is too big on its own, split it further
            if para_size > chunk_size:
                # Try to split by sentences
                sentences = re.split(r'(?<=[.!?])\s+', para)
                for sentence in sentences:
                    if len(current_chunk) + len(sentence) <= chunk_size:
                        current_chunk += sentence + " "
                        current_chunk_size += len(sentence) + 1
                    else:
                        if current_chunk:
                            chunks.append({
                                "chunk_text": current_chunk.strip(),
                                "source": file_path,
                                "title": title,
                                "type": "runbook"
                            })
                        current_chunk = sentence + " "
                        current_chunk_size = len(sentence) + 1
            else:
                # If adding this paragraph exceeds the chunk size, start a new chunk
                if current_chunk_size + para_size > chunk_size and current_chunk:
                    chunks.append({
                        "chunk_text": current_chunk.strip(),
                        "source": file_path,
                        "title": title,
                        "type": "runbook"
                    })
                    current_chunk = para + "\n\n"
                    current_chunk_size = para_size + 2
                else:
                    current_chunk += para + "\n\n"
                    current_chunk_size += para_size + 2
        
        # Add the last chunk if it's not empty
        if current_chunk:
            chunks.append({
                "chunk_text": current_chunk.strip(),
                "source": file_path,
                "title": title,
                "type": "runbook"
            })
        
        return chunks
    except Exception as e:
        print(f"Error processing file {file_path}: {e}")
        return []

def initialize_pinecone():
    """Initialize Pinecone client and ensure index exists"""
    if not PINECONE_API_KEY:
        raise ValueError("PINECONE_API_KEY environment variable is not set")
    
    print(f"Initializing Pinecone client")
    pc = Pinecone(api_key=PINECONE_API_KEY)
    
    # Check if index exists, create if it doesn't
    if not pc.has_index(INDEX_NAME):
        print(f"Creating new Pinecone index with integrated embedding model: {INDEX_NAME}")
        pc.create_index_for_model(
            name=INDEX_NAME,
            cloud="aws",
            region="us-east-1",
            embed={
                "model": EMBEDDING_MODEL,
                "field_map": {"text": "chunk_text"}
            }
        )
        # Wait for index to be ready
        print("Waiting for index to be ready...")
        time.sleep(10)
    
    # Get the index
    index = pc.Index(INDEX_NAME)
    print(f"Connected to Pinecone index: {INDEX_NAME}")
    
    return pc, index

def main():
    parser = argparse.ArgumentParser(description='Populate Pinecone with runbook markdown files')
    parser.add_argument('--runbooks-dir', type=str, default=RUNBOOKS_DIR,
                        help=f'Directory containing runbook markdown files (default: {RUNBOOKS_DIR})')
    parser.add_argument('--force', action='store_true',
                        help='Force recreation of the index')
    
    args = parser.parse_args()
    
    # Handle force recreation of index
    if args.force:
        print("Forcing recreation of index")
        try:
            pc = Pinecone(api_key=PINECONE_API_KEY)
            if pc.has_index(INDEX_NAME):
                print(f"Deleting existing index: {INDEX_NAME}")
                pc.delete_index(INDEX_NAME)
                time.sleep(5)  # Wait for deletion to complete
        except Exception as e:
            print(f"Error deleting index: {e}")
    
    try:
        # Initialize Pinecone
        pc, index = initialize_pinecone()
        
        # Find markdown files
        runbooks_dir = os.path.abspath(args.runbooks_dir)
        md_files = find_markdown_files(runbooks_dir)
        print(f"Found {len(md_files)} runbook files")
        
        # Process files
        all_records = []
        chunk_id = 1
        
        for file_path in tqdm(md_files, desc="Processing files"):
            try:
                chunks = chunk_markdown(file_path)
                
                # Add unique ID to each chunk and make path relative
                for chunk in chunks:
                    record_id = f"runbook-{chunk_id}"
                    chunk_id += 1
                    
                    # Convert absolute path to relative path
                    relative_path = os.path.relpath(chunk["source"], start=os.getcwd())
                    chunk["source"] = relative_path
                    
                    all_records.append({"_id": record_id, **chunk})
                    
            except Exception as e:
                print(f"Error processing file {file_path}: {e}")
        
        print(f"Collected {len(all_records)} chunks from {len(md_files)} files")
        
        # Upsert records in batches of 95 to stay within Pinecone's limit of 96
        batch_size = 95
        for i in range(0, len(all_records), batch_size):
            batch = all_records[i:i+batch_size]
            batch_num = i//batch_size + 1
            total_batches = (len(all_records) + batch_size - 1) // batch_size
            
            try:
                print(f"Upserting batch {batch_num}/{total_batches} with {len(batch)} records")
                index.upsert_records(
                    namespace="runbooks",
                    records=batch
                )
                print(f"Successfully upserted batch {batch_num}/{total_batches}")
            except Exception as e:
                print(f"Error upserting batch {batch_num}/{total_batches}: {e}")
                print("Falling back to individual record upserts for this batch...")
                # Try one by one if batch fails
                for record in batch:
                    try:
                        index.upsert_records(namespace="runbooks", records=[record])
                        print(f"Upserted single record: {record['_id']}")
                    except Exception as e2:
                        print(f"Error upserting single record {record['_id']}: {e2}")
        
        print(f"Total chunks added to Pinecone: {len(all_records)}")
        
    except Exception as e:
        print(f"Error during population process: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()

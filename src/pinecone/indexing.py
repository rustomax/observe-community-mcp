"""
Pinecone indexing operations

Provides unified indexing functionality for documents and runbooks,
with support for chunking, embedding generation, and batch upserts.
"""

import os
import sys
import glob
import uuid
import re
from typing import List, Dict, Any, Optional
from tqdm import tqdm
from .client import initialize_pinecone, get_index_config
from .embeddings import get_embeddings_batch


def find_markdown_files(directory: str) -> List[str]:
    """Find all markdown files in the given directory recursively"""
    if not os.path.exists(directory):
        print(f"Error: Directory {directory} does not exist", file=sys.stderr)
        return []
    
    md_files = []
    for ext in ["md", "markdown"]:
        md_files.extend(glob.glob(f"{directory}/**/*.{ext}", recursive=True))
    
    return md_files


def chunk_markdown(file_path: str, chunk_size: int = 1000, chunk_type: str = "docs") -> List[Dict[str, Any]]:
    """
    Split markdown file into chunks of approximately chunk_size characters
    
    Args:
        file_path: Path to the markdown file
        chunk_size: Target size for each chunk in characters
        chunk_type: Type of chunks ("docs" or "runbooks") for field naming
        
    Returns:
        List of chunk dictionaries with appropriate field names
    """
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
                            chunks.append(_create_chunk_dict(
                                current_chunk.strip(), file_path, title, chunk_type
                            ))
                        current_chunk = sentence + " "
                        current_chunk_size = len(sentence) + 1
            else:
                # If adding this paragraph exceeds the chunk size, start a new chunk
                if current_chunk_size + para_size > chunk_size and current_chunk:
                    chunks.append(_create_chunk_dict(
                        current_chunk.strip(), file_path, title, chunk_type
                    ))
                    current_chunk = para + "\n\n"
                    current_chunk_size = para_size + 2
                else:
                    current_chunk += para + "\n\n"
                    current_chunk_size += para_size + 2
        
        # Add the last chunk if it's not empty
        if current_chunk:
            chunks.append(_create_chunk_dict(
                current_chunk.strip(), file_path, title, chunk_type
            ))
        
        return chunks
        
    except Exception as e:
        print(f"Error processing file {file_path}: {e}", file=sys.stderr)
        return []


def _create_chunk_dict(text_content: str, file_path: str, title: str, chunk_type: str) -> Dict[str, Any]:
    """Create a chunk dictionary with appropriate field names based on type"""
    # Convert absolute path to relative path
    relative_path = os.path.relpath(file_path, start=os.getcwd())
    
    if chunk_type == "runbooks":
        return {
            "chunk_text": text_content,
            "source": relative_path,
            "title": title,
            "type": "runbook"
        }
    else:  # docs
        return {
            "text": text_content,
            "source": relative_path,
            "title": title
        }


def index_documents(docs_dir: str, batch_size: int = 50, force_recreate: bool = False) -> int:
    """
    Index documents from a directory into the docs Pinecone index
    
    Args:
        docs_dir: Directory containing markdown documents
        batch_size: Batch size for processing (default: 50)
        force_recreate: Whether to delete and recreate the index
        
    Returns:
        Number of chunks successfully indexed
    """
    try:
        print(f"Indexing documents from: {docs_dir}", file=sys.stderr)
        
        # Initialize Pinecone for docs
        pc, index = initialize_pinecone(index_type="docs")
        
        # Handle force recreation
        if force_recreate:
            print("Force recreation requested - deleting existing index", file=sys.stderr)
            try:
                config = get_index_config(index_type="docs")
                index_name = config["index_name"]
                if pc.has_index(index_name):
                    pc.delete_index(index_name)
                    import time
                    time.sleep(5)  # Wait for deletion
                # Reinitialize after deletion
                pc, index = initialize_pinecone(index_type="docs")
            except Exception as e:
                print(f"Error during force recreation: {e}", file=sys.stderr)
        
        # Find and process markdown files
        docs_dir = os.path.abspath(docs_dir)
        md_files = find_markdown_files(docs_dir)
        print(f"Found {len(md_files)} markdown files", file=sys.stderr)
        
        # Process files into chunks
        all_chunks = []
        for file_path in tqdm(md_files, desc="Processing files"):
            try:
                chunks = chunk_markdown(file_path, chunk_type="docs")
                all_chunks.extend(chunks)
            except Exception as e:
                print(f"Error processing file {file_path}: {e}", file=sys.stderr)
        
        print(f"Collected {len(all_chunks)} chunks from {len(md_files)} files", file=sys.stderr)
        
        return _upsert_chunks_to_index(pc, index, all_chunks, batch_size, chunk_type="docs")
        
    except Exception as e:
        print(f"Error during document indexing: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        return 0


def index_runbooks(runbooks_dir: str, force_recreate: bool = False) -> int:
    """
    Index runbooks from a directory into the runbooks Pinecone index
    
    Args:
        runbooks_dir: Directory containing runbook markdown files
        force_recreate: Whether to delete and recreate the index
        
    Returns:
        Number of chunks successfully indexed
    """
    try:
        print(f"Indexing runbooks from: {runbooks_dir}", file=sys.stderr)
        
        # Initialize Pinecone for runbooks
        pc, index = initialize_pinecone(index_type="runbooks")
        
        # Handle force recreation
        if force_recreate:
            print("Force recreation requested - deleting existing index", file=sys.stderr)
            try:
                config = get_index_config(index_type="runbooks")
                index_name = config["index_name"]
                if pc.has_index(index_name):
                    pc.delete_index(index_name)
                    import time
                    time.sleep(5)  # Wait for deletion
                # Reinitialize after deletion
                pc, index = initialize_pinecone(index_type="runbooks")
            except Exception as e:
                print(f"Error during force recreation: {e}", file=sys.stderr)
        
        # Find and process markdown files
        runbooks_dir = os.path.abspath(runbooks_dir)
        md_files = find_markdown_files(runbooks_dir)
        print(f"Found {len(md_files)} runbook files", file=sys.stderr)
        
        # Process files into chunks
        all_records = []
        chunk_id = 1
        
        for file_path in tqdm(md_files, desc="Processing files"):
            try:
                chunks = chunk_markdown(file_path, chunk_type="runbooks")
                
                # Add unique ID to each chunk
                for chunk in chunks:
                    record_id = f"runbook-{chunk_id}"
                    chunk_id += 1
                    all_records.append({"_id": record_id, **chunk})
                    
            except Exception as e:
                print(f"Error processing file {file_path}: {e}", file=sys.stderr)
        
        print(f"Collected {len(all_records)} chunks from {len(md_files)} files", file=sys.stderr)
        
        return _upsert_runbooks_to_index(pc, index, all_records)
        
    except Exception as e:
        print(f"Error during runbook indexing: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        return 0


def _upsert_chunks_to_index(pc, index, chunks: List[Dict[str, Any]], batch_size: int, chunk_type: str) -> int:
    """Upsert document chunks to Pinecone index"""
    total_chunks_added = 0
    
    # Process in batches
    for i in range(0, len(chunks), batch_size):
        batch_chunks = chunks[i:i+batch_size]
        
        try:
            # Extract texts for embedding
            texts = [chunk["text"] for chunk in batch_chunks]
            
            # Get embeddings using batch processing
            embeddings = get_embeddings_batch(pc, texts, batch_size=10)
            
            # Prepare vectors for upsert
            vectors_to_upsert = []
            for j, (chunk, embedding) in enumerate(zip(batch_chunks, embeddings)):
                try:
                    chunk_id = str(uuid.uuid4())
                    
                    vectors_to_upsert.append({
                        "id": chunk_id,
                        "values": embedding,
                        "metadata": {
                            "text": chunk["text"],
                            "source": chunk["source"],
                            "title": chunk["title"]
                        }
                    })
                except Exception as e:
                    print(f"Error preparing chunk {j}: {e}", file=sys.stderr)
            
            # Upsert vectors to Pinecone
            if vectors_to_upsert:
                try:
                    index.upsert(vectors=vectors_to_upsert)
                    print(f"Upserted batch {i//batch_size + 1}/{(len(chunks)-1)//batch_size + 1} with {len(vectors_to_upsert)} vectors", file=sys.stderr)
                    total_chunks_added += len(vectors_to_upsert)
                except Exception as e:
                    print(f"Error upserting batch: {e}", file=sys.stderr)
                    # Try one by one
                    for k, vector in enumerate(vectors_to_upsert):
                        try:
                            index.upsert(vectors=[vector])
                            total_chunks_added += 1
                        except Exception as e2:
                            print(f"Error upserting single vector: {e2}", file=sys.stderr)
                            
        except Exception as e:
            print(f"Error processing batch starting at index {i}: {e}", file=sys.stderr)
    
    return total_chunks_added


def _upsert_runbooks_to_index(pc, index, records: List[Dict[str, Any]]) -> int:
    """Upsert runbook records to Pinecone index using the runbooks-specific format"""
    total_chunks_added = 0
    
    # Upsert records in batches of 95 to stay within Pinecone's limit
    batch_size = 95
    for i in range(0, len(records), batch_size):
        batch = records[i:i+batch_size]
        batch_num = i//batch_size + 1
        total_batches = (len(records) + batch_size - 1) // batch_size
        
        try:
            print(f"Upserting batch {batch_num}/{total_batches} with {len(batch)} records", file=sys.stderr)
            index.upsert_records(
                namespace="runbooks",
                records=batch
            )
            print(f"Successfully upserted batch {batch_num}/{total_batches}", file=sys.stderr)
            total_chunks_added += len(batch)
        except Exception as e:
            print(f"Error upserting batch {batch_num}/{total_batches}: {e}", file=sys.stderr)
            print("Falling back to individual record upserts for this batch...", file=sys.stderr)
            # Try one by one if batch fails
            for record in batch:
                try:
                    index.upsert_records(namespace="runbooks", records=[record])
                    total_chunks_added += 1
                    print(f"Upserted single record: {record['_id']}", file=sys.stderr)
                except Exception as e2:
                    print(f"Error upserting single record {record['_id']}: {e2}", file=sys.stderr)
    
    return total_chunks_added
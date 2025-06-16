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

# Load environment variables
load_dotenv()

# Configuration
PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
INDEX_NAME = os.getenv("PINECONE_DOCS_INDEX", "observe-docs")
EMBEDDING_MODEL = "llama-text-embed-v2"  # Pinecone's integrated embedding model
DOCS_DIR = os.getenv("OBSERVE_DOCS_DIR", "observe-docs")

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
                                "text": current_chunk.strip(),
                                "source": file_path,
                                "title": title
                            })
                        current_chunk = sentence + " "
                        current_chunk_size = len(sentence) + 1
            else:
                # If adding this paragraph exceeds the chunk size, start a new chunk
                if current_chunk_size + para_size > chunk_size and current_chunk:
                    chunks.append({
                        "text": current_chunk.strip(),
                        "source": file_path,
                        "title": title
                    })
                    current_chunk = para + "\n\n"
                    current_chunk_size = para_size + 2
                else:
                    current_chunk += para + "\n\n"
                    current_chunk_size += para_size + 2
        
        # Add the last chunk if it's not empty
        if current_chunk:
            chunks.append({
                "text": current_chunk.strip(),
                "source": file_path,
                "title": title
            })
        
        return chunks
    except Exception as e:
        print(f"Error processing file {file_path}: {e}")
        return []

def get_embedding(pc, text: str, is_query: bool = False) -> List[float]:
    """Get embedding for a single text using Pinecone's inference API"""
    try:
        # Use Pinecone's inference API to generate embedding
        # Use 'query' input_type for queries and 'passage' for documents
        input_type = "query" if is_query else "passage"
        
        embeddings = pc.inference.embed(
            model=EMBEDDING_MODEL,
            inputs=[text],
            parameters={
                "input_type": input_type
            }
        )
        
        # Return the values from the first (and only) embedding
        if embeddings and len(embeddings) > 0:
            return embeddings[0]["values"]
        else:
            print("Warning: No embeddings returned from Pinecone")
            return [0.0]
    except Exception as e:
        print(f"Error getting embedding: {e}")
        # Return empty embedding as a fallback
        return [0.0]

def get_embeddings_batch(pc, texts: List[str], batch_size: int = 10) -> List[List[float]]:
    """Get embeddings for a list of texts in batches"""
    all_embeddings = []
    
    # Process in smaller batches to avoid API limits
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i+batch_size]
        print(f"Generating embeddings for batch {i//batch_size + 1}/{(len(texts)-1)//batch_size + 1} ({len(batch)} texts)")
        
        try:
            # Generate embeddings for the batch
            batch_embeddings = pc.inference.embed(
                model=EMBEDDING_MODEL,
                inputs=batch,
                parameters={
                    "input_type": "passage"  # Use passage type for documents
                }
            )
            
            # Extract the values from each embedding
            for embedding in batch_embeddings:
                all_embeddings.append(embedding["values"])
                
        except Exception as e:
            print(f"Error in batch embedding: {e}")
            # Fall back to individual embeddings on batch failure
            for text in batch:
                try:
                    embedding = get_embedding(pc, text)
                    all_embeddings.append(embedding)
                except Exception as e2:
                    print(f"Error in individual embedding: {e2}")
                    all_embeddings.append([0.0])  # Add dummy embedding on failure
    
    return all_embeddings

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
                "field_map": {"text": "text"}
            }
        )
        # Wait for index to be ready
        time.sleep(10)
    
    # Get the index
    index = pc.Index(INDEX_NAME)
    print(f"Connected to Pinecone index: {INDEX_NAME}")
    return pc, index

def main():
    parser = argparse.ArgumentParser(description='Populate Pinecone with markdown documents')
    parser.add_argument('--docs-dir', type=str, default=DOCS_DIR, help='Directory containing markdown files')
    parser.add_argument('--force', action='store_true', help='Force recreation of the index')
    parser.add_argument('--batch-size', type=int, default=50, help='Batch size for uploads')
    args = parser.parse_args()
    
    # Initialize variables
    pc = None
    index = None
    total_chunks_added = 0
    
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
        docs_dir = os.path.abspath(args.docs_dir)
        md_files = find_markdown_files(docs_dir)
        print(f"Found {len(md_files)} markdown files")
        
        # Process files
        all_chunks = []
        for file_path in tqdm(md_files, desc="Processing files"):
            try:
                chunks = chunk_markdown(file_path)
                all_chunks.extend(chunks)
            except Exception as e:
                print(f"Error processing file {file_path}: {e}")
        
        print(f"Collected {len(all_chunks)} chunks from {len(md_files)} files")
        
        # Prepare chunks for embedding in batches
        batch_size = min(args.batch_size, 100)  # Limit batch size for API calls
        
        # Process in batches
        for i in range(0, len(all_chunks), batch_size):
            batch_chunks = all_chunks[i:i+batch_size]
            
            try:
                # Extract texts for embedding
                texts = [chunk["text"] for chunk in batch_chunks]
                
                # Get embeddings using Pinecone's inference API in batches
                # Use a smaller batch size (10) for the embedding API calls
                embeddings = get_embeddings_batch(pc, texts, batch_size=10)
                
                # Prepare vectors for upsert
                vectors_to_upsert = []
                for j, (chunk, embedding) in enumerate(zip(batch_chunks, embeddings)):
                    try:
                        chunk_id = str(uuid.uuid4())
                        
                        vectors_to_upsert.append({
                            "id": chunk_id,
                            "values": embedding,  # Now embedding is already the values list
                            "metadata": {
                                "text": chunk["text"],
                                "source": chunk["source"],
                                "title": chunk["title"]
                            }
                        })
                    except Exception as e:
                        print(f"Error preparing chunk {j}: {e}")
                
                # Upsert vectors to Pinecone
                if vectors_to_upsert:
                    try:
                        index.upsert(vectors=vectors_to_upsert)
                        print(f"Upserted batch {i//batch_size + 1}/{(len(all_chunks)-1)//batch_size + 1} with {len(vectors_to_upsert)} vectors")
                        total_chunks_added += len(vectors_to_upsert)
                    except Exception as e:
                        print(f"Error upserting batch: {e}")
                        # Try one by one
                        for k, vector in enumerate(vectors_to_upsert):
                            try:
                                index.upsert(vectors=[vector])
                                total_chunks_added += 1
                            except Exception as e2:
                                print(f"Error upserting single vector: {e2}")
            except Exception as e:
                print(f"Error processing batch starting at index {i}: {e}")
    except Exception as e:
        print(f"Error during population process: {e}")
    finally:
        print(f"Total chunks added to Pinecone: {total_chunks_added}")

if __name__ == "__main__":
    main()

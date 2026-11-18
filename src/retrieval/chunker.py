import sys
from pathlib import Path
from typing import Dict, List


# Add project root to Python path
sys.path.append(str(Path(__file__).resolve().parent.parent))

from config import PROCESSED_DATA_DIR, CHUNK_SIZE, CHUNK_OVERLAP


def load_documents(data_dir: Path = PROCESSED_DATA_DIR) -> List[Dict]:
    """Load all .txt files from the processed data directory."""

    documents = []

    for filepath in sorted(data_dir.glob("*.txt")):
        text = filepath.read_text(encoding="utf-8").strip()

        if text:
            documents.append({
                "doc_id": filepath.stem,
                "text": text,
                "source": filepath.name,
            })

    return documents


def chunk_text(
    text: str,
    chunk_size: int = CHUNK_SIZE,
    overlap: int = CHUNK_OVERLAP
) -> List[str]:
    """Split text into overlapping chunks by words."""

    if chunk_size <= 0:
        raise ValueError("chunk_size must be greater than zero")

    if overlap < 0 or overlap >= chunk_size:
        raise ValueError("overlap must be between 0 and chunk_size - 1")

    words = text.split()

    if not words:
        return []

    if len(words) <= chunk_size:
        return [text]

    chunks = []
    start = 0

    while start < len(words):
        end = start + chunk_size

        chunk = " ".join(words[start:end])
        chunks.append(chunk)

        start += chunk_size - overlap

    return chunks


def chunk_all_documents(data_dir: Path = PROCESSED_DATA_DIR) -> List[Dict]:
    """Load all documents and split them into chunks with metadata."""

    documents = load_documents(data_dir)

    all_chunks = []
    chunk_id = 0

    for doc in documents:

        chunks = chunk_text(doc["text"])

        for i, chunk in enumerate(chunks):

            all_chunks.append({
                "chunk_id": chunk_id,
                "doc_id": doc["doc_id"],
                "source": doc["source"],
                "chunk_index": i,
                "total_chunks": len(chunks),
                "text": chunk,
            })

            chunk_id += 1

    return all_chunks


if __name__ == "__main__":

    docs = load_documents()
    chunks = chunk_all_documents()

    print(f"Total documents: {len(docs)}")
    print(f"Total chunks: {len(chunks)}")

    if chunks:
        print("\nSample chunk:")
        print(f"  doc_id: {chunks[0]['doc_id']}")
        print(f"  chunk_index: {chunks[0]['chunk_index']}")
        print(f"  words: {len(chunks[0]['text'].split())}")
        print(f"  text: {chunks[0]['text'][:200]}...")
    else:
        print("\nNo chunks generated. Check your processed data directory.")

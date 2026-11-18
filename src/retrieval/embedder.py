
import sys
import logging
from pathlib import Path
from typing import Dict, List

import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

import httpx
from openai import OpenAI
from pinecone import Pinecone, ServerlessSpec

sys.path.append(str(Path(__file__).resolve().parent.parent))

from config import (
    EMBEDDING_API_KEY,
    EMBEDDING_BASE_URL,
    EMBEDDING_DIMENSIONS,
    EMBEDDING_MAX_BATCH_SIZE,
    EMBEDDING_MODEL,
    PINECONE_API_KEY,
    PINECONE_INDEX_NAME,
    TOP_K,
)

from retrieval.chunker import chunk_all_documents


# Logging configuration
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

logger = logging.getLogger(__name__)


class Embedder:

    def __init__(self):

        # Initialize HTTP client for self-signed SSL certificate
        self.http_client = httpx.Client(
            verify=False,
            timeout=60.0
        )

        # Initialize OpenAI-compatible embedding client
        self.client = OpenAI(
            api_key=EMBEDDING_API_KEY,
            base_url=EMBEDDING_BASE_URL,
            http_client=self.http_client,
            max_retries=3
        )

        # Initialize Pinecone
        self.pc = Pinecone(api_key=PINECONE_API_KEY)

        self.index_name = PINECONE_INDEX_NAME
        self.dimension = EMBEDDING_DIMENSIONS
        self.batch_size = EMBEDDING_MAX_BATCH_SIZE
        self.model = EMBEDDING_MODEL

        self._initialize_index()

    def _initialize_index(self):
        """Create Pinecone index if it does not exist."""

        existing_indexes = [
            idx.name for idx in self.pc.list_indexes()
        ]

        if self.index_name not in existing_indexes:

            logger.info(
                "Creating Pinecone index: %s",
                self.index_name
            )

            self.pc.create_index(
                name=self.index_name,
                dimension=self.dimension,
                metric="cosine",
                spec=ServerlessSpec(
                    cloud="aws",
                    region="us-east-1"
                )
            )

        self.index = self.pc.Index(self.index_name)

        logger.info(
            "Connected to Pinecone index: %s",
            self.index_name
        )

    def generate_embeddings(
        self,
        texts: List[str]
    ) -> List[List[float]]:
        """Generate embeddings for a batch of text."""

        if not texts:
            return []

        response = self.client.embeddings.create(
            model=self.model,
            input=texts
        )

        # Sort by input index to preserve ordering
        sorted_data = sorted(
            response.data,
            key=lambda item: item.index
        )

        embeddings = [
            item.embedding for item in sorted_data
        ]

        if len(embeddings) != len(texts):
            raise ValueError(
                "Embedding count does not match input count"
            )

        for embedding in embeddings:

            if len(embedding) != self.dimension:
                raise ValueError(
                    f"Expected {self.dimension} dimensions, "
                    f"received {len(embedding)}"
                )

        return embeddings

    def embed_and_store(
        self,
        chunks: List[Dict]
    ):
        """Generate embeddings and store chunks in Pinecone."""

        if not chunks:
            logger.warning("No chunks available for embedding")
            return

        if self.batch_size <= 0:
            raise ValueError("Batch size must be greater than zero")

        total_chunks = len(chunks)

        logger.info(
            "Starting embedding for %s chunks",
            total_chunks
        )

        stored_count = 0

        for start in range(0, total_chunks, self.batch_size):

            batch = chunks[start:start + self.batch_size]

            texts = [
                chunk["text"] for chunk in batch
            ]

            embeddings = self.generate_embeddings(texts)

            vectors = []

            for chunk, embedding in zip(batch, embeddings):

                vector_id = (
                    f'{chunk["doc_id"]}_{chunk["chunk_index"]}'
                )

                vectors.append({
                    "id": vector_id,
                    "values": embedding,
                    "metadata": {
                        "doc_id": chunk["doc_id"],
                        "source": chunk["source"],
                        "chunk_index": chunk["chunk_index"],
                        "total_chunks": chunk["total_chunks"],
                        "text": chunk["text"]
                    }
                })

            self.index.upsert(vectors=vectors)

            stored_count += len(vectors)

            logger.info(
                "Embedded and stored %s/%s chunks",
                stored_count,
                total_chunks
            )

        logger.info(
            "Embedding completed. Total vectors: %s",
            stored_count
        )

    def query_similar(
        self,
        query: str,
        top_k: int = TOP_K
    ) -> List[Dict]:
        """Retrieve similar chunks from Pinecone."""

        if not query.strip():
            return []

        embedding = self.generate_embeddings([query])[0]

        results = self.index.query(
            vector=embedding,
            top_k=top_k,
            include_metadata=True
        )

        return [
            {
                "score": match.score,
                "doc_id": match.metadata.get("doc_id"),
                "source": match.metadata.get("source"),
                "chunk_index": match.metadata.get("chunk_index"),
                "text": match.metadata.get("text")
            }
            for match in results.matches
        ]

    def close(self):
        """Close HTTP client resources."""

        self.client.close()
        self.http_client.close()


if __name__ == "__main__":

    embedder = None

    try:
        logger.info("Loading document chunks...")

        chunks = chunk_all_documents()

        logger.info(
            "Total chunks generated: %s",
            len(chunks)
        )

        embedder = Embedder()

        # Generate embeddings and store in Pinecone
        embedder.embed_and_store(chunks)

        # Test similarity search
        results = embedder.query_similar(
            query="What is the employee leave policy?",
            top_k=5
        )

        logger.info("Similarity search results:")

        for result in results:

            print("\nScore:", result["score"])
            print("Source:", result["source"])
            print("Text:", result["text"][:300])

    except Exception:
        logger.exception("Embedding pipeline failed")
        raise

    finally:
        if embedder:
            embedder.close()



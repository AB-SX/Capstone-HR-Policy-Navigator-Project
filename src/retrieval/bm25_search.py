import logging
import re
import sys
from pathlib import Path
from typing import Dict, List

from rank_bm25 import BM25Okapi

sys.path.append(str(Path(__file__).resolve().parent.parent))

from config import TOP_K
from retrieval.chunker import chunk_all_documents


# Logging configuration
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

logger = logging.getLogger(__name__)


class BM25Search:

    def __init__(self):

        self.chunks = []
        self.bm25 = None

        self._build_index()

    @staticmethod
    def tokenize(text: str) -> List[str]:
        """Normalize text and tokenize words."""

        return re.findall(r"\b\w+\b", text.lower())

    def _build_index(self):
        """Load chunks and build BM25 index."""

        logger.info("Loading document chunks for BM25...")

        self.chunks = [
            chunk
            for chunk in chunk_all_documents()
            if chunk.get("text", "").strip()
        ]

        if not self.chunks:
            logger.warning("No chunks available for BM25 indexing")
            return

        tokenized = [
            self.tokenize(chunk["text"])
            for chunk in self.chunks
        ]

        self.bm25 = BM25Okapi(tokenized)

        logger.info(
            "BM25 index built successfully with %s chunks",
            len(self.chunks)
        )

    def query_bm25(
        self,
        query: str,
        top_k: int = TOP_K
    ) -> List[Dict]:
        """Search chunks using BM25 keyword matching."""

        if not query or not query.strip():
            return []

        if top_k <= 0:
            return []

        if self.bm25 is None:
            logger.warning("BM25 index is not initialized")
            return []

        tokenized_query = self.tokenize(query)

        if not tokenized_query:
            return []

        scores = self.bm25.get_scores(tokenized_query)

        # Sort by score in descending order
        top_indices = sorted(
            range(len(scores)),
            key=lambda i: (-scores[i], i)
        )

        results = []

        for idx in top_indices:

            score = float(scores[idx])

            # Skip chunks with no keyword relevance
            if score <= 0:
                continue

            chunk = self.chunks[idx]

            results.append({
                "id": (
                    f'{chunk["doc_id"]}_'
                    f'{chunk["chunk_index"]}'
                ),
                "score": score,
                "doc_id": chunk["doc_id"],
                "source": chunk["source"],
                "chunk_index": chunk["chunk_index"],
                "text": chunk["text"],
            })

            if len(results) >= top_k:
                break

        return results

    def get_index_stats(self) -> Dict:
        """Return BM25 index statistics."""

        return {
            "total_chunks": len(self.chunks),
            "index_initialized": self.bm25 is not None,
        }


if __name__ == "__main__":

    bm25 = BM25Search()

    print("\nBM25 Index Statistics")
    print("-" * 60)
    print(bm25.get_index_stats())

    test_queries = [
        "What is the home office stipend?",
        "COBRA medical coverage",
        "What is the co-working space monthly limit?",
    ]

    for query in test_queries:

        print(f"\nQuery: {query}")
        print("-" * 60)

        results = bm25.query_bm25(query, top_k=5)

        if not results:
            print("No relevant results found.")
            continue

        for r in results:

            print(
                f"Score: {r['score']:.4f} | "
                f"Source: {r['source']}"
            )

            print(f"Chunk ID: {r['id']}")
            print(f"Text: {r['text'][:150]}...")
            print()

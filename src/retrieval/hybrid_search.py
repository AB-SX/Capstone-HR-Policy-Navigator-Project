
import logging
import sys
from pathlib import Path
from typing import Dict, List

sys.path.append(str(Path(__file__).resolve().parent.parent))

if __name__ == "__main__":
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    
from config import TOP_K
from retrieval.embedder import Embedder
from retrieval.bm25_search import BM25Search

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

logger = logging.getLogger(__name__)


class HybridSearch:

    def __init__(self, candidate_multiplier: int = 3):

        logger.info("Initializing hybrid search...")

        if candidate_multiplier <= 0:
            raise ValueError(
                "candidate_multiplier must be greater than zero"
            )

        self.candidate_multiplier = candidate_multiplier

        self.embedder = Embedder()
        self.bm25 = BM25Search()

        logger.info("Hybrid search ready")

    @staticmethod
    def _get_chunk_id(result: Dict) -> str:
        """Generate consistent chunk ID across retrievers."""

        return result.get(
            "id",
            f'{result["doc_id"]}_{result["chunk_index"]}'
        )

    def reciprocal_rank_fusion(
        self,
        dense_results: List[Dict],
        bm25_results: List[Dict],
        k: int = 60
    ) -> List[Dict]:
        """Merge dense and BM25 results using RRF."""

        if k <= 0:
            raise ValueError("RRF k must be greater than zero")

        fused_scores = {}
        chunk_data = {}
        retrieval_sources = {}

        result_lists = [
            ("dense", dense_results),
            ("bm25", bm25_results)
        ]

        for method, results in result_lists:

            for rank, result in enumerate(results, start=1):

                chunk_id = self._get_chunk_id(result)

                # RRF scoring
                rrf_score = 1.0 / (k + rank)

                fused_scores[chunk_id] = (
                    fused_scores.get(chunk_id, 0.0)
                    + rrf_score
                )

                if chunk_id not in chunk_data:
                    chunk_data[chunk_id] = result

                retrieval_sources.setdefault(
                    chunk_id, []
                ).append(method)

        # Sort by fused score, then chunk ID for deterministic ties
        sorted_ids = sorted(
            fused_scores.keys(),
            key=lambda cid: (-fused_scores[cid], cid)
        )

        results = []

        for chunk_id in sorted_ids:

            data = chunk_data[chunk_id]

            results.append({
                "id": chunk_id,
                "score": round(fused_scores[chunk_id], 6),
                "doc_id": data["doc_id"],
                "source": data["source"],
                "chunk_index": data["chunk_index"],
                "text": data["text"],
                "retrieval_method": "hybrid",
                "matched_by": retrieval_sources[chunk_id],
            })

        return results

    def query_hybrid(
        self,
        query: str,
        top_k: int = TOP_K,
        rrf_k: int = 60
    ) -> List[Dict]:
        """Run dense and BM25 search, then fuse using RRF."""

        if not query or not query.strip():
            return []

        if top_k <= 0:
            return []

        fetch_k = top_k * self.candidate_multiplier

        # Dense vector retrieval
        dense_results = self.embedder.query_similar(
            query=query,
            top_k=fetch_k
        )

        # BM25 keyword retrieval
        bm25_results = self.bm25.query_bm25(
            query=query,
            top_k=fetch_k
        )

        logger.info(
            "Dense returned %s, BM25 returned %s results",
            len(dense_results),
            len(bm25_results)
        )

        # Reciprocal Rank Fusion
        fused_results = self.reciprocal_rank_fusion(
            dense_results=dense_results,
            bm25_results=bm25_results,
            k=rrf_k
        )

        final_results = fused_results[:top_k]

        logger.info(
            "Hybrid search returned %s final results",
            len(final_results)
        )

        return final_results

    def close(self):
        """Clean up resources."""

        if hasattr(self, "embedder") and self.embedder:
            self.embedder.close()

        logger.info("Hybrid search resources closed")


if __name__ == "__main__":

    hybrid = None

    try:

        hybrid = HybridSearch(candidate_multiplier=3)

        test_queries = [
            "What is the home office stipend?",
            "COBRA medical coverage",
            "What is the co-working space monthly limit?",
        ]

        for query in test_queries:

            print(f"\nQuery: {query}")
            print("=" * 60)

            results = hybrid.query_hybrid(
                query=query,
                top_k=5
            )

            if not results:
                print("No relevant results found.")
                continue

            for i, result in enumerate(results, 1):

                print(
                    f"\nRank {i} | "
                    f"RRF Score: {result['score']:.6f}"
                )

                print(f"Source: {result['source']}")
                print(f"Chunk ID: {result['id']}")
                print(f"Matched by: {result['matched_by']}")
                print(f"Text: {result['text'][:150]}...")

    except Exception:

        logger.exception("Hybrid search failed")
        raise

    finally:

        if hybrid:
            hybrid.close()

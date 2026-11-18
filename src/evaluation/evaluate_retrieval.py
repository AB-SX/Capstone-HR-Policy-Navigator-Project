import json
import logging
import sys
from pathlib import Path
from typing import Dict, List

import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

sys.path.append(str(Path(__file__).resolve().parent.parent))

from config import EVAL_DATA_PATH, TOP_K
from retrieval.embedder import Embedder
from retrieval.bm25_search import BM25Search
from retrieval.hybrid_search import HybridSearch


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

logger = logging.getLogger(__name__)


def load_eval_data() -> List[Dict]:
    """Load the 80-query golden evaluation set."""
    with open(EVAL_DATA_PATH, "r") as f:
        return json.load(f)


def check_retrieval_hit(
    results: List[Dict],
    gold_answer: str
) -> bool:
    """Check if any retrieved chunk contains key terms from the gold answer."""
    gold_lower = gold_answer.lower()

    import re
    gold_numbers = set(re.findall(r"\$?\d+(?:[,.]?\d+)*", gold_lower))

    for result in results:
        text_lower = result["text"].lower()

        if gold_numbers:
            numbers_found = sum(
                1 for num in gold_numbers
                if num in text_lower
            )
            if numbers_found >= len(gold_numbers) * 0.5:
                return True

        gold_words = set(gold_lower.split())
        text_words = set(text_lower.split())
        overlap = len(gold_words & text_words) / len(gold_words)
        if overlap >= 0.3:
            return True

    return False


def evaluate_method(
    method_name: str,
    search_fn,
    eval_data: List[Dict],
    k_values: List[int] = None
) -> Dict:
    """Evaluate a search method across multiple k values."""

    if k_values is None:
        k_values = [1, 3, 5, 10]

    results = {k: 0 for k in k_values}
    reciprocal_ranks = []
    max_k = max(k_values)

    for item in eval_data:
        query = item["query"]
        gold = item["gold_answer"]

        search_results = search_fn(query, top_k=max_k)

        found_rank = None
        for rank, result in enumerate(search_results, 1):
            if check_retrieval_hit([result], gold):
                found_rank = rank
                break

        if found_rank:
            reciprocal_ranks.append(1.0 / found_rank)
            for k in k_values:
                if found_rank <= k:
                    results[k] += 1
        else:
            reciprocal_ranks.append(0.0)

    total = len(eval_data)
    recall = {k: results[k] / total for k in k_values}
    mrr = sum(reciprocal_ranks) / total

    return {
        "method": method_name,
        "total_queries": total,
        "recall": recall,
        "mrr": round(mrr, 4),
        "hits": results,
    }


def print_comparison(all_results: List[Dict]):
    """Print a comparison table of all methods."""

    print("\n" + "=" * 70)
    print("RETRIEVAL EVALUATION RESULTS")
    print("=" * 70)

    k_values = list(all_results[0]["recall"].keys())

    header = f"{'Method':<20}"
    for k in k_values:
        header += f" | Recall@{k:<3}"
    header += f" | {'MRR':<6}"
    print(header)
    print("-" * 70)

    for result in all_results:
        row = f"{result['method']:<20}"
        for k in k_values:
            pct = result["recall"][k] * 100
            row += f" | {pct:>7.1f}%"
        row += f" | {result['mrr']:<6.4f}"
        print(row)

    print("-" * 70)

    best_method = max(all_results, key=lambda r: r["recall"][5])
    print(f"\nBest at Recall@5: {best_method['method']} "
          f"({best_method['recall'][5]*100:.1f}%)")

    best_mrr = max(all_results, key=lambda r: r["mrr"])
    print(f"Best MRR: {best_mrr['method']} ({best_mrr['mrr']:.4f})")


if __name__ == "__main__":

    logger.info("Loading evaluation data...")
    eval_data = load_eval_data()
    logger.info("Loaded %s evaluation queries", len(eval_data))

    # Initialize search methods
    logger.info("Initializing search methods...")
    embedder = Embedder()
    bm25 = BM25Search()
    hybrid = HybridSearch()

    all_results = []

    # 1. Dense search evaluation
    logger.info("Evaluating dense search...")
    dense_result = evaluate_method(
        "Dense (Embedding)",
        embedder.query_similar,
        eval_data
    )
    all_results.append(dense_result)

    # 2. BM25 search evaluation
    logger.info("Evaluating BM25 search...")
    bm25_result = evaluate_method(
        "BM25 (Keyword)",
        bm25.query_bm25,
        eval_data
    )
    all_results.append(bm25_result)

    # 3. Hybrid search evaluation
    logger.info("Evaluating hybrid search...")
    hybrid_result = evaluate_method(
        "Hybrid (RRF)",
        hybrid.query_hybrid,
        eval_data
    )
    all_results.append(hybrid_result)

    # Print comparison
    print_comparison(all_results)

    # Save results
    output_path = Path(__file__).resolve().parent.parent.parent / "data" / "evaluation"
    output_file = output_path / "retrieval_evaluation_results.json"

    save_data = []
    for r in all_results:
        save_data.append({
            "method": r["method"],
            "total_queries": r["total_queries"],
            "recall": {f"recall@{k}": v for k, v in r["recall"].items()},
            "mrr": r["mrr"],
            "hits": {f"hits@{k}": v for k, v in r["hits"].items()},
        })

    with open(output_file, "w") as f:
        json.dump(save_data, f, indent=2)

    logger.info("Results saved to %s", output_file)

    # Cleanup
    hybrid.close()

    
"""Strict retrieval evaluation of the production policy_search (recall@k / MRR vs gold docs and pages).

    python -m scripts.eval_retrieval            # uses config/settings.yaml
Writes data/evaluation/retrieval_prod_results.json. Retrieval is measured separately from answer quality (brief III).
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src import config  # noqa: E402
from src.retrieval.policy_search import get_engine, rrf  # noqa: E402

KS = (1, 3, 5, 10)


def score(ranked, items, lookup, level):
    hits, rr = {k: 0 for k in KS}, 0.0
    for it in items:
        gold = set(it["gold_doc_ids"]) if level == "doc" else set(it["gold_pages"])
        rank = next((i for i, c in enumerate(ranked[it["id"]], 1)
                     if (lookup[c]["doc_id"] in gold if level == "doc" else set(lookup[c]["pages"]) & gold)), None)
        rr += 1 / rank if rank else 0
        for k in KS:
            hits[k] += bool(rank and rank <= k)
    n = len(items)
    return {**{f"R@{k}": round(hits[k] / n, 3) for k in KS}, "MRR": round(rr / n, 3)}


def main():
    eng = get_engine()
    items = json.loads(config.EVAL_V11_PATH.read_text(encoding="utf-8"))
    runs = {"bm25": {}, "dense": {}, "hybrid": {}, "hybrid+rerank": {}}
    lat, degraded = [], 0
    for it in items:
        q = it["query"]
        t0 = time.perf_counter()
        b = [c for c, _ in eng.bm25_search(q, 50)]
        d, deg = eng.dense(eng.query_vector(q), 50)
        degraded += deg
        h = rrf({"bm25": b, "dense": [c for c, _ in d]}, eng.p["rrf_k"])[0]
        r, _ = eng.rerank(q, h[:eng.p["rerank_in"]])
        lat.append(time.perf_counter() - t0)
        runs["bm25"][it["id"]] = b[:10]
        runs["dense"][it["id"]] = [c for c, _ in d][:10]
        runs["hybrid"][it["id"]] = h[:10]
        runs["hybrid+rerank"][it["id"]] = r[:10]
    out = {"variant": eng.variant, "reranker": eng.reranker_name, "backend": eng.backend,
           "degraded_queries": degraded, "latency_p50_ms": round(1000 * sorted(lat)[len(lat) // 2]),
           "results": {m: {"doc": score(rk, items, eng.lookup, "doc"), "page": score(rk, items, eng.lookup, "page")}
                       for m, rk in runs.items()}}
    print(json.dumps(out, indent=1))
    (config.EVAL_DIR / "retrieval_prod_results.json").write_text(json.dumps(out, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()

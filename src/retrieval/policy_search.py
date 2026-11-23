"""policy_search(): the single retrieval entry point used by the agents and the API.

Pipeline (ADR-002, accepted 18 Nov):
    BM25 (local) top 50  ┐
                         ├─ RRF (k=60) → top 30 → cross-encoder rerank → top 5 → pack (≤2,500 tokens, C1..C5 tags)
    Pinecone dense top 50┘   (FAISS over the same vectors if Pinecone times out or errors → degraded=True)

Output contract (tests/test_retrieval.py):
    {"ok": True, "data": {"status": "ok"|"no_relevant_policy", "chunks": [...], "tag_map": {...},
                          "max_rerank_score": float, "degraded": bool, "variant": str, "reranker": str,
                          "timings_ms": {...}}}
    {"ok": False, "error_code": "...", "message": "..."}
"""
from __future__ import annotations

import concurrent.futures as cf
import json
import re
import threading
import time
from collections import defaultdict
from functools import lru_cache

import numpy as np

from src import config

_TOK = re.compile(r"\b\w+\b")


def tokenize(text: str) -> list[str]:
    return _TOK.findall(text.lower())


def rrf(rankings: dict[str, list[str]], k: int = 60):
    score, src = defaultdict(float), defaultdict(list)
    for name, ranking in rankings.items():
        for r, cid in enumerate(ranking, 1):
            score[cid] += 1.0 / (k + r)
            src[cid].append(name)
    order = sorted(score, key=lambda c: (-score[c], c))
    return order, dict(score), dict(src)


class PolicySearch:
    """Loads data/index/<variant>/ once; thread-safe for the API."""

    def __init__(self, variant=None, reranker=None, backend=None, embedder=None, pinecone_index=None, cross_encoder=None):
        self.variant = variant or config.setting("retrieval.variant", "c3")
        self.reranker_name = reranker or config.setting("retrieval.reranker", "minilm-l6")
        self.backend = backend or config.setting("retrieval.backend", "pinecone")
        self.namespace = config.setting("retrieval.namespace", f"v2-{self.variant}")
        d = config.INDEX_DIR / self.variant
        if not (d / "chunks.jsonl").exists():
            raise FileNotFoundError(f"{d} missing: run  python -m scripts.build_index --variant {self.variant}")
        self.chunks = [json.loads(line) for line in open(d / "chunks.jsonl", encoding="utf-8")]
        self.ids = [c["chunk_id"] for c in self.chunks]
        self.lookup = {c["chunk_id"]: c for c in self.chunks}
        self.vectors = np.load(d / "vectors.npy").astype(np.float32)
        from rank_bm25 import BM25Okapi
        self.bm25 = BM25Okapi([tokenize(c["text"]) for c in self.chunks])
        import faiss
        self.faiss = faiss.IndexFlatIP(self.vectors.shape[1])
        self.faiss.add(self.vectors)
        self._embedder = embedder
        self._pc_index = pinecone_index
        self._ce = cross_encoder
        self._lock = threading.Lock()
        self._pool = cf.ThreadPoolExecutor(max_workers=4)
        self.min_score = float(config.setting("retrieval.min_rerank_score", 0.0))
        self.p = {k: config.setting(f"retrieval.{k}") for k in ("top_k_each", "rrf_k", "rerank_in", "top_out", "context_tokens")}

    # ------------------------------------------------------------ lazy dependencies
    @property
    def embedder(self):
        if self._embedder is None:
            from src.llm.client import Embedder
            self._embedder = Embedder()
        return self._embedder

    @property
    def pc_index(self):
        if self._pc_index is None:
            from pinecone import Pinecone
            self._pc_index = Pinecone(api_key=config.PINECONE_API_KEY).Index(config.PINECONE_INDEX_NAME)
        return self._pc_index

    @property
    def cross_encoder(self):
        if self._ce is None and self.reranker_name != "none":
            with self._lock:
                if self._ce is None:
                    from sentence_transformers import CrossEncoder
                    self._ce = CrossEncoder(config.setting(f"rerankers.{self.reranker_name}"), max_length=512, device="cpu")
        return self._ce

    # ------------------------------------------------------------ stages
    def bm25_search(self, query, k):
        s = self.bm25.get_scores(tokenize(query))
        top = np.argsort(-s)[:k]
        return [(self.ids[i], float(s[i])) for i in top if s[i] > 0]

    def query_vector(self, query):
        instr = config.setting("embedding.query_instruction", "") if config.setting("embedding.use_query_instruction", True) else ""
        v = np.asarray(_embed_query_cached(self.embedder, instr + query), dtype=np.float32)
        return v / max(np.linalg.norm(v), 1e-12)

    def dense_faiss(self, qv, k):
        s, i = self.faiss.search(qv.reshape(1, -1), k)
        return [(self.ids[j], float(x)) for x, j in zip(s[0], i[0]) if j >= 0]

    def dense_pinecone(self, qv, k):
        r = self.pc_index.query(vector=qv.tolist(), top_k=k, namespace=self.namespace, include_metadata=False)
        return [(m.id, float(m.score)) for m in r.matches if m.id in self.lookup]

    def dense(self, qv, k, force_fail=False):
        """Pinecone with a hard timeout; FAISS fallback. Returns (results, degraded)."""
        if self.backend == "faiss":
            return self.dense_faiss(qv, k), False
        try:
            if force_fail:
                raise TimeoutError("simulated Pinecone outage")
            fut = self._pool.submit(self.dense_pinecone, qv, k)
            res = fut.result(timeout=float(config.setting("retrieval.pinecone_timeout_s", 3.0)))
            if not res:
                raise RuntimeError("empty Pinecone result (namespace not loaded?)")
            return res, False
        except Exception:
            return self.dense_faiss(qv, k), True

    def rerank(self, query, cids):
        if not cids:
            return [], []
        if self.cross_encoder is None:                       # reranker "none": keep RRF order
            return cids, [1.0 / (i + 1) for i in range(len(cids))]
        s = np.asarray(self.cross_encoder.predict([(query, self.lookup[c]["text"]) for c in cids],
                                                  batch_size=16, show_progress_bar=False), dtype=float)
        o = np.argsort(-s)
        return [cids[i] for i in o], [float(s[i]) for i in o]

    def pack(self, cids, scores):
        out, used = [], 0
        for i, (c, s) in enumerate(zip(cids, scores), 1):
            ch = self.lookup[c]
            n = int(len(ch["text"].split()) * 1.3)
            if out and used + n > self.p["context_tokens"]:
                break
            used += n
            out.append({"tag": f"C{i}", "chunk_id": c, "doc_id": ch["doc_id"], "pages": ch["pages"],
                        "score": round(s, 4), "text": ch["text"]})
        return out

    # ------------------------------------------------------------ public
    def search(self, query: str, k: int | None = None, _force_fail: bool = False) -> dict:
        k = k or self.p["top_out"]
        if not isinstance(query, str) or not query.strip():
            return {"ok": False, "error_code": "empty_query", "message": "query must be a non-empty string"}
        query = query.strip()[:1000]
        t, t0 = {}, time.perf_counter()
        try:
            b = [c for c, _ in self.bm25_search(query, self.p["top_k_each"])]
            t["bm25"] = time.perf_counter() - t0
            t1 = time.perf_counter()
            qv = self.query_vector(query)
            t["embed"] = time.perf_counter() - t1
            t2 = time.perf_counter()
            d, degraded = self.dense(qv, self.p["top_k_each"], _force_fail)
            t["dense"] = time.perf_counter() - t2
            cand = rrf({"bm25": b, "dense": [c for c, _ in d]}, self.p["rrf_k"])[0][:self.p["rerank_in"]]
            t3 = time.perf_counter()
            ids, sc = self.rerank(query, cand)
            t["rerank"] = time.perf_counter() - t3
        except Exception as ex:
            return {"ok": False, "error_code": "retrieval_error", "message": f"{type(ex).__name__}: {str(ex)[:300]}"}
        top = float(sc[0]) if sc else 0.0
        status = "ok" if (ids and top >= self.min_score) else "no_relevant_policy"
        chunks = self.pack(ids[:k], sc[:k]) if status == "ok" else []
        return {"ok": True, "data": {
            "status": status, "chunks": chunks,
            "tag_map": {c["tag"]: {"chunk_id": c["chunk_id"], "doc_id": c["doc_id"], "pages": c["pages"]} for c in chunks},
            "max_rerank_score": round(top, 4), "degraded": degraded, "variant": self.variant,
            "reranker": self.reranker_name, "timings_ms": {x: round(1000 * y) for x, y in t.items()}}}


@lru_cache(maxsize=2048)
def _embed_query_cached_inner(embedder_id, text):
    return tuple(_EMBEDDERS[embedder_id].embed([text])[0])


_EMBEDDERS: dict[int, object] = {}


def _embed_query_cached(embedder, text):
    _EMBEDDERS[id(embedder)] = embedder
    return _embed_query_cached_inner(id(embedder), text)


_engine: PolicySearch | None = None
_engine_lock = threading.Lock()


def get_engine() -> PolicySearch:
    global _engine
    if _engine is None:
        with _engine_lock:
            if _engine is None:
                _engine = PolicySearch()
    return _engine


def policy_search(query: str, k: int | None = None) -> dict:
    """Module-level entry point: the agent tool and the API call this."""
    return get_engine().search(query, k)

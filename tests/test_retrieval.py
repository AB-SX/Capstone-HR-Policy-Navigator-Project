"""Contract tests for policy_search (offline: fake embedder / Pinecone / reranker).

Run:  pytest -q tests/test_retrieval.py
The live check against the real index is scripts/eval_retrieval.py.
"""
import pytest

from src.retrieval import policy_search as ps


@pytest.fixture(scope="module")
def engine(fake_engine):
    return fake_engine


def check_contract(r, eng):
    assert "ok" in r
    if not r["ok"]:
        assert {"error_code", "message"} <= set(r)
        return
    d = r["data"]
    assert d["status"] in {"ok", "no_relevant_policy"}
    assert isinstance(d["degraded"], bool) and isinstance(d["max_rerank_score"], float)
    assert len(d["chunks"]) <= eng.p["top_out"]
    for i, c in enumerate(d["chunks"], 1):
        assert c["tag"] == f"C{i}" and c["chunk_id"] in eng.lookup and c["pages"] and c["text"]
        assert d["tag_map"][c["tag"]]["chunk_id"] == c["chunk_id"]
    if d["status"] == "no_relevant_policy":
        assert d["chunks"] == []


def test_contract_and_fallback(engine):
    r = engine.search("home office stipend for new hires")
    check_contract(r, engine)
    assert r["data"]["degraded"] is True          # fake Pinecone is down -> FAISS fallback used


def test_empty_query(engine):
    r = engine.search("   ")
    assert r == {"ok": False, "error_code": "empty_query", "message": "query must be a non-empty string"}


def test_out_of_scope_refused(engine):
    r = engine.search("zebra quantum guitar volcano")
    check_contract(r, engine)
    assert r["data"]["status"] == "no_relevant_policy"


def test_rrf_fuses_same_ids():
    order, score, src = ps.rrf({"bm25": ["a", "b"], "dense": ["b", "c"]}, 60)
    assert order[0] == "b" and src["b"] == ["bm25", "dense"]

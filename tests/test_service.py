"""Serving layer: rate limit, cache (incl. M2 memory on a cache hit), daily cap, ticket confirm."""
import json
import sqlite3

import pytest

from src.agents import graph, single_agent
from src.app import service as svc
from tests.fakes import FakeLLM


@pytest.fixture
def s(monkeypatch, fake_engine, tmp_path):
    llm = FakeLLM()
    monkeypatch.setattr(graph, "get_llm", lambda: llm)
    monkeypatch.setattr(single_agent, "get_llm", lambda: llm)
    from langgraph.checkpoint.sqlite import SqliteSaver
    monkeypatch.setattr(graph, "_graph", graph.build_graph(SqliteSaver(sqlite3.connect(str(tmp_path / "cp.db"),
                                                                                         check_same_thread=False))))
    monkeypatch.setattr(svc.config, "RUNTIME_DIR", tmp_path)
    service = svc.Service()
    service.log_path = tmp_path / "app_log.jsonl"
    return service


def test_rate_limiter_window():
    rl = svc.RateLimiter(2, 60)
    assert rl.check("a", 0) == 0 and rl.check("a", 1) == 0
    assert rl.check("a", 2) > 0 and rl.check("b", 2) == 0
    assert rl.check("a", 61) == 0


def test_m1_answer_is_cached_with_sources(s):
    q = "What is the home office stipend for new hires?"
    a = s.ask(q, "m1", "t-a", [], "ip1")
    assert a["status"] == "answered" and a["sources"] and a["sources"][0]["excerpt"] and not a["cached"]
    b = s.ask(q + "  ", "m1", "t-b", [], "ip1")
    assert b["cached"] and b["answer"] == a["answer"] and b["usage"]["llm_calls"] == 0
    c = s.ask(q, "m1", "t-c", [{"role": "user", "content": "hi"}], "ip1")   # follow-up: never from cache
    assert not c["cached"]


def test_m2_cache_hit_keeps_conversation_memory(s):
    q = "What is the home office stipend for new hires?"
    s.ask(q, "m2", "thread-1", None, "ip1")
    hit = s.ask(q, "m2", "thread-2", None, "ip1")
    assert hit["cached"]
    assert svc.Service._m2_has_history("thread-2")           # the follow-up in thread-2 has context
    follow = s.ask("And what about laptops?", "m2", "thread-2", None, "ip1")
    assert follow["status"] in ("answered", "not_covered") and not follow["cached"]


def test_rate_limit_and_daily_cap(s):
    s.limiter = svc.RateLimiter(1, 60)
    assert s.ask("hello", "m2", "t1", None, "ip9")["status"] == "chitchat"
    assert s.ask("hello again", "m2", "t1", None, "ip9")["status"] == "rate_limited"
    s.limiter = svc.RateLimiter(10, 60)
    s.day_calls = s.daily_cap
    assert s.ask("hello", "m2", "t2", None, "ip9")["status"] == "daily_cap"


def test_ticket_confirm_through_service(s, tmp_path):
    r = s.ask("Please raise a ticket for my parental leave", "m2", "tk1", None, "ip1")
    assert r["status"] == "ticket_pending" and r["pending_ticket"]
    done = s.confirm("tk1", True, "ip1")
    assert done["status"] == "ticket_submitted"


def test_feedback_stores_no_chat_text_and_redacts_comment(s):
    a = s.ask("What is the home office stipend for new hires?", "m1", "f1", [], "ip1")
    s.feedback(0, "wrong amount, call me on +91 98765 43210", {**a, "n_sources": 1})
    rec = json.loads(s.feedback_path.read_text(encoding="utf-8").splitlines()[-1])
    assert rec["rating"] == 0 and "98765" not in rec["comment"] and "stipend" not in json.dumps(rec)
    logs, fb = s.usage_rows()
    assert logs and fb and "question" not in logs[-1]


def test_forget_and_seed_conversation_state(s):
    s.ask("What is the home office stipend for new hires?", "m2", "keep1", None, "ip1")
    assert svc.Service._m2_has_history("keep1")
    s.forget("keep1")
    assert not svc.Service._m2_has_history("keep1")
    s.seed("restored", [{"role": "user", "content": "stipend?"}, {"role": "assistant", "content": "1,500 USD"}])
    assert svc.Service._m2_has_history("restored")
    assert s.purge_expired(force=True) == 0          # nothing older than 24 h

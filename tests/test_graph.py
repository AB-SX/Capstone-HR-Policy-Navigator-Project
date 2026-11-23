"""M2 LangGraph tests with the fake LLM: routes, planner->executor->critic->responder, HITL interrupt/resume, memory."""
import sqlite3

import pytest

from src.agents import graph
from tests.fakes import FakeLLM


@pytest.fixture
def g(monkeypatch, fake_engine, tmp_path):
    llm = FakeLLM()
    monkeypatch.setattr(graph, "get_llm", lambda: llm)
    from langgraph.checkpoint.sqlite import SqliteSaver
    monkeypatch.setattr(graph, "_graph", graph.build_graph(SqliteSaver(sqlite3.connect(str(tmp_path / "cp.db"),
                                                                                         check_same_thread=False))))
    monkeypatch.setattr(graph.config, "RUNTIME_DIR", tmp_path)
    return llm


def test_policy_path(g):
    r = graph.run_m2("What is the home office stipend for new hires?")
    assert r.route == "policy" and r.status == "answered", (r.status, r.error)
    assert r.plan and r.critic and r.tool_calls[0]["name"] == "search_hr_policy"
    assert r.guard["has_citation"] and r.citations


def test_chitchat_and_out_of_scope(g):
    assert graph.run_m2("hello").status == "chitchat"
    assert graph.run_m2("What is the capital of France?").status == "refused"


def test_ticket_requires_human_confirmation(g, tmp_path):
    r = graph.run_m2("Please raise a ticket for my parental leave", thread_id="t1")
    assert r.status == "ticket_pending" and r.pending_ticket["status"] == "draft_awaiting_user_confirmation"
    assert not (tmp_path / "tickets.jsonl").exists()          # nothing sent before confirmation
    tid = r.pending_ticket["ticket_id"]
    r2 = graph.resume_m2("t1", confirm=True)
    assert r2.status == "ticket_submitted" and tid in r2.answer
    assert (tmp_path / "tickets.jsonl").read_text().count(tid) == 1


def test_memory_persists_across_turns(g):
    graph.run_m2("What is the home office stipend?", thread_id="mem")
    st = graph.get_graph().get_state({"configurable": {"thread_id": "mem"}}).values
    assert len(st["history"]) == 2
    graph.run_m2("And for laptops?", thread_id="mem")
    st = graph.get_graph().get_state({"configurable": {"thread_id": "mem"}}).values
    assert len(st["history"]) == 4

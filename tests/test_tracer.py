"""Tracer: one trace per question with nested node / llm / tool spans, using the offline fake LLM."""
import sqlite3

from src.agents import graph
from src.observability import tracer
from tests.fakes import FakeLLM


def test_m2_trace_has_nested_spans(monkeypatch, fake_engine, tmp_path):
    tracer.install(llm_classes=(FakeLLM,))
    llm = FakeLLM()
    monkeypatch.setattr(graph, "get_llm", lambda: llm)
    from langgraph.checkpoint.sqlite import SqliteSaver
    monkeypatch.setattr(graph, "_graph", graph.build_graph(SqliteSaver(sqlite3.connect(str(tmp_path / "cp.db"),
                                                                                         check_same_thread=False))))
    monkeypatch.setattr(graph.config, "RUNTIME_DIR", tmp_path)
    with tracer.trace("What is the home office stipend for new hires?", "m2", {"question_id": "t1"}) as t:
        r = graph.run_m2("What is the home office stipend for new hires?")
        t.finish(r)
    names = [s["name"] for s in t.spans]
    for n in ("router", "planner", "executor", "critic", "responder", "finalize", "tool:search_hr_policy"):
        assert n in names, names
    assert any(s["kind"] == "llm" for s in t.spans)
    ids = {s["span_id"]: s for s in t.spans}
    tool = next(s for s in t.spans if s["name"] == "tool:search_hr_policy")
    assert ids[tool["parent_id"]]["name"] == "executor"            # tool nested under its node
    assert all(s["end_ms"] >= s["start_ms"] for s in t.spans)
    assert t.result["status"] == "answered"
    p = tmp_path / "t.jsonl"
    tracer.write(t, p)
    assert p.read_text().count("\n") == 1

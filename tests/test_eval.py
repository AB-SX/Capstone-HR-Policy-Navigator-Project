"""Eval harness runs end to end with fakes (no endpoint)."""
import json

from scripts import run_eval
from src import config
from src.agents import single_agent
from src.evaluation import metrics
from tests.fakes import FakeLLM


def test_metrics_numbers_normalised():
    d = metrics.deterministic("You get $10K per year [C1].", "Up to $10,000 each year.")
    assert d["numbers_match"]


def test_run_eval_m1(monkeypatch, fake_engine, tmp_path):
    llm = FakeLLM()
    monkeypatch.setattr(single_agent, "get_llm", lambda: llm)
    monkeypatch.setattr(run_eval, "get_llm", lambda: llm)
    items = json.loads(config.EVAL_V11_PATH.read_text(encoding="utf-8"))[:3]
    rows = [run_eval.evaluate_one("m1", it, use_judge=True) for it in items]
    s = run_eval.summarise(rows, "m1", "test")
    assert s["n"] == 3 and s["avg_tool_calls"] >= 1 and "failure_taxonomy" in s
    assert all(r["judge"] == "correct" for r in rows)


def test_refusal_without_search_is_incorrect(monkeypatch):
    class Refuser:
        def chat(self, messages, tools=None, **kw):
            return {"text": "The handbook does not cover Compass.", "tool_calls": None}
    llm = FakeLLM()
    monkeypatch.setattr(single_agent, "get_llm", lambda: Refuser())
    monkeypatch.setattr(run_eval, "get_llm", lambda: llm)      # fake judge says "correct"
    item = {"id": 1, "query": "What is Compass?", "gold_answer": "Compass is the support platform.", "type": "fact"}
    row = run_eval.evaluate_one("m1", item, use_judge=True)
    assert row["judge"] == "incorrect" and row["judge_llm"] == "correct" and row["failure"] == "skipped_search"


def test_rubric_verdict_rules():
    F = metrics.FactCheck
    ok = [F(fact="a", status="present"), F(fact="b", status="present"), F(fact="c", status="present"),
          F(fact="d", status="missing")]
    assert metrics.verdict_from_facts(ok) == "correct"                       # 3/4 present
    assert metrics.verdict_from_facts([F(fact="a", status="present"), F(fact="b", status="missing")]) == "partially_correct"
    assert metrics.verdict_from_facts([F(fact="a", status="contradicted")]) == "incorrect"
    assert metrics.verdict_from_facts([F(fact="a", status="missing")]) == "incorrect"


def test_rejudge_regrades_saved_rows(monkeypatch, fake_engine, tmp_path):
    llm = FakeLLM()
    monkeypatch.setattr(single_agent, "get_llm", lambda: llm)
    monkeypatch.setattr(run_eval, "get_llm", lambda: llm)
    items = json.loads(config.EVAL_V11_PATH.read_text(encoding="utf-8"))[:2]
    rows = [run_eval.evaluate_one("m1", it, use_judge=False) for it in items]
    for r in rows:
        r["judge"] = "incorrect"
        assert "judge_facts" not in r
    regraded = [run_eval.grade(r, "numeric") for r in rows]
    assert all(r["judge"] == "correct" and r["judge_facts"] for r in regraded)


def test_fixed_keyfacts_judge_and_file():
    kf = json.loads((config.EVAL_DIR / "eval_v2_keyfacts.json").read_text(encoding="utf-8"))["facts"]
    assert len(kf) == 92 and all(1 <= len(v) <= 4 for v in kf.values())
    v = metrics.judge(FakeLLM(), "q", "gold", "answer", in_scope=True, key_facts=kf["1"])
    assert v.verdict == "correct" and len(v.facts) == len(kf["1"])
    two_of_three = [{"status": "present"}, {"status": "present"}, {"status": "missing"}]
    assert metrics.verdict_from_facts(two_of_three) == "correct"
    assert metrics.verdict_from_facts([{"status": "present"}, {"status": "missing"}]) == "partially_correct"


def test_final_scrub_keeps_handbook_mailboxes():
    from src.guards.output_guard import final_scrub
    out = final_scrub("Email leaves@gitlab.com or priya.sharma@example.com")
    assert "leaves@gitlab.com" in out and "priya.sharma@example.com" not in out


def test_final_scrub_keeps_contacts_quoted_from_passages():
    from src.guards.output_guard import final_scrub
    src = "Text (970) 449-0178 for leave support."
    out = final_scrub("Text (970) 449-0178, or call me on +91 98765 43210", src)
    assert "(970) 449-0178" in out and "98765 43210" not in out

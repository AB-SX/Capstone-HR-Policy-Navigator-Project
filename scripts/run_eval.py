"""End-to-end evaluation (brief V). Runs ONE system over the eval set, sequentially (1 request per key).

    python -m scripts.run_eval --system m1                # all questions, LLM judge on
    python -m scripts.run_eval --system m1 --limit 5      # quick check
    python -m scripts.run_eval --system m2 --tag v2 --eval-file data/evaluation/eval_v2.json
    python -m scripts.run_eval --system direct            # no-retrieval baseline under the same judge

Resumable: results stream to runtime/eval/<system>_<tag>.jsonl; re-running skips finished questions.
Summary: data/evaluation/results/<system>_<tag>_summary.json (+ .md table for the report).
"""
from __future__ import annotations

import argparse
import json
import statistics as st
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src import config  # noqa: E402
from src.evaluation import metrics  # noqa: E402
from src.llm.client import get_llm, track_usage  # noqa: E402


def run_system(name: str, q: str):
    if name == "m1":
        from src.agents.single_agent import run_m1
        return run_m1(q)
    if name == "m2":
        from src.agents.graph import run_m2
        return run_m2(q)
    if name == "direct":                                   # Week-1-style baseline: no retrieval, no tools
        from src.agents.result import AgentResult
        t0 = time.perf_counter()
        with track_usage() as u:
            out = get_llm().chat([{"role": "system", "content": "You are an HR policy assistant for GitLab. Answer concisely."},
                                  {"role": "user", "content": q}], name="direct", max_tokens=400)
        return AgentResult(question=q, answer=out["text"], status="no_tool", system="direct", usage=u.as_dict(),
                           latency_s=round(time.perf_counter() - t0, 2))
    raise ValueError(name)


def evaluate_one(system, item, use_judge):
    r = run_system(system, item["query"])
    gold_docs = set(item.get("gold_doc_ids") or [])
    retrieved_docs = {c["doc_id"] for c in r.retrieved}
    searches = [t for t in r.tool_calls if t["name"] in ("search_hr_policy", "read_policy_doc") and t["ok"]]
    det = metrics.deterministic(r.answer, item["gold_answer"])
    row = {"id": item["id"], "query": item["query"], "gold_answer": item["gold_answer"],
           "difficulty": item.get("difficulty"), "type": item.get("type"), "topic": item.get("topic"),
           "system": system, "answer": r.answer, "status": r.status, "route": r.route,
           "tool_calls": len(r.tool_calls), "searches": len(searches),
           "tool_errors": sum(1 for t in r.tool_calls if not t["ok"]),
           "tools_used": [t["name"] for t in r.tool_calls],
           "gold_retrieved": bool(gold_docs & retrieved_docs) if gold_docs else None,
           "cited_gold": bool(gold_docs & {c["doc_id"] for c in r.citations}) if gold_docs else None,
           "has_citation": r.guard.get("has_citation", False), "invalid_citations": r.guard.get("invalid_citations", []),
           "ungrounded_numbers": r.guard.get("ungrounded_numbers", []), "degraded_retrieval": r.degraded_retrieval,
           "latency_s": r.latency_s, **{k: r.usage.get(k, 0) for k in ("llm_calls", "prompt_tokens", "completion_tokens",
                                                                       "json_repairs")},
           "critic_rounds": len(r.critic), "error": r.error, **det}
    return grade(row, item.get("type"), use_judge)


_KEYFACTS: dict | None = None


def key_facts_for(qid):
    global _KEYFACTS
    if _KEYFACTS is None:
        p = config.EVAL_DIR / "eval_v2_keyfacts.json"
        _KEYFACTS = json.loads(p.read_text(encoding="utf-8"))["facts"] if p.exists() else {}
    return _KEYFACTS.get(str(qid))


def grade(row, qtype, use_judge=True):
    """Judge one result row (also used by --rejudge on saved rows)."""
    for k in ("judge_llm", "judge_facts"):
        row.pop(k, None)
    if use_judge:
        try:
            in_scope = qtype != "out_of_scope"
            v = metrics.judge(get_llm(), row["query"], row["gold_answer"], row["answer"], in_scope=in_scope,
                              key_facts=key_facts_for(row["id"]) if in_scope else None)
            row["judge"], row["judge_reason"] = v.verdict, v.reason
            if v.facts:
                row["judge_facts"] = v.facts
            if in_scope and not row["searches"] and metrics.REFUSAL_RE.search(row["answer"]):
                row["judge_llm"] = v.verdict                # keep the LLM verdict for transparency
                row["judge"], row["judge_reason"] = "incorrect", "rule: declined an in-scope question without searching"
        except Exception as ex:
            row["judge"], row["judge_reason"] = "incorrect", f"judge_error: {ex}"[:200]
    else:
        row["judge"] = "correct" if row["det_correct"] else "incorrect"
        row["judge_reason"] = "deterministic only"
    row["failure"] = metrics.failure_category(row)
    return row


def summarise(rows, system, tag):
    n = len(rows)
    lat = sorted(r["latency_s"] for r in rows)

    def pct(xs):
        return round(100 * sum(xs) / max(len(xs), 1), 1)

    completed = [r["status"] not in ("error", "step_cap") for r in rows]
    s = {"system": system, "tag": tag, "n": n,
         "accuracy_judge_pct": pct([r["judge"] == "correct" for r in rows]),
         "accuracy_judge_incl_partial_pct": pct([r["judge"] in ("correct", "partially_correct") for r in rows]),
         "accuracy_deterministic_pct": pct([r["det_correct"] for r in rows]),
         "judge_vs_deterministic_agreement_pct": pct([(r["judge"] == "correct") == r["det_correct"] for r in rows]),
         "task_completion_rate_pct": pct(completed),
         "avg_tool_calls": round(st.mean(r["tool_calls"] for r in rows), 2) if rows else 0,
         "avg_llm_calls": round(st.mean(r["llm_calls"] for r in rows), 2) if rows else 0,
         "latency_p50_s": lat[n // 2] if n else 0, "latency_p95_s": lat[min(n - 1, int(n * 0.95))] if n else 0,
         "avg_prompt_tokens": round(st.mean(r["prompt_tokens"] for r in rows)) if rows else 0,
         "avg_completion_tokens": round(st.mean(r["completion_tokens"] for r in rows)) if rows else 0,
         "gold_retrieved_pct": pct([r["gold_retrieved"] for r in rows if r["gold_retrieved"] is not None]),
         "answers_with_citation_pct": pct([r["has_citation"] for r in rows]),
         "answers_with_ungrounded_numbers_pct": pct([bool(r["ungrounded_numbers"]) for r in rows]),
         "invalid_citation_pct": pct([bool(r["invalid_citations"]) for r in rows]),
         "json_repairs_total": sum(r["json_repairs"] for r in rows),
         "failure_taxonomy": dict(Counter(r["failure"] for r in rows if r["failure"]))}
    for key in ("difficulty", "type"):
        groups = defaultdict(list)
        for r in rows:
            if r.get(key):
                groups[r[key]].append(r["judge"] == "correct")
        if groups:
            s[f"accuracy_by_{key}"] = {k: {"n": len(v), "acc_pct": pct(v)} for k, v in groups.items()}
    return s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--system", required=True, choices=["m1", "m2", "direct"])
    ap.add_argument("--eval-file", default=str(config.EVAL_V11_PATH))
    ap.add_argument("--tag", default="v11")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--no-judge", action="store_true")
    ap.add_argument("--fresh", action="store_true", help="ignore previous partial results")
    ap.add_argument("--rejudge", nargs="?", const="", default=None, metavar="ROWS_JSONL",
                    help="re-grade saved answers with the current judge (no agent calls); default file: "
                         "runtime/eval/<system>_<tag>.jsonl")
    a = ap.parse_args()
    if a.rejudge is not None:
        return rejudge(a)

    items = json.loads(Path(a.eval_file).read_text(encoding="utf-8"))
    items = items[:a.limit] if a.limit else items
    out_dir = config.RUNTIME_DIR / "eval"
    out_dir.mkdir(parents=True, exist_ok=True)
    jl = out_dir / f"{a.system}_{a.tag}.jsonl"
    if a.fresh and jl.exists():
        jl.unlink()
    done = {json.loads(line)["id"]: json.loads(line) for line in open(jl, encoding="utf-8")} if jl.exists() else {}
    todo = [it for it in items if it["id"] not in done]
    print(f"{a.system}: {len(items)} questions, {len(done)} already done, {len(todo)} to run")
    t0 = time.time()
    for i, it in enumerate(todo, 1):
        row = evaluate_one(a.system, it, not a.no_judge)
        done[it["id"]] = row
        with open(jl, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        eta = (time.time() - t0) / i * (len(todo) - i)
        print(f"[{i}/{len(todo)}] Q{it['id']:>3} {row['judge']:<17} {row['status']:<14} tools={row['tool_calls']} "
              f"{row['latency_s']:>5.1f}s  fail={row['failure'] or '-'}  ETA {eta / 60:.1f} min")
    rows = [done[it["id"]] for it in items if it["id"] in done]
    s = summarise(rows, a.system, a.tag)
    res_dir = config.EVAL_DIR / "results"
    res_dir.mkdir(parents=True, exist_ok=True)
    (res_dir / f"{a.system}_{a.tag}_summary.json").write_text(json.dumps(s, indent=1), encoding="utf-8")
    (res_dir / f"{a.system}_{a.tag}_rows.json").write_text(json.dumps(rows, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(s, indent=1))


def rejudge(a):
    """Re-grade answers already saved, so a judge change can be compared on identical answers."""
    src = Path(a.rejudge) if a.rejudge else config.RUNTIME_DIR / "eval" / f"{a.system}_{a.tag}.jsonl"
    rows = [json.loads(line) for line in open(src, encoding="utf-8")]
    types = {it["id"]: it.get("type") for it in json.loads(Path(a.eval_file).read_text(encoding="utf-8"))}
    out = config.RUNTIME_DIR / "eval" / f"{a.system}_{a.tag}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists() and out.resolve() == src.resolve():
        out.with_suffix(".before_rejudge.jsonl").write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    print(f"re-judging {len(rows)} saved answers from {src}")
    for i, row in enumerate(rows, 1):
        old = row.get("judge")
        grade(row, types.get(row["id"], row.get("type")), True)
        print(f"[{i}/{len(rows)}] Q{row['id']:>3} {old:<17} -> {row['judge']:<17} fail={row['failure'] or '-'}")
    out.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    s = summarise(rows, a.system, a.tag)
    res_dir = config.EVAL_DIR / "results"
    res_dir.mkdir(parents=True, exist_ok=True)
    (res_dir / f"{a.system}_{a.tag}_summary.json").write_text(json.dumps(s, indent=1), encoding="utf-8")
    (res_dir / f"{a.system}_{a.tag}_rows.json").write_text(json.dumps(rows, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(s, indent=1))


if __name__ == "__main__":
    main()

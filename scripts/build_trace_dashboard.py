"""Build dashboard/data.js from real executions for the static trace dashboard (dashboard/index.html).

Sources (all produced by real runs against the course Qwen3-8B endpoint):
  * data/evaluation/results/archive/*_rows.jsonl   per-question execution records from run_eval
  * data/evaluation/traces/*.jsonl                 span-level traces from scripts.trace_capture
  * src/prompts/track_b_week1_prompt_results.csv    Week 1 prompt-only baseline (4 strategies x 80 questions),
                                                    re-scored with the same deterministic rule as the agents
  * data/evaluation/retrieval_v2_results.json       offline retrieval benchmark (recall@k / MRR, chunk variants)
  * data/evaluation/retrieval_prod_results.json     production retrieval configuration check

    python -m scripts.build_trace_dashboard
    python -m http.server -d dashboard 8000       # open http://localhost:8000
"""
from __future__ import annotations

import ast
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from src import config  # noqa: E402

ARCHIVE = config.EVAL_DIR / "results" / "archive"
TRACES = config.EVAL_DIR / "traces"
OUT = ROOT / "dashboard" / "data.js"

FIELDS = ("id", "query", "gold_answer", "difficulty", "type", "topic", "answer", "status", "route", "tool_calls",
          "searches", "tool_errors", "tools_used", "gold_retrieved", "cited_gold", "has_citation",
          "invalid_citations", "ungrounded_numbers", "degraded_retrieval", "latency_s", "llm_calls",
          "prompt_tokens", "completion_tokens", "json_repairs", "critic_rounds", "error", "token_f1",
          "numbers_match", "det_correct", "judge", "judge_reason", "failure")


def _val(v):
    """Rows were saved with Python reprs as strings in some runs; normalise them."""
    if not isinstance(v, str):
        return v
    s = v.strip()
    if s in ("True", "False"):
        return s == "True"
    if s in ("None", ""):
        return None
    if re.fullmatch(r"-?\d+", s):
        return int(s)
    if re.fullmatch(r"-?\d+\.\d*", s):
        return float(s)
    if s[:1] in "[{(":
        try:
            return ast.literal_eval(s)
        except Exception:
            return v
    return v


def _git_date(path):
    try:
        return subprocess.check_output(["git", "log", "-1", "--format=%cI", "--", str(path)], cwd=ROOT,
                                       text=True).strip() or None
    except Exception:
        return None


def load_runs():
    runs = []
    for p in sorted(ARCHIVE.glob("*_rows.jsonl")):
        m = re.match(r"(m\d)_(v\d+)_run(\d+)_rows", p.stem)
        if not m:
            continue
        system, tag, n = m.groups()
        rows = []
        for line in open(p, encoding="utf-8"):
            r = json.loads(line)
            rows.append({k: _val(r.get(k)) for k in FIELDS})
        summ = p.with_name(p.name.replace("_rows.jsonl", "_summary.json"))
        runs.append({"run_id": f"{system}_{tag}_run{n}", "system": system, "tag": tag, "run": int(n),
                     "label": f"{system.upper()} · eval {tag} · run {n}",
                     "summary": json.loads(summ.read_text()) if summ.exists() else None,
                     "committed": _git_date(p), "rows": rows})
    return runs


def load_traces():
    out = []
    for p in sorted(TRACES.glob("*.jsonl")) if TRACES.exists() else []:
        for line in open(p, encoding="utf-8"):
            t = json.loads(line)
            t["source_file"] = p.name
            out.append(t)
    return out


WEEK1 = ROOT / "src" / "prompts" / "track_b_week1_prompt_results.csv"
RET_V2 = config.EVAL_DIR / "retrieval_v2_results.json"
RET_PROD = config.EVAL_DIR / "retrieval_prod_results.json"


def load_pipeline():
    """Week 1 baseline -> retrieval -> agents. Week 1 used the original 80 questions, which are ids 1-80 of eval_v2
    with identical gold answers, so the like-for-like comparison is restricted to those 80."""
    import csv
    from src.evaluation.metrics import deterministic
    out = {"week1": [], "retrieval": None, "retrieval_prod": None, "overlap_ids": []}
    if WEEK1.exists():
        for r in csv.DictReader(open(WEEK1, encoding="utf-8")):
            d = deterministic(r["prediction"], r["gold_answer"])
            out["week1"].append({"id": int(r["id"]), "strategy": r["strategy"], "prediction": r["prediction"],
                                 "orig_correct": r["is_correct"] == "1", "orig_f1": float(r["token_f1"] or 0),
                                 "det_correct": d["det_correct"], "token_f1": d["token_f1"]})
        out["week1_committed"] = _git_date(WEEK1)
    out["overlap_ids"] = sorted({r["id"] for r in out["week1"]})
    if RET_V2.exists():
        out["retrieval"] = json.loads(RET_V2.read_text())
    if RET_PROD.exists():
        out["retrieval_prod"] = json.loads(RET_PROD.read_text())
    return out


def main():
    data = {"model": config.MODEL_NAME, "endpoint": "course vLLM (OpenAI-compatible)", "built": None,
            "runs": load_runs(), "traces": load_traces(), "pipeline": load_pipeline()}
    import datetime as dt
    data["built"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("window.TRACE_DATA = " + json.dumps(data, ensure_ascii=False, default=str) + ";\n", encoding="utf-8")
    n = sum(len(r["rows"]) for r in data["runs"])
    print(f"wrote {OUT.relative_to(ROOT)}: {len(data['runs'])} runs, {n} executions, {len(data['traces'])} span traces, "
          f"{len(data['pipeline']['week1'])} week-1 rows")


if __name__ == "__main__":
    main()

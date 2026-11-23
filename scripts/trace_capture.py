"""Run real questions through the agent with span-level tracing, for the trace dashboard.

Every question becomes one trace with nested spans (graph nodes, model calls, tool calls), timings, tokens,
the final answer and the judge verdict. Output: data/evaluation/traces/<system>_<tag>.jsonl (resumable).

    python -m scripts.trace_capture --system m2 --limit 20                 # 20 questions from eval v2
    python -m scripts.trace_capture --system m1 --limit 20
    python -m scripts.trace_capture --system m2 --ids 1 5 81 93            # specific questions
    python -m scripts.trace_capture --system m2 --limit 20 --no-judge      # skip the judge (fewer calls)
    python -m scripts.build_trace_dashboard                                # then rebuild dashboard/data.js

Needs the same .env as run_eval (QWEN_API_KEY, QWEN_BASE_URL, COURSE_CA_CERT). Sequential: one request per key.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src import config  # noqa: E402
from src.observability import tracer  # noqa: E402
from scripts import run_eval  # noqa: E402

TRACE_DIR = config.EVAL_DIR / "traces"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--system", default="m2", choices=["m1", "m2"])
    ap.add_argument("--eval-file", default=str(config.EVAL_DIR / "eval_v2.json"))
    ap.add_argument("--tag", default="v2")
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("--ids", nargs="*", default=None)
    ap.add_argument("--no-judge", action="store_true")
    ap.add_argument("--fresh", action="store_true")
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)

    tracer.install()
    items = json.loads(Path(a.eval_file).read_text(encoding="utf-8"))
    if a.ids:
        items = [it for it in items if str(it["id"]) in set(a.ids)]
    elif a.limit:
        items = items[:a.limit]
    out = Path(a.out) if a.out else TRACE_DIR / f"{a.system}_{a.tag}.jsonl"
    if a.fresh and out.exists():
        out.unlink()
    done = {json.loads(l)["meta"]["question_id"] for l in open(out, encoding="utf-8")} if out.exists() else set()
    todo = [it for it in items if str(it["id"]) not in done]
    print(f"{a.system}: {len(items)} questions, {len(done)} traced already, {len(todo)} to run -> {out}")

    real_run = run_eval.run_system
    for i, it in enumerate(todo, 1):
        meta = {"question_id": str(it["id"]), "difficulty": it.get("difficulty"), "type": it.get("type"),
                "topic": it.get("topic"), "eval_file": Path(a.eval_file).name, "model": config.MODEL_NAME,
                "endpoint": config.QWEN_BASE_URL}
        holder = {}

        def traced_run(name, q, _meta=meta):
            with tracer.trace(q, name, _meta) as t:
                r = real_run(name, q)
                t.finish(r)
            holder["t"] = t
            return r

        run_eval.run_system = traced_run
        try:
            row = run_eval.evaluate_one(a.system, it, not a.no_judge)    # judge runs outside the trace
        finally:
            run_eval.run_system = real_run
        t = holder["t"]
        t.result["eval"] = {k: row.get(k) for k in ("judge", "judge_reason", "failure", "gold_answer", "gold_retrieved",
                                                     "cited_gold", "det_correct", "numbers_match")}
        tracer.write(t, out)
        print(f"[{i}/{len(todo)}] Q{it['id']:>3} {row['judge']:<17} {row['status']:<14} spans={len(t.spans):>3} "
              f"{row['latency_s']:>5.1f}s fail={row['failure'] or '-'}")
        time.sleep(0.2)
    print("done. Next: python -m scripts.build_trace_dashboard")


if __name__ == "__main__":
    main()

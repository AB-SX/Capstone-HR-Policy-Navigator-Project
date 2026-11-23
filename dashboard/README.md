# Trace dashboard

A static dashboard of real HR Policy Navigator executions on the course Qwen3-8B endpoint. Open `index.html` through any static server; it needs no backend.

## What it shows

| Tab | Source | Content |
|---|---|---|
| Overview | `data/evaluation/results/archive/*_rows.jsonl` | Task completion, accuracy, tool calls per task, latency p50/p95, tokens per query, the full failure taxonomy (all four brief V buckets, zeros included), accuracy by difficulty, tokens vs latency, tool usage |
| Executions | same | All 98 questions per run, with filters by verdict, failure and difficulty. Click a row for the question, model answer, gold answer, judge reason, execution path and grounding checks |
| Span traces | `data/evaluation/traces/*.jsonl` | One waterfall per question: every LangGraph node, model call and tool call, with timing, tokens, inputs and outputs |
| Compare runs | archive rows | M1 runs 1–3 and M2 run 1 side by side |

## Refresh with new executions

Run this wherever the course endpoint is reachable, using the same `.env` as `run_eval`:

```bash
python -m scripts.trace_capture --system m2 --limit 20        # span traces for 20 eval-v2 questions
python -m scripts.trace_capture --system m1 --limit 20        # optional: single-agent baseline
python -m scripts.trace_capture --system m2 --ids 81 84 93    # specific hard questions
python -m scripts.build_trace_dashboard                       # rebuild dashboard/data.js
python -m http.server -d dashboard 8000                       # open http://localhost:8000
```

`trace_capture` can be resumed and only makes sequential requests, one at a time per key. It records spans through `src/observability/tracer.py`, which wraps the graph nodes, `run_tool` and the LLM client without changing agent behaviour. If `LANGSMITH_TRACING=true`, the same runs also appear in LangSmith.

# ADR-009: Tracing and observability with LangSmith

| | |
|---|---|
| **Status** | Accepted (22 Nov 2026) |
| **Owner (role)** | Observability & safety |

## Context
Brief V: *"Tracing via LangSmith, Langfuse or OpenTelemetry"* is required, alongside end-to-end accuracy, completion rate, tool calls per task, cost and latency per query, and a failure taxonomy.

## Options
| Option | Pros | Cons |
|---|---|---|
| **LangSmith** | Native to LangGraph (env vars only); LLM/tool/latency/token trees; free developer tier; shareable trace links for the report | Hosted SaaS; needs an account |
| Langfuse | Open source; self-hostable | Self-host needs Postgres + ClickHouse; cloud needs callback wiring in code |
| OpenTelemetry | Vendor-neutral | Needs a separate viewer and manual LLM instrumentation |

## Decision
LangSmith, switched on with `LANGSMITH_TRACING=true`, `LANGSMITH_API_KEY` and `LANGSMITH_PROJECT` (`hrnav-dev`, `hrnav-eval`, `hrnav-prod`). Our LLM client and agents add `@traceable` spans. Metrics needed for the report are **also** computed by our own harness (`scripts/run_eval.py`), so results don't depend on LangSmith being up.

## Consequences
- PII is redacted by the input guard **before** any call is traced (ADR-006).
- If the key is missing, tracing is simply off; the app runs normally.

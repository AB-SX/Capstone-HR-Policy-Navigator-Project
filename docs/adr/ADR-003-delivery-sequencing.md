# ADR-003: Build M1 (single agent + one tool) before M2 (multi-agent)

| | |
|---|---|
| **Status** | Proposed |
| **Date** | 18 Nov 2026 |
| **Owner (role)** | Agent orchestration & tools |
| **Affects** | HLD 9 (build plan), LLD 5 (agent graph), report narrative |

## Context

- The architecture doc designs a nine-node LangGraph graph (planner → executor → critic, with loop caps, human confirmation and fallback).
- At the 17 Nov review the mentor asked us to reach **"one agent with one tool and your RAG chunked data"** as soon as possible, and said things get easier after that.
- He also said the report should tell an **improvement story** (baseline → single agent → multi-agent), not chase one accuracy number.
- Nine days remain (deadline Fri 27 Nov), with two more mentor calls: one at the weekend and one around mid-week.

## Decision

| Milestone | Scope | Target date | Shown at |
|---|---|---|---|
| **M1** | One agent (a prebuilt ReAct-style tool-calling agent) + **one tool**, `policy_search`, + a citation-enforcing system prompt | Sat 21 Nov | Weekend mentor call |
| **M2** | Planner → executor → critic graph, `entitlement_calc`, loop caps, fallback, human confirmation | Wed 25 Nov | Mid-week mentor call |
| **Ablation** | Baseline vs M1 vs M2 on eval v2, broken down by difficulty and type | Thu 26 Nov | Report |

- M1 and M2 share the same `policy_search` contract, state field names and eval harness. M1 code is not thrown away; it becomes the single-agent arm of the ablation.
- Retrieval work (ADR-002) and orchestration run **in parallel**: M1 is built against a fake retriever that returns real golden-evidence chunks, then switched to the real index with a config change.
- Scope cuts if time runs short, in this order: ReAct-vs-plan-and-execute variant, semantic cache, `draft_hr_ticket` and the human confirmation step. **Never cut:** the baseline, eval v2 or the failure taxonomy.

## Alternatives considered

| Option | Why not |
|---|---|
| Build the full multi-agent graph first | Highest risk; leaves nothing to show if it slips; no single-agent arm for comparison |
| Single agent only | Misses the mentor's suggested multi-agent comparison and the main finding for the report |

## Consequences

- **Positive:** a working end-to-end system by day 4, a natural ablation, lower delivery risk.
- **Negative:** some prompt work is done twice (the M1 system prompt, then the M2 role prompts).
- **Dependency:** the hosted endpoint must support native tool calling. If it doesn't, M1 uses a JSON-action ReAct loop that we parse ourselves (see the runbook, Step 4).

## Validation

- M1 numbers on the original 80 questions and on v2 are ready before the weekend call.
- M2 beats M1 on the `hard` / `multi_step` tier. If it doesn't, the report explains why.

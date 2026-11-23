# ADR-004: Routing simple questions: always retrieve for policy questions

| | |
|---|---|
| **Status** | Proposed: **differs from the mentor's suggestion, so needs his agreement** |
| **Date** | 18 Nov 2026 |
| **Owner (role)** | Agent orchestration & tools |
| **Affects** | LLD 5 (router node), LLD 11 (cache), M1 system prompt |

## Context

- We asked whether simple questions can skip the full agent loop. The mentor suggested putting this in the **system prompt**: if the agent already knows the answer it replies directly; otherwise it uses the tool ("what is the capital of France → Paris").
- Our Week 1 baseline shows the ≤8B model's *main* failure is **numeric hallucination**: confident, made-up leave limits, allowances and dates. In this domain, "the model already knows" is exactly when it is most likely to be wrong.
- HR answers need a citation to be trustworthy and to be checked in evaluation.

## Decision

1. A **deterministic router** (rules first: keywords and regex; the LLM classifies only when unsure) sorts each message into:
    - `chitchat_meta` (greetings, "what can you do?", thanks): answered directly, no retrieval, no policy facts;
    - `policy`: **always retrieves**. Every factual sentence must carry a citation;
    - `out_of_scope`: refused politely with a reason code;
    - `ambiguous`: one clarifying question.
2. **Fast path** for simple policy questions: one retrieval call and one generation call (no planner or critic). This saves latency without dropping evidence.
3. **Cache** for repeated questions: an exact-match cache on the normalised question plus corpus version (Redis, 24 h TTL). A semantic cache is a stretch goal. Only first-turn questions are cached; follow-ups depend on history.
4. The system prompt **also** says "never state a policy number, limit or date without a citation". This is our version of the mentor's prompt-level guidance, but as a guard rather than permission to answer from memory.

## Alternatives considered

| Option | Why not |
|---|---|
| Mentor's suggestion: the model decides in the system prompt whether to use the tool | A small model is poor at judging what it knows; this would bring back the numeric hallucination we measured |
| Always run the full planner → executor → critic | 3 LLM calls for "hi"; wastes latency and quota on the public deployment |

## Consequences

- **Positive:** no uncited policy facts; lower latency and cost for chit-chat and repeated questions; router decisions can be unit-tested.
- **Negative:** extra router rules to maintain; some general HR questions ("what is gratuity?") will retrieve when they didn't strictly need to. That's acceptable.

## Validation and evidence for the report

- Ablation: run eval v2 with the mentor's prompt-only routing vs our router. Report accuracy, the share of answers with uncited numbers, and latency. This turns the difference of opinion into a finding.
- Router unit tests: at least 30 labelled messages, at least 95% routed correctly.

## Question for the mentor

Are you comfortable with deterministic routing (always retrieve for policy questions) instead of prompt-only self-routing, given the numeric-hallucination evidence from Week 1? We will report both as an ablation.

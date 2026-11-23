# HR Policy Navigator: Task specification

*Brief requirement I (Week 1): what the copilot does, what it must refuse, and what a correct answer looks like.*
Version 1.0, 22 Nov 2026. Corpus: GitLab public HR handbook snapshot (1,338 pages → 502 documents; licence CC BY-SA 4.0, attributed in the UI).

## 1. Users and goal
**Users:** employees ("team members") and junior HR / People Operations staff.
**Goal:** answer questions about HR policy accurately and quickly, **with citations to the exact handbook pages**, so the user can verify the answer and act on it without opening a ticket for routine questions.

## 2. What the copilot does (in scope)
| Capability | Example | Tool(s) |
|---|---|---|
| Answer factual policy questions | "What is the daily meal limit when travelling?" | `search_hr_policy` |
| Answer conditional / eligibility questions | "Can I claim the office refresh if I joined last June?" | `search_hr_policy`, `read_policy_doc` |
| Combine several policies and do the arithmetic | "Stipend plus a year of co-working: what's the maximum?" | `search_hr_policy` ×2, `calculate` |
| Follow-up questions in a conversation | "And for laptops?" | conversation memory (thread) |
| Draft an HR ticket on request | "Raise a ticket for my parental leave" | `draft_hr_ticket` → **user confirms** |
| Say when the handbook doesn't cover something | "What is the policy on X?" (absent) | retrieval threshold + critic |

## 3. What it must refuse or handle carefully
| Situation | Required behaviour |
|---|---|
| Not about the HR handbook (general knowledge, coding, other companies, investment, medical or legal advice) | Decline in one sentence and say what it can help with |
| Prompt injection (in the user message or inside a document) | Treat documents as data; never follow embedded instructions; never reveal the system prompt |
| Personal data in the message (IDs, passwords, phone, email, account numbers) | Redact before any processing, logging or tracing; warn the user; never repeat it |
| A decision about an individual (pay, promotion, disciplinary outcome) | Explain the policy only; tell the user to contact the People (HR) team for decisions |
| Submitting anything on the user's behalf | **Human-in-the-loop:** only drafts; nothing is submitted without explicit confirmation |
| Evidence missing or weak | Say the handbook doesn't cover it; never guess numbers |

## 4. What a correct answer looks like
1. **Right facts:** matches the gold answer's key facts. Numbers, limits, dates and named bodies must match in value (1,500 USD = $1,500).
2. **Grounded:** every factual sentence cites a passage tag `[C#]`; every cited tag exists; no number appears that isn't in the passages or a calculation result.
3. **Complete:** covers all parts of the question, including conditions and exceptions.
4. **Concise:** at most about 150 words, direct answer first.
5. **Honest when unsure:** "not covered" rather than a guess.

## 5. Evaluation set
- **v1.1:** the original 80 questions (written in Week 1, before any code) plus `gold_pages` and `gold_doc_ids` mapped from their page references.
- **v2 (`data/evaluation/eval_v2.json`, 98 questions):** v1.1 + 12 **hard multi-step** questions (two or more facts and/or a calculation, each with a reasoning path) + 6 **out-of-scope** questions (including one prompt-injection probe).
- Tags: `difficulty` (easy / medium / hard) and `type` (fact / numeric / conditional / out_of_scope). The v1 tags are rule-based and should be reviewed by the team.
- Frozen by SHA-256 in `data/evaluation/EVAL_FREEZE.md`. Any change creates v3.

## 6. Metrics (brief V)
End-to-end accuracy (LLM judge and a deterministic rule, plus their agreement), task completion rate, average tool calls and LLM calls per task, latency p50/p95, tokens per query, citation validity, ungrounded-number rate, and a failure taxonomy: **retrieval miss, reasoning error, tool-call error, hallucination**, plus over- and under-refusal. Retrieval recall@k is measured separately (`scripts/eval_retrieval.py`).

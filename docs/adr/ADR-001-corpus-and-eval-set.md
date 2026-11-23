# ADR-001: Corpus and evaluation set v2

| | |
|---|---|
| **Status** | Proposed |
| **Date** | 18 Nov 2026 |
| **Owner (role)** | Domain spec & eval design |
| **Affects** | LLD 2 (ingestion), LLD 9 (evaluation), report |

## Context

- Week 1 used the **GitLab HR handbook**, which is published openly: 1,338 pages split into **502 topic documents**, with **80 golden question–answer pairs** extracted from them. Indian company manuals (e.g. Coal India, NBCC) were rejected because using third-party copies without authorisation may be a compliance problem, and the small public manuals (13–27 pages) were too thin.
- An LLM split the handbook into the 502 documents. At the 17 Nov review the mentor asked us to say how extraction was done and to account for the model's context length, since overflowing it can produce hallucinated content.
- Week 1 baseline accuracy on the 80 questions: direct prompting **18.75%**, few-shot **12.5%**, chain-of-thought **21.25%**, decomposition **22.5%**. The main failure modes were numeric hallucination (invented limits and dates) and template contamination in few-shot prompts (failure rate 87.5%).
- Retrieval tried earlier in Week 1 reportedly scored 80–92%. The mentor read this as a sign the questions may be too easy. He asked for **about 10 extra hard questions that need multi-step reasoning**, tags for easy/medium/hard, and a split between fact lookups and reasoning questions.

## Decision

1. **Corpus:** keep the GitLab HR handbook. Record the source URL and snapshot date, and treat the snapshot as frozen. Credit the source in the README and the UI under its licence (CC BY-SA 4.0; confirm on the handbook's licence page).
2. **Extraction check:** before indexing, compare a stratified sample of 20 of the 502 documents with the source (automatic number and date matching plus a manual read). Topics that fail are re-extracted with a deterministic parser based on the handbook's headings.
3. **Stable IDs:** derive every ID from the content path, never from file order: `doc_id` = topic slug, `section_id` = `doc_id#heading-slug`, `chunk_id` = `section_id~n`. Citations, recall@k and the golden set all join on `section_id`.
4. **Evaluation set v2** = the original 80 questions plus at least 10 hard questions. Each question carries `difficulty` (easy/medium/hard), `type` (fact / numeric / multi_step / conditional / follow_up / out_of_scope) and `gold_evidence_ids` (one or more section IDs). Every hard question cites at least two sections.
5. **Freeze:** commit `eval_v2.jsonl` with its sha256 hash and tag it `eval-v2`. Any later change creates v3. Results are always reported on **the original 80** (to compare with the baseline) **and on the full v2**.

## Alternatives considered

| Option | Why not |
|---|---|
| Indian company HR manuals | Licensing and compliance uncertainty, and the documents are too small |
| Keep the 80-question set unchanged | Likely too easy; the mentor asked for harder multi-step questions |
| Re-extract the whole handbook with a deterministic parser now | Costs a day; we only fall back to it where the sampled check fails |

## Consequences

- **Positive:** the corpus can be shared legally; evaluation is hard enough to separate single-agent from multi-agent results; IDs survive re-chunking.
- **Negative:** the corpus is US/global, not India-specific, so the report must state this scope. Writing and reviewing hard questions takes about half a day of two people's time.
- **Report:** a short section on how extraction was done and how its quality was checked (the mentor asked for this).

## Validation

- At most 5% of sampled sentences unmatched against the source.
- 100% of `gold_evidence_ids` resolve to a section in the index.
- Every hard question reviewed by two people.

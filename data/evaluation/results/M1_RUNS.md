# M1 on eval v2 (98 questions): three runs, one grader

All three runs are graded by judge v3 (frozen key facts, `eval_v2_keyfacts.json`), so differences come from the agent, not the grader.

| | Run 1 | Run 2 | Run 3 (current code) |
|---|---|---|---|
| What changed before the run | baseline | handbook scope in prompt; search nudge; conflicting-passages rule | out-of-scope fix to the nudge and prompt |
| Correct (judge v3) | 60.2% | 74.5% | **73.5%** |
| Correct or partially correct | 73.5% | 88.8% | **87.8%** |
| Correct by code-only checks | 50.0% | 60.2% | **61.2%** |
| Judge agrees with code-only checks | 71.4% | 73.5% | 77.6% |
| Right document retrieved | 72.8% | 88.0% | **87.0%** |
| In-scope questions answered without searching | 14 | 0 | 1 |
| Out-of-scope refused | 6/6 | 4/6 | 5/6 |
| Answers with citations | 69.4% | 85.7% | 83.7% |
| Answers with ungrounded numbers | 8.2% | 6.1% | 6.1% |
| Hard questions correct (12) | 41.7% | 41.7% | 33.3% |
| Model calls per question | 1.81 | 2.08 | 2.06 |
| Latency p50 / p95 | 4.6 / 7.8 s | 6.1 / 11.3 s | 5.2 / 9.3 s |
| Prompt + completion tokens per question | 2,750 + 140 | 3,403 + 165 | 3,388 + 157 |

## Reading it

- Run 1 → 2: forcing a search first removed all 14 skipped searches and lifted accuracy by 14 points.
- Run 2 → 3: the out-of-scope fix restored refusals (4/6 → 5/6). In-scope accuracy moved by about two questions (69 → 67 of 92), which is within run-to-run variation of the model; both runs use temperature 0.1 on a shared endpoint.
- Run 3 is the M1 result we report, because it matches the code as shipped.
- Remaining M1 failures (run 3): 12 reasoning errors (mostly multi-step), 8 retrieval misses (the gold document never reached the agent), 3 hallucinated numbers on calculation questions, 1 skipped search, 1 over-refusal, 1 under-refusal.

## Grader history (why the earlier headline numbers differ)

| Judge | Run 1 | Run 2 | Problem found |
|---|---|---|---|
| v1: single verdict | 72.4% | 53.1% | marked 12 wrong refusals correct; gave identical answers different grades |
| v2: judge extracts its own facts | 25.5% | 28.6% | took "facts" from the assistant's answer and penalised its extra detail |
| v3: frozen key facts | 60.2% | 74.5% | consistent; used for all reported numbers |

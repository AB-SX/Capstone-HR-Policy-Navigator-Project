# M1 against M2 on eval v2 (98 questions, judge v3)

M1 = run 3 (single tool-calling agent). M2 = run 1 (LangGraph: router, planner, executor, critic, responder). Same questions, same frozen key facts, same grader.

| | M1 | M2 | Difference |
|---|---|---|---|
| Correct | 73.5% | 72.4% | −1 question |
| Correct or partially correct | 87.8% | 82.7% | −5 |
| In-scope correct (92) | 67 | 65 | −2 |
| **Hard multi-step correct (12)** | **4 (33.3%)** | **7 (58.3%)** | **+3** |
| Out-of-scope refused (6) | 5 | **6** | +1 |
| Answers with ungrounded numbers | 6.1% | **2.0%** | 3× fewer |
| Answers with citations | 83.7% | 86.7% | +3 pts |
| Right document retrieved | 87.0% | 87.0% | same |
| Searches per question | 0.94 | 1.5 | planner and critic add searches |
| Model calls per question | 2.06 | 4.1 | ≈2× |
| Tokens per question (in + out) | 3,388 + 157 | 3,603 + 270 | +9% |
| Latency p50 / p95 | 5.2 / 9.3 s | 8.3 / 19.6 s | +60% / +110% |
| Task completion | 100% | 100% | same |

## Agreement between the two systems

| | M2 correct | M2 not correct |
|---|---|---|
| **M1 correct** | 60 | 12 |
| **M1 not correct** | 11 | 15 |

The 12 vs 11 split is close to even, so the overall accuracies are statistically the same (McNemar, p ≈ 1). The two systems fail on different questions: picking the better answer each time would reach 83 of 98. On the hard set M2 wins 4 to 1 among the questions only one of them gets right; that is a consistent direction but only 12 questions.

## Where M2 lost points

1. **Router misroutes (3 questions).** Q27 "ARAG Legal Insurance rates" and Q30 "Ireland's Bike to Work limits" were routed as out of scope (the word "legal", a country scheme); Q66 "how many days before relocation must I submit a Compass request" was routed to the ticket flow. All three never searched.
2. **The critic asks for more evidence too often.** It sent 35 of 89 policy questions back for another search. Extra passages sometimes bring in a near-miss document: Q2 mixed in "six months of service" from another policy, Q16 and Q40 contradicted facts they had right in M1. On those 35 questions M2 and M1 are level (23 vs 22 correct), so the second round helps the hard questions and hurts some easy ones.
3. **More cautious answers.** Q25 and Q35 said the handbook "does not specify" when it does (over-refusal 2).
4. **Code-only checks score M2 lower (49.0% vs 61.2%)** because its longer answers lower the word-overlap measure; the key-fact judge reads meaning, so we report it as the main metric.

## Where M2 gained

- Hard questions: the planner splits them into several searches and the calculator does the arithmetic (Q83, Q85, Q86, Q92 right only in M2).
- Out-of-scope: the router refuses all 6, including the one M1 answered.
- Grounding: one third of the ungrounded numbers, and slightly more answers with citations.

## Cost of M2's structure

About twice the model calls and 60% more median latency for the same overall accuracy, better hard-question accuracy and safer refusals. For an HR assistant where a wrong number or an answered off-topic question is worse than a slower reply, M2 is the better default; M1 stays useful as a fast baseline.

## Fixes this points to

- Router: say explicitly that benefit plans (including legal insurance) and country schemes are policy questions, and that "how do I submit a request" is a policy question, not a ticket.
- Critic: ask for more evidence only when a key part of the question has no supporting passage; cap extra passages so a second search can't push the original ones out.

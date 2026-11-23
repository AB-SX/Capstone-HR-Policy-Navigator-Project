# Approval sheet: ADR-001 to ADR-007

Mark each cell **A** (approve), **C** (approve with comments) or **R** (reject), and add comments below. An ADR becomes **Accepted** when every team member has marked A or C, and, for ADR-002 and ADR-004, the mentor has agreed.

| Reviewer | Role | 001 | 002 | 003 | 004 | 005 | 006 | 007 | Date |
|---|---|---|---|---|---|---|---|---|---|
| Shubhi Saxena | Team member | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ | |
| Abhishek Gupta | Team member | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ | |
| Rajat Mohanty | Team member | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ | |
| Raman Th | Team member | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ | |
| Suprateem Chakraborty | Team member | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ | |
| _(sixth team member)_ | Team member | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ | |
| Prof. Satyajit Das | Mentor | ☐ | **A** (18 Nov) | ☐ | ☐ | ☐ | ☐ | ☐ | |

## Questions for the mentor

1. ~~**ADR-002:** Is an external managed vector store (Pinecone) acceptable?~~ **Answered 18 Nov:** "Pinecone with fallback sounds good."
2. ~~**ADR-002:** Is a local cross-encoder reranker acceptable?~~ **Answered 18 Nov:** try bge-reranker-base and/or ms-marco-MiniLM-L6-v2; comparing both is welcome.
3. **ADR-004:** Do you agree with deterministic routing (always retrieve for policy questions) instead of prompt-only self-routing, given the Week 1 numeric-hallucination evidence? We will report both as an ablation.
4. **ADR-007 (optional):** Can you confirm the student AWS credits route? Otherwise we use the standard new-account credits.

## Comments

| ADR | Reviewer | Comment | Resolution |
|---|---|---|---|
| | | | |
| | | | |
| | | | |

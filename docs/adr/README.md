# HR Policy Navigator: Architecture Decision Records

**Project:** HR Policy Navigator (Executive PG Programme in Generative AI & Agentic AI, Capstone Track B)  
**Prepared by:** Shubhi Saxena · **Date:** 18 Nov 2026 · **Submission deadline:** 27 Nov 2026  
**Inputs:** HLD + LLD architecture doc (16 Nov), mentor review call with Prof. Satyajit Das (17 Nov), team discussions (18 Nov)  

This pack records the decisions we need before building past Week 1. Every ADR has the status **Proposed** until the team and the mentor sign the approval table at the end of this pack.

## Decision index

| ID | Decision | Owner (role) | Needs mentor input? |
|---|---|---|---|
| ADR-001 | Corpus is the GitLab HR handbook; the evaluation set moves to v2 (80 + ≥10 hard questions, tagged by difficulty and type) | Domain spec & eval design | No, this follows mentor guidance |
| ADR-002 | Retrieval stack: BM25 (local) + Pinecone (dense) + RRF + reranker (bge-reranker-base vs MiniLM-L6, compared), with FAISS as fallback | RAG / retrieval | **Accepted 18 Nov** (mentor email) |
| ADR-003 | Build M1 (single agent + one tool) before M2 (planner, executor, critic) | Agent orchestration & tools | No, this follows mentor guidance |
| ADR-004 | Policy questions always go through retrieval; direct answers only for greetings and meta questions | Agent orchestration & tools | **Yes:** this differs from the mentor's suggestion |
| ADR-005 | UI is a Streamlit chat app calling the agents in-process, with rate limit, cache and daily cap in a tested serving layer (revised 22 Nov) | Front-end & deployment | No |
| ADR-006 | Full chat history lives only in the user's browser; the server keeps redacted state for 24 h; PII is redacted and the user is warned | Observability & safety | No, this follows mentor guidance |
| ADR-007 | Deploy on AWS: one EC2 instance in Sydney, Docker Compose with Caddy for HTTPS, live for about 7 days (revised 22 Nov) | Front-end & deployment | No |

## How to use this pack

1. Each team member reads the ADRs for their area and comments by **Thu 19 Nov, 12:00 IST**.
2. Questions for the mentor: ADR-002 answered by email on 18 Nov (accepted); ADR-004 is still open. Raise it at the weekend call.
3. When an ADR is approved, change its status to **Accepted** and commit it to `docs/adr/` in the repo.
4. To change an accepted ADR, write a new ADR that supersedes it. Never edit an accepted one.

## Status values

**Proposed** → **Accepted** | **Rejected** → (later) **Superseded by ADR-xxx**

# ADR-005: UI is a Streamlit chat app that calls the agents in-process

| | |
|---|---|
| **Status** | Proposed (revised 22 Nov: Streamlit replaces the React plan) |
| **Date** | 18 Nov 2026, revised 22 Nov 2026 |
| **Owner (role)** | Front-end & deployment |
| **Affects** | LLD 11 (UI), ADR-006 (history), ADR-007 (deployment) |

## Context

- The brief requires a Streamlit or React front end, containerised, with rate limiting and caching.
- On 22 Nov, with five days to submission, the remaining work is evaluation, responsible-AI tests, deployment and the report. The UI has to be the smallest piece that does the job well.
- The UI must show: answers with citation tags, the cited document and page with an excerpt, a PII warning, Confirm and Cancel for the HR-ticket step (M2), a switch between M1 and M2 for demos, and an access-code gate for the public URL.
- The repo already had a Streamlit prototype (`src/app/ui.py`) built on the Week 2 pipeline.

## Decision

1. **Streamlit** app `src/app/navigator.py`. It calls M1 and M2 directly in the same Python process; there is no separate API service.
2. A thin serving layer `src/app/service.py` holds what the brief asks for and is unit-tested with the fake LLM:
    - rate limit per client (10 questions a minute, sliding window);
    - answer cache (24 h) for first questions in a conversation only, so follow-ups always use their history; a cached M2 answer is still written into the conversation's checkpoint;
    - daily cap on model calls (3,000);
    - one agent turn at a time, matching the endpoint's one-request limit, with a 90-second queue wait;
    - a usage log with status, latency, model calls and tokens, and no question text.
3. Chat history is kept in the Streamlit session (this browser tab); **New conversation** clears it. M2 also checkpoints each conversation server-side for 24 h (ADR-006).
4. Citations render as tags (C1, C2…) with a **Sources** panel listing document, page and an excerpt. A "Show how it answered" toggle shows route, tools, plan, critic verdict, model calls and time.

## Employee MVP (24 Nov)

What employees see, and what was removed from the team/demo view:

| Removed for employees | Replaced by |
|---|---|
| M1/M2 switch | M2 for everyone (`HRNAV_SYSTEM`); the switch stays behind `HRNAV_DEV_MODE=1` |
| "How it answered" (route, plan, critic, model calls, cache) | Nothing; developer mode only |
| Internal IDs (`doc_019`, `C3`, `DRAFT-…`) | Numbered citations 1, 2 … with "GitLab team handbook, page 55 · section"; ticket reference `HR-…` |
| Raw status messages | Plain messages for busy, rate limit, daily limit and errors |
| Streamlit developer menu | Minimal toolbar |

Added: quick-start questions by topic; thumbs up/down with an optional comment; a request card with Submit to HR / Cancel; chat history saved **only in the browser** (localStorage via `streamlit-js-eval`) with "Clear chats on this device"; an about-and-privacy note; a code-protected admin page at `?admin=1` with two sections: Usage (questions per day, outcomes, median time, cache share, thumbs-up rate, thumbs-down comments) and HR requests (the same review workflow as `?hr=1`). All pages share a chat-app look: grey sidebar, centred greeting with topic cards, right-hand user bubbles, one icon family and an "HR" monogram.

Data kept on the server: the current conversation's PII-redacted state for follow-ups (deleted on New conversation or Clear, or after 24 h idle), a usage log without question text, and feedback without chat text.

HR request workflow: every confirmed request lands in an append-only log; HR reviewers use a code-protected page at `?hr=1` to list requests, filter by status and move each one through Submitted → In progress → Resolved / Closed with a note; employees check status by reference under "Check a request". Full history is kept for audit (`src/app/tickets.py`).

Not in the MVP: single sign-on, streaming answers, other languages, a real HR ticketing integration.

## Alternatives considered

| Option | Pros | Cons | Verdict |
|---|---|---|---|
| **Streamlit, in-process** | All Python; fastest to build and change; one container; allowed by the brief | Server-side session state; less control over styling | **Chosen** |
| React (Vite) + FastAPI | Full control of the UI; browser-only history in `localStorage` | A second language and build step; an API layer to write and secure; about a day more work | Rejected for time |
| Streamlit + separate FastAPI | Clean API for other clients | Two services and more moving parts for no user-visible gain in a demo | Rejected |
| Chainlit | Chat UI out of the box | Another framework; not named in the brief | Rejected |

## Consequences

- **Positive:** one language, one container, one port; the serving rules live in a tested module rather than in UI code.
- **Negative:** history is per browser tab rather than persisted in `localStorage`; Streamlit uses WebSockets, so the reverse proxy must pass them (Caddy does by default).

## Validation

- Driven end to end with a fake LLM in a headless browser (22 Nov): starter question, sources panel, ticket draft, Confirm, submitted, no exceptions.
- `tests/test_service.py`: rate limit, cache hits, M2 memory after a cache hit, daily cap, ticket confirmation.

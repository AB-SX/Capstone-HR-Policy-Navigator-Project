# ADR-006: Chat history in the browser, 24 h server state, PII redaction and warning

| | |
|---|---|
| **Status** | Proposed |
| **Date** | 18 Nov 2026 |
| **Owner (role)** | Observability & safety |
| **Affects** | LLD 8 (memory), LLD 12 (safety tests), HLD 7 (Responsible AI), ADR-005 |

## Context

- The mentor suggested storing chat history **locally in the browser**, so a user's data stays with them and they can delete it.
- The LangGraph agent still needs **per-thread state on the server** to resolve follow-up questions and to pause and resume at the human confirmation step (M2). That uses the SQLite checkpointer from LLD 8.
- On PII the mentor agreed we should (a) tell the model to ignore user-specific personal details and (b) **warn the user** when they paste sensitive data such as a password.
- The app will be on a public URL for about a week (ADR-007), so whatever we store on the server becomes a liability.

## Decision

| Data | Where | Content | Lifetime |
|---|---|---|---|
| Full chat history (for display) | Browser `localStorage`, key `hrnav.history.v1` | Messages as the user sees them | Until the user clicks **Clear history** |
| Thread ID | Browser, generated client-side (UUID v4) | Random ID only | Same as history |
| Agent state (checkpointer) | Server, SQLite on a mounted volume | **Redacted** last 6 messages, rolling summary, slots | **24 h**: an hourly cleanup job deletes older threads |
| Traces (LangSmith) | LangSmith | **Redacted** prompts and outputs | LangSmith project retention; dev and prod in separate projects |
| Application logs | Container logs | Request ID, route, latency, error codes. **No message text.** | Rotated: 10 MB × 3 files |

**PII handling:**

1. The **input guard** finds Indian and generic PII (PAN, Aadhaar-like 12-digit numbers, phone, email, card-like 16-digit numbers, password and OTP phrases) with regex and checksums, and replaces each match with a typed placeholder **before** the text is logged, traced, cached or sent to the model.
2. When anything is redacted, the reply starts with a short warning: *"It looks like you shared personal information (e.g. a PAN). I removed it and didn't use it. Please don't share passwords or IDs here."*
3. The system prompt tells the model to ignore any personal details and answer only from policy text.
4. The **output guard** scans the answer again before returning it.
5. The cache (ADR-004) stores only redacted, first-turn questions.

## Alternatives considered

| Option | Why not |
|---|---|
| Server-side history (database) | Against the mentor's privacy suggestion; more data to protect |
| Stateless server (the browser sends the whole history every turn) | Breaks pausing and resuming at the human confirmation step; larger payloads; the client could tamper with state |
| No PII warning, silent redaction only | The user never learns they over-shared; the mentor agreed the warning adds value |

## Consequences

- **Positive:** a clear Responsible AI story (data minimisation, retention under 24 h, user-controlled deletion); the redacted state still supports follow-ups and the human confirmation step.
- **Negative:** history doesn't sync across devices; a thread older than 24 h loses server context (the UI says "starting a fresh session").

## Validation

- PII test suite (LLD 12): at least 30 cases, with 100% redaction of PAN, card and password phrases before the model call (checked in LangSmith traces).
- After "Clear history", `localStorage` is empty.
- A thread older than 24 h is absent from `checkpoints.db`.

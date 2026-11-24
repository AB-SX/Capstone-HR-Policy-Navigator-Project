"""HR request log and review workflow (stand-in for a real HR case system).

Two append-only files in the runtime volume:
    tickets.jsonl          one line per request the employee confirmed (written by the M2 graph)
    ticket_events.jsonl    one line per status change made by an HR reviewer

Current state = the submission plus its latest status event. Nothing is overwritten, so the full history of every
request is kept for audit.
"""
from __future__ import annotations

import json
import threading
import time

from src import config

STATUSES = ["submitted", "in_progress", "resolved", "closed"]
CATEGORIES = ["leave", "benefits", "payroll", "expenses", "equipment", "policy_question", "other"]
LABELS = {"submitted": "Submitted", "in_progress": "In progress", "resolved": "Resolved", "closed": "Closed"}
_lock = threading.Lock()


def _read(path):
    try:
        with open(path, encoding="utf-8") as f:
            return [json.loads(x) for x in f if x.strip()]
    except (OSError, ValueError):
        return []


def _paths():
    return config.RUNTIME_DIR / "tickets.jsonl", config.RUNTIME_DIR / "ticket_events.jsonl"


def all_tickets() -> list[dict]:
    """Every submitted request with its current status and history, newest first."""
    subs, events = (_read(p) for p in _paths())
    by_id: dict[str, dict] = {}
    for t in subs:
        tid = t.get("ticket_id")
        if not tid:
            continue
        by_id[tid] = {**t, "status": "submitted", "updated": t.get("submitted") or t.get("created", ""), "note": "",
                      "reviewer": "", "history": [{"ts": t.get("submitted") or t.get("created", ""),
                                                   "status": "submitted", "by": "employee", "note": ""}]}
    for e in events:
        t = by_id.get(e.get("ticket_id"))
        if not t or e.get("status") not in STATUSES:
            continue
        t.update(status=e["status"], updated=e["ts"], note=e.get("note", ""), reviewer=e.get("by", ""))
        t["history"].append({k: e.get(k, "") for k in ("ts", "status", "by", "note")})
    return sorted(by_id.values(), key=lambda t: t.get("submitted") or t.get("created", ""), reverse=True)


def get(ticket_id: str) -> dict | None:
    tid = (ticket_id or "").strip().upper()
    return next((t for t in all_tickets() if t["ticket_id"] == tid), None)


def clean_fields(category: str, summary: str, details: str) -> dict:
    """Validate what an employee typed and remove personal details before anything is stored."""
    from src.guards.pii import redact
    category = category if category in CATEGORIES else "other"
    summary = redact((summary or "").strip())[0][:150]
    details = redact((details or "").strip())[0][:1500]
    if len(summary) < 5:
        raise ValueError("Please add a short summary (at least 5 characters).")
    return {"category": category, "summary": summary, "details": details}


def submit(category: str, summary: str, details: str) -> dict:
    """An employee files a request directly from the form (no assistant involved)."""
    import uuid
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    t = {"ticket_id": "HR-" + uuid.uuid4().hex[:8].upper(), "status": "submitted",
         **clean_fields(category, summary, details), "created": now, "submitted": now, "source": "form"}
    with _lock, open(_paths()[0], "a", encoding="utf-8") as f:
        f.write(json.dumps(t) + "\n")
    return t


def update(ticket_id: str, status: str, note: str = "", by: str = "") -> dict:
    """Record a reviewer's status change. Raises ValueError for an unknown request or status."""
    if status not in STATUSES:
        raise ValueError(f"unknown status {status!r}")
    if not get(ticket_id):
        raise ValueError(f"unknown request {ticket_id!r}")
    ev = {"ticket_id": ticket_id.strip().upper(), "status": status, "note": (note or "").strip()[:1000],
          "by": (by or "").strip()[:80], "ts": time.strftime("%Y-%m-%d %H:%M:%S")}
    with _lock, open(_paths()[1], "a", encoding="utf-8") as f:
        f.write(json.dumps(ev) + "\n")
    return get(ticket_id)


def employee_view(ticket_id: str) -> dict | None:
    """What an employee sees for their own reference: status, last update and the reviewer's note only."""
    t = get(ticket_id)
    if not t:
        return None
    return {"ticket_id": t["ticket_id"], "status": LABELS[t["status"]], "updated": t["updated"],
            "summary": t.get("summary", ""), "note": t.get("note", "")}

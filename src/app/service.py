"""Serving layer for the Streamlit app: rate limiting, answer cache, daily model-call cap, one turn at a time.

Kept separate from the UI so it can be unit-tested with the fake LLM (tests/test_service.py).
Everything lives in one process (one container), so plain in-memory structures are enough (ADR-007).
"""
from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from collections import defaultdict, deque

from src import config

CACHEABLE = {"answered", "not_covered", "refused", "chitchat"}


class RateLimiter:
    """Sliding window: at most `limit` questions per `window_s` per client."""

    def __init__(self, limit: int, window_s: float = 60.0):
        self.limit, self.window = limit, window_s
        self.hits: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str, now: float | None = None) -> float:
        """0 if allowed (and counted), else seconds to wait."""
        now = time.time() if now is None else now
        with self._lock:
            q = self.hits[key]
            while q and now - q[0] >= self.window:
                q.popleft()
            if len(q) >= self.limit:
                return round(self.window - (now - q[0]), 1)
            q.append(now)
            return 0.0


class TTLCache:
    def __init__(self, ttl_s: float, max_items: int = 500):
        self.ttl, self.max = ttl_s, max_items
        self.data: dict[str, tuple[float, dict]] = {}
        self._lock = threading.Lock()

    def get(self, key):
        with self._lock:
            hit = self.data.get(key)
            if not hit or time.time() - hit[0] > self.ttl:
                self.data.pop(key, None)
                return None
            return hit[1]

    def put(self, key, value):
        with self._lock:
            if len(self.data) >= self.max:
                self.data.pop(min(self.data, key=lambda k: self.data[k][0]))
            self.data[key] = (time.time(), value)


def normalise(q: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", (q or "").lower())).strip()


class Service:
    def __init__(self):
        self.limiter = RateLimiter(int(config.setting("api.rate_limit_per_minute", 10)))
        self.cache = TTLCache(float(config.setting("api.cache_ttl_s", 86400)))
        self.daily_cap = int(config.setting("api.daily_llm_call_cap", 3000))
        self.turn_lock = threading.Lock()          # the endpoint serves one request at a time anyway
        self.day, self.day_calls = time.strftime("%Y-%m-%d"), 0
        self.log_path = config.RUNTIME_DIR / "app_log.jsonl"
        self.feedback_path = config.RUNTIME_DIR / "feedback.jsonl"
        self.ttl_s = float(config.setting("api.thread_ttl_hours", 24)) * 3600
        self._last_purge = 0.0

    # ------------------------------------------------------------------ helpers
    def _cap_left(self) -> int:
        today = time.strftime("%Y-%m-%d")
        if today != self.day:
            self.day, self.day_calls = today, 0
        return self.daily_cap - self.day_calls

    def _log(self, out: dict, system: str):
        rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "system": system, "status": out.get("status"),
               "cached": out.get("cached", False), "latency_s": out.get("latency_s"),
               "llm_calls": out.get("usage", {}).get("llm_calls", 0),
               "prompt_tokens": out.get("usage", {}).get("prompt_tokens", 0)}   # no question text: PII stays out of logs
        try:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec) + "\n")
        except OSError:
            pass

    @staticmethod
    def _sources(result) -> list[dict]:
        from src.retrieval.policy_search import get_engine
        lookup = getattr(get_engine(), "lookup", {})
        out = []
        for c in result.citations:
            text = (lookup.get(c["chunk_id"]) or {}).get("text", "")
            head, _, body = text.partition(": ")
            title = head.strip() if body and 0 < len(head) <= 80 else ""      # C3 chunks are "heading: body"
            body = body if title else text
            out.append({"tag": c["tag"], "doc_id": c["doc_id"], "pages": c["pages"], "title": title,
                        "excerpt": (body[:320] + "…") if len(body) > 320 else body})
        return out

    def _pack(self, r, system, thread_id) -> dict:
        return {"answer": r.answer, "status": r.status, "route": r.route, "system": system, "thread_id": thread_id,
                "sources": self._sources(r), "pending_ticket": r.pending_ticket, "usage": r.usage,
                "latency_s": r.latency_s, "tools": [t["name"] for t in r.tool_calls],
                "plan": [s.get("query") or s.get("expression") for s in (r.plan or [])],
                "critic": [c.get("verdict") for c in (r.critic or [])], "pii": r.pii_categories,
                "injection": r.injection_flag, "degraded": r.degraded_retrieval, "cached": False}

    @staticmethod
    def _m2_has_history(thread_id: str) -> bool:
        from src.agents.graph import get_graph
        st = get_graph().get_state({"configurable": {"thread_id": thread_id}})
        return bool((st.values or {}).get("history"))

    @staticmethod
    def _m2_remember(thread_id: str, question: str, answer: str):
        """A cached answer still becomes part of the conversation, so follow-ups keep their context."""
        from src.agents.graph import get_graph
        get_graph().update_state({"configurable": {"thread_id": thread_id}},
                                 {"history": [{"role": "user", "content": question},
                                              {"role": "assistant", "content": answer}]}, as_node="finalize")

    def _busy(self, msg="The assistant is busy with another question. Please try again in a minute."):
        return {"answer": msg, "status": "busy", "sources": [], "usage": {}, "cached": False}

    # ------------------------------------------------------------------ conversation state (server side)
    @staticmethod
    def _saver():
        from src.agents.graph import get_graph
        return get_graph().checkpointer

    def forget(self, thread_id: str):
        """Delete a conversation's server-side state now ("New conversation" / "Clear chats")."""
        try:
            fn = getattr(self._saver(), "delete_thread", None)
            if fn and thread_id:
                fn(thread_id)
        except Exception:
            pass

    def purge_expired(self, force: bool = False) -> int:
        """Delete M2 conversation state idle for longer than api.thread_ttl_hours (default 24 h). Runs hourly."""
        now = time.time()
        if not force and now - self._last_purge < 3600:
            return 0
        self._last_purge = now
        try:
            from datetime import datetime
            last: dict[str, float] = {}
            for t in self._saver().list(None):
                tid = t.config["configurable"]["thread_id"]
                ts = datetime.fromisoformat(str(t.checkpoint["ts"]).replace("Z", "+00:00")).timestamp()
                last[tid] = max(ts, last.get(tid, 0.0))
            old = [tid for tid, ts in last.items() if now - ts > self.ttl_s]
            for tid in old:
                self.forget(tid)
            return len(old)
        except Exception:
            return 0

    def seed(self, thread_id: str, messages: list[dict]):
        """Reopening a chat saved in the browser: give M2 the last turns again so follow-ups keep context."""
        hist = [{"role": m["role"], "content": (m.get("content") or "")[:1500]} for m in messages
                if m.get("role") in ("user", "assistant") and m.get("content")][-12:]
        if not hist:
            return
        try:
            from src.agents.graph import get_graph
            get_graph().update_state({"configurable": {"thread_id": thread_id}}, {"history": hist}, as_node="finalize")
        except Exception:
            pass

    # ------------------------------------------------------------------ feedback and usage
    def feedback(self, rating: int, comment: str, meta: dict):
        """Thumbs up/down. No question or answer text is stored; an optional comment is PII-redacted."""
        from src.guards.pii import redact
        rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "rating": int(rating),
               "comment": redact((comment or "").strip()[:500])[0],
               **{k: meta.get(k) for k in ("system", "status", "route", "cached", "latency_s", "n_sources")}}
        with open(self.feedback_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")

    def usage_rows(self):
        def read(p):
            try:
                return [json.loads(x) for x in open(p, encoding="utf-8") if x.strip()]
            except OSError:
                return []
        return read(self.log_path), read(self.feedback_path)

    # ------------------------------------------------------------------ public
    def ask(self, question: str, system: str, thread_id: str, history: list | None, client: str) -> dict:
        self.purge_expired()
        question = (question or "").strip()[:2000]
        if not question:
            return {"answer": "Please type a question.", "status": "empty", "sources": [], "usage": {}}
        wait = self.limiter.check(client)
        if wait:
            return {"answer": f"You've reached the limit of {self.limiter.limit} questions a minute. "
                              f"Try again in {int(wait) + 1} seconds.", "status": "rate_limited", "sources": [], "usage": {}}
        if self._cap_left() <= 0:
            return {"answer": "Today's question allowance for this demo is used up. Please try again tomorrow.",
                    "status": "daily_cap", "sources": [], "usage": {}}

        fresh = not history if system == "m1" else not self._m2_has_history(thread_id)
        key = hashlib.sha256(f"{system}|{normalise(question)}".encode()).hexdigest()
        if fresh:
            hit = self.cache.get(key)
            if hit:
                out = {**hit, "cached": True, "latency_s": 0.0, "thread_id": thread_id, "usage": {"llm_calls": 0}}
                if system == "m2":
                    self._m2_remember(thread_id, question, out["answer"])
                self._log(out, system)
                return out

        if not self.turn_lock.acquire(timeout=float(config.setting("api.queue_wait_s", 90))):
            return self._busy()
        try:
            if system == "m1":
                from src.agents.single_agent import run_m1
                r = run_m1(question, history=history)
            else:
                from src.agents.graph import run_m2
                r = run_m2(question, thread_id=thread_id)
        finally:
            self.turn_lock.release()
        self.day_calls += int(r.usage.get("llm_calls", 0))
        out = self._pack(r, system, thread_id)
        if fresh and r.status in CACHEABLE and not r.pii_categories and not r.injection_flag:
            self.cache.put(key, {k: v for k, v in out.items() if k not in ("thread_id",)})
        self._log(out, system)
        return out

    def confirm(self, thread_id: str, yes: bool, client: str, edits: dict | None = None) -> dict:
        if not self.turn_lock.acquire(timeout=float(config.setting("api.queue_wait_s", 90))):
            return self._busy()
        try:
            from src.agents.graph import resume_m2
            r = resume_m2(thread_id, yes, edits)
        finally:
            self.turn_lock.release()
        out = self._pack(r, "m2", thread_id)
        self._log(out, "m2")
        return out


_service: Service | None = None


def get_service() -> Service:
    global _service
    if _service is None:
        _service = Service()
    return _service

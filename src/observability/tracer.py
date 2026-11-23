"""Span-level tracer for real executions (brief V: tracing + observability).

Records one trace per question with nested spans for every LangGraph node, every model call and every tool
call, then writes them as JSON lines the trace dashboard (dashboard/) reads. Works next to LangSmith: if
LANGSMITH_TRACING is on, the same runs also go to LangSmith.

    from src.observability import tracer
    tracer.install()                       # patch graph nodes, tools and the LLM client once
    with tracer.trace(question, system="m2", meta={...}) as t:
        result = run_m2(question)
    t.finish(result)                       # attaches answer, status, usage
    tracer.write(t, path)

Nothing here changes agent behaviour; wrappers only time calls and copy small previews of inputs/outputs.
"""
from __future__ import annotations

import contextvars
import functools
import json
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

PREVIEW = 600                                   # chars kept per input/output preview

_current: contextvars.ContextVar["Trace | None"] = contextvars.ContextVar("hrnav_trace", default=None)
_parent: contextvars.ContextVar[str | None] = contextvars.ContextVar("hrnav_span_parent", default=None)
_installed = False


def _short(x, n=PREVIEW):
    if x is None:
        return None
    if not isinstance(x, str):
        try:
            x = json.dumps(x, default=str, ensure_ascii=False)
        except Exception:
            x = str(x)
    return x if len(x) <= n else x[:n] + "…"


class Trace:
    def __init__(self, question, system, meta=None):
        self.id = uuid.uuid4().hex[:16]
        self.question = question
        self.system = system
        self.meta = meta or {}
        self.t0 = time.perf_counter()
        self.started_at = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        self.spans: list[dict] = []
        self.result: dict = {}

    def now_ms(self):
        return round((time.perf_counter() - self.t0) * 1000, 1)

    def finish(self, result):
        d = result.to_dict() if hasattr(result, "to_dict") else dict(result)
        self.result = {"answer": d.get("answer", ""), "status": d.get("status"), "route": d.get("route"),
                       "latency_s": d.get("latency_s"), "usage": d.get("usage", {}),
                       "tool_calls": d.get("tool_calls", []), "plan": d.get("plan", []),
                       "critic": d.get("critic", []), "citations": d.get("citations", []),
                       "guard": {k: d.get("guard", {}).get(k) for k in
                                 ("has_citation", "invalid_citations", "ungrounded_numbers")},
                       "degraded_retrieval": d.get("degraded_retrieval"), "error": d.get("error", "")}

    def to_dict(self):
        return {"trace_id": self.id, "system": self.system, "question": self.question, "started_at": self.started_at,
                "duration_ms": self.now_ms() if not self.spans else max(s["end_ms"] for s in self.spans),
                "meta": self.meta, "result": self.result, "spans": self.spans}


@contextmanager
def trace(question, system, meta=None):
    t = Trace(question, system, meta)
    tok = _current.set(t)
    ptok = _parent.set(None)
    try:
        yield t
    finally:
        _parent.reset(ptok)
        _current.reset(tok)


@contextmanager
def span(name, kind, inputs=None):
    t = _current.get()
    if t is None:                                # tracing not active: no-op
        yield {}
        return
    sid = uuid.uuid4().hex[:12]
    s = {"span_id": sid, "parent_id": _parent.get(), "name": name, "kind": kind, "start_ms": t.now_ms(),
         "end_ms": None, "ok": True, "error": None, "input": _short(inputs), "output": None, "attrs": {}}
    t.spans.append(s)
    tok = _parent.set(sid)
    try:
        yield s
    except Exception as ex:
        s["ok"], s["error"] = False, f"{type(ex).__name__}: {ex}"[:300]
        raise
    finally:
        _parent.reset(tok)
        s["end_ms"] = t.now_ms()
        s["dur_ms"] = round(s["end_ms"] - s["start_ms"], 1)


def _usage_snapshot():
    from src.llm import client
    u = client._usage.get()
    return (u.prompt_tokens, u.completion_tokens, u.json_repairs) if u else (0, 0, 0)


# ----------------------------------------------------------------- wrappers
def _wrap_node(name, fn):
    @functools.wraps(fn)
    def inner(state, *a, **k):
        with span(name, "node", {k2: state.get(k2) for k2 in ("raw_question", "standalone", "route", "next_step")
                                 if isinstance(state, dict) and state.get(k2) is not None}) as s:
            out = fn(state, *a, **k)
            if isinstance(out, dict):
                s["output"] = _short({k2: out[k2] for k2 in ("route", "plan", "status", "answer", "critic_log",
                                                             "next_step", "error") if k2 in out})
            return out
    inner.__hrnav_traced__ = True
    return inner


def _wrap_tool(fn):
    @functools.wraps(fn)
    def inner(name, raw_args, ctx, *a, **k):
        with span(f"tool:{name}", "tool", raw_args) as s:
            r = fn(name, raw_args, ctx, *a, **k)
            if isinstance(r, dict):
                s["ok"] = bool(r.get("ok", True))
                if not s["ok"]:
                    s["error"] = r.get("error_code") or r.get("message")
                d = r.get("data") if isinstance(r.get("data"), dict) else {}
                s["attrs"] = {"error_code": r.get("error_code"), "n_chunks": len(d.get("chunks") or []),
                              "retrieval_status": d.get("status"), "degraded": d.get("degraded"),
                              "doc_ids": [c.get("doc_id") for c in (d.get("chunks") or [])][:8] or None}
                s["output"] = _short(r.get("text") or r.get("message") or r)
            return r
    inner.__hrnav_traced__ = True
    return inner


def _wrap_llm_method(meth, kind):
    @functools.wraps(meth)
    def inner(self, messages, *a, **k):
        label = k.get("name", kind)
        before = _usage_snapshot()
        with span(f"llm:{label}", "llm", messages[-1].get("content") if messages else None) as s:
            out = meth(self, messages, *a, **k)
            after = _usage_snapshot()
            s["attrs"] = {"model": getattr(self, "model", "fake"), "call": kind,
                          "prompt_tokens": after[0] - before[0], "completion_tokens": after[1] - before[1],
                          "json_repairs": after[2] - before[2]}
            if isinstance(out, dict):
                s["attrs"]["finish_reason"] = out.get("finish_reason")
                s["attrs"]["tool_calls"] = len(out.get("tool_calls") or [])
                s["output"] = _short(out.get("text"))
            else:
                s["output"] = _short(out.model_dump() if hasattr(out, "model_dump") else out)
            return out
    inner.__hrnav_traced__ = True
    return inner


NODES = ("guard_in", "router", "planner", "executor", "critic", "responder", "chitchat", "out_of_scope",
         "draft_ticket", "confirm_ticket", "finalize")


def install(llm_classes=()):
    """Patch once. llm_classes: extra client classes (e.g. the test FakeLLM) to instrument."""
    global _installed
    if _installed:
        return
    from src.agents import graph, single_agent
    from src.llm.client import LLMClient
    for n in NODES:
        fn = getattr(graph, n)
        if not getattr(fn, "__hrnav_traced__", False):
            setattr(graph, n, _wrap_node(n, fn))
    graph._graph = None                          # rebuild with wrapped nodes
    for mod in (graph, single_agent):
        if not getattr(mod.run_tool, "__hrnav_traced__", False):
            mod.run_tool = _wrap_tool(mod.run_tool)
    for cls in (LLMClient, *llm_classes):
        # chat_json calls chat internally on the real client, so wrap chat_json as the parent span
        for m, kind in (("chat", "chat"), ("chat_json", "json")):
            f = getattr(cls, m, None)
            if f and not getattr(f, "__hrnav_traced__", False):
                setattr(cls, m, _wrap_llm_method(f, kind))
    _installed = True


def write(t: Trace, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(t.to_dict(), ensure_ascii=False, default=str) + "\n")

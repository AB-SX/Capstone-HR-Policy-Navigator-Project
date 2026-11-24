"""M2: LangGraph multi-agent workflow (brief IV: explicit planner -> executor -> critic loop).

    guard_in -> router -┬- chitchat ---------------------------------------------┐
                        ├- out_of_scope ------------------------------------------┤
                        ├- ticket -> draft_ticket -> confirm_ticket [interrupt] ---┤
                        └- policy -> planner -> executor -> critic ─┬─ responder --┴-> finalize
                                                  ^                 │
                                                  └── need_more ────┘  (max_critic_rounds)

Persistent state across turns: SQLite checkpointer keyed by thread_id (history, pending ticket).
Error handling: tool errors are data; JSON via constrained decoding + validation + repair;
loop caps (max_steps, max_critic_rounds, recursion_limit); token budget on context; LLM outage -> safe reply.
Human-in-the-loop boundary: an HR ticket is only drafted; submitting requires explicit user confirmation.
"""
from __future__ import annotations

import json
import re
import sqlite3
import time
import uuid
from typing import Any, Literal, TypedDict

from pydantic import BaseModel, Field

from src import config
from src.agents import prompts
from src.agents.result import AgentResult
from src.agents.tools import TOOLS, TicketArgs, openai_tool_specs, run_tool
from src.guards import injection, output_guard, pii
from src.llm.client import LLMError, estimate_tokens, get_llm, track_usage


# ----------------------------------------------------------------- structured outputs
class RouteDecision(BaseModel):
    route: Literal["policy", "chitchat", "ticket", "out_of_scope"]
    standalone_question: str = Field(..., max_length=400)
    reason: str = Field("", max_length=200)


class PlanStep(BaseModel):
    tool: Literal["search_hr_policy", "calculate"]
    intent: str = Field(..., max_length=200)
    query: str = Field("", max_length=300)
    expression: str = Field("", max_length=200)


class Plan(BaseModel):
    steps: list[PlanStep] = Field(..., min_length=1, max_length=4)


class CriticVerdict(BaseModel):
    verdict: Literal["sufficient", "need_more", "not_covered"]
    missing: str = Field("", max_length=300)
    new_query: str = Field("", max_length=300)


class NavState(TypedDict, total=False):
    # persistent across turns (thread)
    history: list[dict]
    pending_ticket: dict | None
    # per turn
    raw_question: str
    question: str
    standalone: str
    pii: list[str]
    injection: bool
    route: str
    plan: list[dict]
    next_step: int
    chunks: list[dict]
    calculations: list[dict]
    tool_log: list[dict]
    critic_log: list[dict]
    critic_rounds: int
    answer: str
    status: str
    guard: dict
    error: str
    degraded: bool


_GREETING = re.compile(r"(?i)^\s*(hi|hello|hey|thanks|thank you|good (morning|afternoon|evening)|what can you do)\b[\s!.?]*$")
_TICKET = re.compile(r"(?i)\b(raise|file|submit|create|open|log)\b.{0,30}\b(ticket|request|case)\b")


def _ctx_text(chunks, budget):
    """Passages for prompts, best first, within a token budget (dedup by chunk_id)."""
    seen, out, used = set(), [], 0
    for c in sorted(chunks, key=lambda c: -c.get("score", 0)):
        if c["chunk_id"] in seen:
            continue
        t = f"[{c['tag']}] ({c['doc_id']}, p. {', '.join(map(str, c['pages']))})\n{injection.sanitize_passage(c['text'])}"
        n = estimate_tokens(t)
        if out and used + n > budget:
            continue
        seen.add(c["chunk_id"])
        out.append(t)
        used += n
    return "<policy_passages>\n" + "\n\n".join(out) + "\n</policy_passages>" if out else "<policy_passages>\n(none)\n</policy_passages>"


def _calc_text(calcs):
    return "\n".join(f"- {c['purpose'] or 'calculation'}: {c['expression']} = {c['result']}" for c in calcs or [])


def _hist(state, n=None):
    n = n or int(config.setting("agent.history_turns", 6))
    return (state.get("history") or [])[-n:]


# ----------------------------------------------------------------- nodes
def guard_in(state: NavState) -> NavState:
    q, found = pii.redact(state.get("raw_question", ""))
    return {"question": q, "pii": found, "injection": injection.detect(q), "plan": [], "next_step": 0, "chunks": [],
            "calculations": [], "tool_log": [], "critic_log": [], "critic_rounds": 0, "answer": "", "status": "",
            "guard": {}, "error": "", "degraded": False, "standalone": q, "route": ""}


def router(state: NavState) -> NavState:
    q = state["question"]
    if _GREETING.match(q):
        return {"route": "chitchat"}
    if state.get("pending_ticket") and re.match(r"(?i)^\s*(yes|confirm|submit|no|cancel)\b", q):
        return {"route": "ticket"}
    hist = "\n".join(f"{m['role']}: {m['content'][:300]}" for m in _hist(state, 4))
    try:
        d = get_llm().chat_json([{"role": "system", "content": prompts.ROUTER_SYSTEM},
                                 {"role": "user", "content": f"Conversation so far:\n{hist or '(none)'}\n\nLatest message: {q}"}],
                                RouteDecision, name="router", max_tokens=200)
        route = d.route
        if route == "chitchat" and not _GREETING.match(q) and len(q.split()) > 6:
            route = "policy"                              # ADR-004: when in doubt, retrieve
        if _TICKET.search(q):
            route = "ticket"
        return {"route": route, "standalone": d.standalone_question or q}
    except LLMError as ex:
        return {"route": "policy", "standalone": q, "error": f"router: {ex}"[:200]}


def planner(state: NavState) -> NavState:
    q = state["standalone"]
    try:
        p = get_llm().chat_json([{"role": "system", "content": prompts.PLANNER_SYSTEM},
                                 {"role": "user", "content": f"Question: {q}"}], Plan, name="planner", max_tokens=400)
        steps = [s.model_dump() for s in p.steps]
    except LLMError as ex:
        steps = [{"tool": "search_hr_policy", "intent": "find the policy", "query": q, "expression": ""}]
        return {"plan": steps, "next_step": 0, "error": f"planner fallback: {ex}"[:200]}
    for s in steps:                                       # a search step with an empty query searches the question
        if s["tool"] == "search_hr_policy" and len(s["query"].strip()) < 3:
            s["query"] = q
    if not any(s["tool"] == "search_hr_policy" for s in steps):
        steps.insert(0, {"tool": "search_hr_policy", "intent": "find the policy", "query": q, "expression": ""})
    return {"plan": steps[:4], "next_step": 0}


def executor(state: NavState) -> NavState:
    """Runs the remaining plan steps. Searches run directly; calculations ask the LLM (native tool call)
    to fill in numbers from the evidence, because the planner wrote them before the numbers were known."""
    ctx = {"chunks": list(state.get("chunks", [])), "calculations": list(state.get("calculations", [])),
           "degraded": state.get("degraded", False)}
    log = list(state.get("tool_log", []))
    plan, i = state["plan"], state.get("next_step", 0)
    max_steps = int(config.setting("agent.max_steps", 6))
    while i < len(plan) and len(log) < max_steps:
        s = plan[i]
        if s["tool"] == "search_hr_policy":
            r = run_tool("search_hr_policy", {"query": s["query"] or state["standalone"]}, ctx)
            log.append({"name": "search_hr_policy", "args": s["query"][:300], "ok": r.get("ok", False),
                        "error_code": r.get("error_code")})
        else:
            msgs = [{"role": "system", "content": prompts.EXECUTOR_SYSTEM},
                    {"role": "user", "content": f"Question: {state['standalone']}\nStep: {s['intent']}\n"
                                                f"Draft expression: {s['expression']}\n\n"
                                                f"{_ctx_text(ctx['chunks'], 2500)}\n\nCall the calculate tool."}]
            for attempt in range(2):                      # one retry on a bad tool call
                try:
                    out = get_llm().chat(msgs, tools=openai_tool_specs(["calculate"]), name="executor", max_tokens=200)
                except LLMError as ex:
                    log.append({"name": "calculate", "args": "", "ok": False, "error_code": "llm_error"})
                    state = {**state, "error": str(ex)[:200]}
                    break
                calls = out["tool_calls"] or []
                if not calls:
                    log.append({"name": "calculate", "args": "", "ok": False, "error_code": "no_tool_call"})
                    msgs.append({"role": "user", "content": "You must call the calculate tool."})
                    continue
                c = calls[0]
                r = run_tool(c.function.name if c.function.name in TOOLS else "calculate", c.function.arguments, ctx)
                log.append({"name": "calculate", "args": c.function.arguments[:300], "ok": r.get("ok", False),
                            "error_code": r.get("error_code")})
                if r.get("ok"):
                    break
                msgs.append({"role": "user", "content": f"Tool error: {r['message']}. Fix the expression and call again."})
        i += 1
    return {"chunks": ctx["chunks"], "calculations": ctx["calculations"], "tool_log": log, "next_step": i,
            "degraded": bool(ctx.get("degraded"))}


def critic(state: NavState) -> NavState:
    rounds = state.get("critic_rounds", 0)
    clog = list(state.get("critic_log", []))
    if not state.get("chunks"):
        clog.append({"verdict": "not_covered", "missing": "no passages retrieved", "new_query": ""})
        return {"critic_log": clog, "critic_rounds": rounds + 1}
    try:
        v = get_llm().chat_json([{"role": "system", "content": prompts.CRITIC_SYSTEM},
                                 {"role": "user", "content": f"Question: {state['standalone']}\n\n"
                                                             f"{_ctx_text(state['chunks'], 3000)}\n\n"
                                                             f"Calculations:\n{_calc_text(state.get('calculations')) or '(none)'}"}],
                                CriticVerdict, name="critic", max_tokens=250)
        verdict = v.model_dump()
    except LLMError as ex:
        verdict = {"verdict": "sufficient", "missing": f"critic unavailable: {ex}"[:200], "new_query": ""}
    clog.append(verdict)
    update: NavState = {"critic_log": clog, "critic_rounds": rounds + 1}
    if verdict["verdict"] == "need_more" and rounds < int(config.setting("agent.max_critic_rounds", 1)):
        q = verdict["new_query"].strip() or state["standalone"]
        update["plan"] = state["plan"] + [{"tool": "search_hr_policy", "intent": "critic follow-up", "query": q,
                                           "expression": ""}]
    return update


def responder(state: NavState) -> NavState:
    if not state.get("chunks"):
        return {"answer": prompts.NOT_COVERED_REPLY, "status": "not_covered"}
    budget = int(config.setting("agent.prompt_token_budget", 6500)) - 1500
    hist = _hist(state, 4)
    base = [{"role": "system", "content": prompts.RESPONDER_SYSTEM},
            *[{"role": m["role"], "content": m["content"][:600]} for m in hist],
            {"role": "user", "content": f"{_ctx_text(state['chunks'], min(budget, 4000))}\n\n"
                                        f"Calculations:\n{_calc_text(state.get('calculations')) or '(none)'}\n\n"
                                        f"Question: {state['standalone']}"}]
    try:
        ans = get_llm().chat(base, name="responder", max_tokens=600)["text"]
        g = output_guard.check(ans, state["chunks"], state.get("calculations"))
        if not g["ok"] or not g["has_citation"]:          # one self-repair pass (output critic)
            fb = []
            if g["invalid_citations"]:
                fb.append(f"these citation tags do not exist: {g['invalid_citations']}")
            if g["ungrounded_numbers"]:
                fb.append(f"these numbers are not in the passages or calculations: {g['ungrounded_numbers']}")
            if not g["has_citation"]:
                fb.append("no citation tags were used")
            ans2 = get_llm().chat(base + [{"role": "assistant", "content": ans},
                                          {"role": "user", "content": "Revise the answer: " + "; ".join(fb) +
                                                                      ". Use only the passages and cite with their tags."}],
                                  name="responder_repair", max_tokens=600)["text"]
            g2 = output_guard.check(ans2, state["chunks"], state.get("calculations"))
            if (not g2["invalid_citations"] and len(g2["ungrounded_numbers"]) <= len(g["ungrounded_numbers"])):
                ans, g = ans2, g2
        status = "not_covered" if re.search(r"(?i)does not cover|doesn't cover|not covered", ans) else "answered"
        return {"answer": ans, "guard": g, "status": status}
    except LLMError as ex:
        return {"answer": "Sorry, the language model is unavailable right now. Please try again in a minute.",
                "status": "error", "error": str(ex)[:200]}


def chitchat(state: NavState) -> NavState:
    return {"answer": prompts.CHITCHAT_REPLY, "status": "chitchat"}


def out_of_scope(state: NavState) -> NavState:
    return {"answer": prompts.OUT_OF_SCOPE_REPLY, "status": "refused"}


def draft_ticket(state: NavState) -> NavState:
    """Consequential action, step 1: only DRAFT the ticket (stored in state so a resume reuses it)."""
    if state.get("pending_ticket"):
        return {}
    try:
        args = get_llm().chat_json(
            [{"role": "system", "content": "Extract an HR ticket from the user's request. Do not invent personal data."},
             {"role": "user", "content": state["standalone"]}], TicketArgs, name="ticket_extract", max_tokens=300)
    except LLMError:
        args = TicketArgs(category="other", summary=(state["standalone"][:140] or "HR request").ljust(5, "."), details="")
    if not args.details.strip():                         # keep the user's own (PII-redacted) words on the ticket
        args.details = f"Request from the employee: {state['standalone'][:600]}"
    ctx: dict = {}
    run_tool("draft_hr_ticket", args.model_dump(), ctx)
    return {"pending_ticket": ctx["pending_ticket"]}


def confirm_ticket(state: NavState) -> NavState:
    """Human-in-the-loop boundary: pause the graph until the user confirms or cancels (LangGraph interrupt)."""
    from langgraph.types import interrupt
    draft = state["pending_ticket"]
    decision = interrupt({"type": "confirm_ticket", "ticket": draft,
                          "message": "Please review this draft HR ticket. Confirm to submit it, or cancel."})
    confirmed = bool(decision.get("confirm")) if isinstance(decision, dict) else str(decision).lower().startswith(("y", "c"))
    if confirmed:
        edits = decision.get("edits") if isinstance(decision, dict) else None
        if edits:                                       # the employee corrected the draft before submitting
            from src.app.tickets import clean_fields
            try:
                draft = {**draft, **clean_fields(edits.get("category", draft.get("category")),
                                                 edits.get("summary", draft.get("summary")),
                                                 edits.get("details", draft.get("details")))}
            except ValueError:
                pass                                    # keep the original draft if the edit is unusable
        submitted = {**draft, "status": "submitted", "submitted": time.strftime("%Y-%m-%d %H:%M:%S")}
        with open(config.RUNTIME_DIR / "tickets.jsonl", "a", encoding="utf-8") as f:   # stand-in for the HR system
            f.write(json.dumps(submitted) + "\n")
        return {"answer": f"Your ticket {draft['ticket_id']} has been submitted to HR.", "status": "ticket_submitted",
                "pending_ticket": None}
    return {"answer": "Okay, I've cancelled that draft. Nothing was sent.", "status": "ticket_cancelled",
            "pending_ticket": None}


def finalize(state: NavState) -> NavState:
    warn = pii.warning_for(state.get("pii", []))
    ans = output_guard.final_scrub(state.get("answer", ""), " ".join(c.get("text", "") for c in state.get("chunks") or []))
    ans = ((warn + "\n\n") if warn else "") + ans
    hist = list(state.get("history") or []) + [{"role": "user", "content": state["question"]},
                                               {"role": "assistant", "content": ans}]
    return {"answer": ans, "history": hist[-2 * int(config.setting("agent.history_turns", 6)):]}


# ----------------------------------------------------------------- edges
def after_router(state: NavState) -> str:
    return {"chitchat": "chitchat", "out_of_scope": "out_of_scope", "ticket": "draft_ticket"}.get(state["route"], "planner")


def after_critic(state: NavState) -> str:
    return "executor" if state.get("next_step", 0) < len(state.get("plan", [])) else "responder"


def build_graph(checkpointer=None):
    from langgraph.graph import END, START, StateGraph
    g = StateGraph(NavState)
    for name, fn in [("guard_in", guard_in), ("router", router), ("planner", planner), ("executor", executor),
                     ("critic", critic), ("responder", responder), ("chitchat", chitchat),
                     ("out_of_scope", out_of_scope), ("draft_ticket", draft_ticket), ("confirm_ticket", confirm_ticket),
                     ("finalize", finalize)]:
        g.add_node(name, fn)
    g.add_edge(START, "guard_in")
    g.add_edge("guard_in", "router")
    g.add_conditional_edges("router", after_router, ["planner", "chitchat", "out_of_scope", "draft_ticket"])
    g.add_edge("draft_ticket", "confirm_ticket")
    g.add_edge("planner", "executor")
    g.add_edge("executor", "critic")
    g.add_conditional_edges("critic", after_critic, ["executor", "responder"])
    for n in ("responder", "chitchat", "out_of_scope", "confirm_ticket"):
        g.add_edge(n, "finalize")
    g.add_edge("finalize", END)
    return g.compile(checkpointer=checkpointer)


_graph = None


def get_graph():
    global _graph
    if _graph is None:
        from langgraph.checkpoint.sqlite import SqliteSaver
        conn = sqlite3.connect(str(config.RUNTIME_DIR / "checkpoints.db"), check_same_thread=False)
        _graph = build_graph(SqliteSaver(conn))
    return _graph


def _to_result(question, state, usage, t0, interrupted=None) -> AgentResult:
    chunks = state.get("chunks") or []
    retrieved = [{k: c[k] for k in ("tag", "chunk_id", "doc_id", "pages")} for c in chunks]
    if chunks or state.get("route") == "policy":
        g = state.get("guard") or output_guard.check(state.get("answer", ""), chunks, state.get("calculations"))
    else:                                                   # ticket, chit-chat, refusal: no handbook facts to check
        g = {"ok": True, "has_citation": False, "invalid_citations": [], "ungrounded_numbers": [], "cited_tags": [],
             "skipped": "no handbook passages used"}
    res = AgentResult(question=question, system="m2", answer=state.get("answer", ""), status=state.get("status", ""),
                      route=state.get("route", ""), retrieved=retrieved,
                      citations=[r for r in retrieved if r["tag"] in g.get("cited_tags", [])],
                      tool_calls=state.get("tool_log", []), plan=state.get("plan", []),
                      critic=state.get("critic_log", []), guard=g, pii_categories=state.get("pii", []),
                      injection_flag=state.get("injection", False), degraded_retrieval=state.get("degraded", False),
                      pending_ticket=state.get("pending_ticket"), usage=usage.as_dict(),
                      latency_s=round(time.perf_counter() - t0, 2), error=state.get("error", ""))
    if interrupted:
        info = interrupted[0].value
        res.status, res.pending_ticket = "ticket_pending", info["ticket"]
        res.answer = (f"{info['message']}\n\n**{info['ticket']['ticket_id']}** · {info['ticket']['category']}\n"
                      f"{info['ticket']['summary']}\n{info['ticket']['details']}")
        warn = pii.warning_for(state.get("pii", []))      # the pause skips finalize, so warn here too
        if warn:
            res.answer = warn + "\n\n" + res.answer
    return res


def run_m2(question: str, thread_id: str | None = None) -> AgentResult:
    """One user turn. Same thread_id = same conversation (history and pending ticket persist)."""
    t0 = time.perf_counter()
    cfg = {"configurable": {"thread_id": thread_id or f"eval-{uuid.uuid4().hex[:10]}"}, "recursion_limit": 25}
    with track_usage() as usage:
        try:
            state = get_graph().invoke({"raw_question": question}, cfg)
        except Exception as ex:                                     # recursion limit or anything unexpected
            return AgentResult(question=question, system="m2", status="error", error=f"{type(ex).__name__}: {ex}"[:300],
                               answer="Sorry, something went wrong while answering. Please try again.",
                               usage=usage.as_dict(), latency_s=round(time.perf_counter() - t0, 2))
    return _to_result(question, state, usage, t0, state.get("__interrupt__"))


def resume_m2(thread_id: str, confirm: bool, edits: dict | None = None) -> AgentResult:
    """Resume a conversation paused at the human-confirmation step (optionally with the employee's edits)."""
    from langgraph.types import Command
    t0 = time.perf_counter()
    cfg = {"configurable": {"thread_id": thread_id}, "recursion_limit": 25}
    with track_usage() as usage:
        state = get_graph().invoke(Command(resume={"confirm": confirm, "edits": edits or {}}), cfg)
    return _to_result("(confirmation)", state, usage, t0, state.get("__interrupt__"))

"""M1: one tool-calling agent (ADR-003). Native OpenAI tool calls on Qwen3-8B (smoke-tested 22 Nov).

Engineering the brief asks for, all here:
  * tool failures / malformed arguments  -> returned to the model as error messages, it can retry
  * infinite loops                       -> max_steps cap, then a forced final answer without tools
  * token budget                         -> old tool outputs are compressed when the prompt nears the limit
  * PII + prompt injection               -> input redaction/flagging, passages sanitised, output scrubbed
  * skipped retrieval                     -> a first reply without any tool call gets one nudge to search
"""
from __future__ import annotations

import json
import time

from src import config
from src.agents import prompts
from src.agents.result import AgentResult
from src.agents.tools import openai_tool_specs, run_tool
from src.guards import injection, output_guard, pii
from src.llm.client import LLMError, TokenBudgetExceeded, get_llm, messages_tokens, track_usage

try:
    from langsmith import traceable
except Exception:                                    # pragma: no cover
    def traceable(*a, **k):
        return lambda f: f


def _compress_old_tool_messages(messages, budget):
    """Shrink older tool results (keep the latest two in full) until the prompt fits the budget."""
    tool_idx = [i for i, m in enumerate(messages) if m["role"] == "tool"]
    for i in tool_idx[:-2]:
        if messages_tokens(messages) <= budget:
            break
        messages[i] = {**messages[i], "content": messages[i]["content"][:400] + " …[compressed]"}
    return messages


def _trim_history(history, n):
    return [{"role": m["role"], "content": m["content"]} for m in (history or [])[-n:]
            if m.get("role") in ("user", "assistant") and m.get("content")]


@traceable(name="M1 single agent", run_type="chain")
def run_m1(question: str, history: list | None = None) -> AgentResult:
    t0 = time.perf_counter()
    clean_q, pii_found = pii.redact(question or "")
    res = AgentResult(question=question, system="m1", pii_categories=pii_found,
                      injection_flag=injection.detect(clean_q))
    llm = get_llm()
    max_steps = int(config.setting("agent.max_steps", 6))
    budget = int(config.setting("agent.prompt_token_budget", 6500))
    specs = openai_tool_specs()
    messages = [{"role": "system", "content": prompts.M1_SYSTEM},
                *_trim_history(history, int(config.setting("agent.history_turns", 6))),
                {"role": "user", "content": clean_q}]
    ctx: dict = {}
    final = None
    nudged = False
    with track_usage() as usage:
        try:
            for step in range(max_steps):
                _compress_old_tool_messages(messages, budget)
                out = llm.chat(messages, tools=specs, name="m1_agent", max_tokens=700)
                calls = out["tool_calls"] or []
                if not calls and step == 0 and not nudged:      # retrieval-first check (eval v2 run 1: 15 skips)
                    nudged = True
                    messages += [{"role": "assistant", "content": out["text"] or ""},
                                 {"role": "user", "content": prompts.RETRIEVAL_FIRST_NUDGE}]
                    continue
                if not calls:
                    final = out["text"]
                    break
                messages.append({"role": "assistant", "content": out["text"] or None, "tool_calls": [
                    {"id": c.id, "type": "function", "function": {"name": c.function.name, "arguments": c.function.arguments}}
                    for c in calls]})
                for c in calls:
                    r = run_tool(c.function.name, c.function.arguments, ctx)
                    res.tool_calls.append({"name": c.function.name, "args": c.function.arguments[:300],
                                           "ok": r.get("ok", False), "error_code": r.get("error_code")})
                    content = r["text"] if r.get("ok") else json.dumps({"error": r["error_code"], "message": r["message"]})
                    messages.append({"role": "tool", "tool_call_id": c.id, "content": content})
            if final is None:                                    # step cap hit: force an answer, no tools
                res.status = "step_cap"
                messages.append({"role": "user", "content": "Stop calling tools. Answer now using only the passages "
                                                            "above, with citations, or say the handbook does not cover it."})
                _compress_old_tool_messages(messages, budget)
                final = llm.chat(messages, name="m1_final", max_tokens=600)["text"]
        except TokenBudgetExceeded as ex:
            res.status, res.error = "error", f"token_budget: {ex}"
            final = prompts.NOT_COVERED_REPLY
        except LLMError as ex:
            res.status, res.error = "error", str(ex)[:300]
            final = "Sorry, the language model is unavailable right now. Please try again in a minute."
        res.usage = usage.as_dict()

    chunks = ctx.get("chunks", [])
    res.retrieved = [{k: c[k] for k in ("tag", "chunk_id", "doc_id", "pages")} for c in chunks]
    res.guard = output_guard.check(final or "", chunks, ctx.get("calculations"))
    res.citations = [r for r in res.retrieved if r["tag"] in res.guard["cited_tags"]]
    res.degraded_retrieval = bool(ctx.get("degraded"))
    res.pending_ticket = ctx.get("pending_ticket")
    if res.pending_ticket:
        res.status = "ticket_pending"
    elif res.status == "answered" and not res.tool_calls:
        res.status = "no_tool"                               # chit-chat / refusal / answered from memory
    warn = pii.warning_for(pii_found)
    res.answer = ((warn + "\n\n") if warn else "") + output_guard.final_scrub(final or "", " ".join(c.get("text", "") for c in chunks))
    res.latency_s = round(time.perf_counter() - t0, 2)
    return res

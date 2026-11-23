"""The agent's tools (brief IV: "at least three tools").

Every tool:
  * has an OpenAI function schema (native tool calling, smoke-tested 22 Nov)
  * validates its arguments with Pydantic (small models send malformed args)
  * never raises: returns {"ok": False, "error_code", "message"} so the agent can recover
  * returns compact text for the model plus structured data for citations/evaluation

Tools
  search_hr_policy   hybrid retrieval over the handbook (policy_search)
  read_policy_doc    read more of one handbook document (follow-up / multi-hop)
  calculate          safe arithmetic for entitlements (pro-rating, totals, day counts)
  draft_hr_ticket    prepare (NOT submit) an HR ticket; submitting needs human confirmation
"""
from __future__ import annotations

import ast
import json
import operator
import time
import uuid
from typing import Callable, Literal

from pydantic import BaseModel, Field, ValidationError

from src import config


# ----------------------------------------------------------------- argument schemas
class SearchArgs(BaseModel):
    query: str = Field(..., min_length=3, max_length=500,
                       description="A standalone search query in plain English (resolve 'it', 'that' etc. first)")


class ReadDocArgs(BaseModel):
    doc_id: str = Field(..., pattern=r"^doc_\d{3}$", description="Document id from a passage header, e.g. doc_019")


class CalcArgs(BaseModel):
    expression: str = Field(..., max_length=200, description="Arithmetic only, e.g. '1500 * 2' or '(25 / 12) * 7'")
    purpose: str = Field("", max_length=200, description="What is being calculated, e.g. 'pro-rated PTO for 7 months'")


class TicketArgs(BaseModel):
    category: Literal["leave", "benefits", "payroll", "expenses", "equipment", "policy_question", "other"]
    summary: str = Field(..., min_length=5, max_length=150)
    details: str = Field("", max_length=1500)


# ----------------------------------------------------------------- implementations
def _passages_text(chunks) -> str:
    from src.guards.injection import sanitize_passage
    lines = []
    for c in chunks:
        pages = ", ".join(str(p) for p in c["pages"])
        lines.append(f"[{c['tag']}] ({c['doc_id']}, p. {pages})\n{sanitize_passage(c['text'])}")
    return "\n\n".join(lines)


def search_hr_policy(args: SearchArgs, ctx: dict) -> dict:
    from src.retrieval.policy_search import policy_search
    r = policy_search(args.query)
    if not r["ok"]:
        return r
    d = r["data"]
    # Re-number tags across multiple searches in one conversation turn so citations stay unique.
    offset = len(ctx.setdefault("chunks", []))
    for i, c in enumerate(d["chunks"], 1):
        c["tag"] = f"C{offset + i}"
    ctx["chunks"].extend(d["chunks"])
    ctx.setdefault("degraded", False)
    ctx["degraded"] |= d["degraded"]
    if d["status"] == "no_relevant_policy":
        return {"ok": True, "text": "NO_RELEVANT_POLICY: the handbook has no passage that answers this query.",
                "data": d}
    return {"ok": True, "text": "<policy_passages>\n" + _passages_text(d["chunks"]) + "\n</policy_passages>",
            "data": d}


def read_policy_doc(args: ReadDocArgs, ctx: dict) -> dict:
    p = config.PROCESSED_DATA_DIR / f"{args.doc_id}.txt"
    if not p.exists():
        return {"ok": False, "error_code": "unknown_doc", "message": f"{args.doc_id} does not exist"}
    text = p.read_text(encoding="utf-8")
    words = text.split()
    clipped = " ".join(words[:900])                        # ~1,200 tokens: stay inside the 8k budget
    tag = f"C{len(ctx.setdefault('chunks', [])) + 1}"
    from src.retrieval.policy_search import get_engine
    pages = sorted({p for c in get_engine().chunks if c["doc_id"] == args.doc_id for p in c["pages"]})
    ctx["chunks"].append({"tag": tag, "chunk_id": f"{args.doc_id}::full", "doc_id": args.doc_id,
                          "pages": pages, "score": 0.0, "text": clipped})
    more = " [truncated]" if len(words) > 900 else ""
    from src.guards.injection import sanitize_passage
    return {"ok": True, "text": f"<policy_passages>\n[{tag}] ({args.doc_id}, p. {', '.join(map(str, pages))})\n"
                                f"{sanitize_passage(clipped)}{more}\n</policy_passages>"}


_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
        ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod, ast.Pow: operator.pow,
        ast.USub: operator.neg, ast.UAdd: operator.pos}


def _safe_eval(node):
    if isinstance(node, ast.Expression):
        return _safe_eval(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        left, right = _safe_eval(node.left), _safe_eval(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > 10:
            raise ValueError("exponent too large")
        return _OPS[type(node.op)](left, right)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_safe_eval(node.operand))
    raise ValueError(f"unsupported expression element: {type(node).__name__}")


def calculate(args: CalcArgs, ctx: dict) -> dict:
    expr = args.expression.replace(",", "").replace("$", "").replace("USD", "").replace("x", "*").strip()
    try:
        val = _safe_eval(ast.parse(expr, mode="eval"))
    except ZeroDivisionError:
        return {"ok": False, "error_code": "division_by_zero", "message": "division by zero"}
    except Exception as ex:
        return {"ok": False, "error_code": "bad_expression", "message": f"{ex}. Use numbers and + - * / ( ) only."}
    val = round(val, 4) if isinstance(val, float) else val
    ctx.setdefault("calculations", []).append({"expression": args.expression, "result": val, "purpose": args.purpose})
    return {"ok": True, "text": f"{args.expression} = {val}"}


def draft_hr_ticket(args: TicketArgs, ctx: dict) -> dict:
    """Consequential action boundary: this only DRAFTS. Submission requires the user to confirm (HITL)."""
    ticket = {"ticket_id": "DRAFT-" + uuid.uuid4().hex[:8].upper(), "status": "draft_awaiting_user_confirmation",
              "category": args.category, "summary": args.summary, "details": args.details,
              "created": time.strftime("%Y-%m-%d %H:%M:%S")}
    ctx["pending_ticket"] = ticket
    return {"ok": True, "text": f"Draft ticket prepared ({ticket['ticket_id']}). It is NOT submitted. "
                                "Tell the user to review it and confirm before it is sent to HR."}


# ----------------------------------------------------------------- registry
TOOLS: dict[str, tuple[type[BaseModel], Callable, str]] = {
    "search_hr_policy": (SearchArgs, search_hr_policy,
                         "Search the HR handbook. Returns passages tagged [C1], [C2]... with doc id and page. "
                         "Call this before answering any policy question."),
    "read_policy_doc": (ReadDocArgs, read_policy_doc,
                        "Read more of one handbook document when a passage is cut off or you need the surrounding "
                        "rules (eligibility, exceptions)."),
    "calculate": (CalcArgs, calculate,
                  "Exact arithmetic for entitlements: totals, pro-rating, day counts. Never do maths in your head."),
    "draft_hr_ticket": (TicketArgs, draft_hr_ticket,
                        "Prepare a draft HR ticket ONLY when the user explicitly asks to raise/submit a request. "
                        "It is not sent until the user confirms."),
}


def openai_tool_specs(names=None) -> list[dict]:
    names = names or list(TOOLS)
    return [{"type": "function", "function": {"name": n, "description": TOOLS[n][2],
                                              "parameters": TOOLS[n][0].model_json_schema()}} for n in names]


def run_tool(name: str, raw_args, ctx: dict) -> dict:
    """Validate + execute. Errors come back as data, never exceptions (brief IV: error handling)."""
    if name not in TOOLS:
        return {"ok": False, "error_code": "unknown_tool", "message": f"No tool named {name!r}. Available: {list(TOOLS)}"}
    schema, fn, _ = TOOLS[name]
    try:
        args = raw_args if isinstance(raw_args, dict) else json.loads(raw_args or "{}")
        parsed = schema.model_validate(args)
    except json.JSONDecodeError as ex:
        return {"ok": False, "error_code": "malformed_json", "message": f"Arguments were not valid JSON: {ex}"}
    except ValidationError as ex:
        return {"ok": False, "error_code": "invalid_arguments",
                "message": "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in ex.errors())[:400]}
    try:
        return fn(parsed, ctx)
    except Exception as ex:                                   # tool crashed: report, don't kill the agent
        return {"ok": False, "error_code": "tool_failure", "message": f"{type(ex).__name__}: {str(ex)[:300]}"}

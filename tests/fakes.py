"""Offline fakes for the LLM, so agent logic can be tested without the course endpoint."""
import json
import re
from types import SimpleNamespace

from src.llm.client import track_usage, _record  # noqa: F401


def _tc(name, args, i=0):
    return SimpleNamespace(id=f"call_{i}", function=SimpleNamespace(name=name, arguments=json.dumps(args)))


class FakeLLM:
    """Scripted behaviour: search once, then answer citing C1 with a number copied from the passage."""

    def __init__(self, mode="normal"):
        self.mode = mode
        self.calls = 0

    def chat(self, messages, tools=None, name="chat", **kw):
        self.calls += 1
        _record(name, 100, 20, 0.01)
        tool_msgs = [m for m in messages if m["role"] == "tool"]
        if tools and self.mode == "skip_first" and self.calls == 1:
            return {"text": "The handbook does not cover that.", "tool_calls": None}
        if tools and self.mode == "loop":
            return {"text": "", "tool_calls": [_tc("search_hr_policy", {"query": "loop forever"}, self.calls)]}
        if tools and self.mode == "bad_args" and len(tool_msgs) == 0:
            return {"text": "", "tool_calls": [_tc("search_hr_policy", {"q": 1}, 1)]}
        if tools and not any("passages" in (m["content"] or "") for m in tool_msgs):
            user = [m for m in messages if m["role"] == "user"][-1]["content"]
            return {"text": "", "tool_calls": [_tc("search_hr_policy", {"query": user[:200]}, self.calls)]}
        passages = " ".join(m["content"] or "" for m in messages if "<policy_passages>" in (m["content"] or ""))
        num = re.search(r"\d[\d,]*", passages)
        ans = f"According to the handbook, the amount is {num.group(0) if num else 'stated'} [C1]."
        return {"text": ans, "tool_calls": None}

    def chat_json(self, messages, schema, name="json", **kw):
        _record(name, 100, 20, 0.01)
        return schema.model_validate(self.json_reply(schema.__name__, messages))

    def json_reply(self, schema_name, messages):
        user = [m for m in messages if m["role"] == "user"][-1]["content"]
        if schema_name == "RouteDecision":
            u = user.split("Latest message:")[-1].lower()
            r = "out_of_scope" if "capital of" in u else "policy"
            return {"route": r, "standalone_question": user.split("Latest message:")[-1].strip()[:300], "reason": "fake"}
        if schema_name == "Plan":
            q = user.replace("Question: ", "")[:200]
            return {"steps": [{"tool": "search_hr_policy", "intent": "find the policy", "query": q}]}
        if schema_name == "TicketArgs":
            return {"category": "leave", "summary": "Parental leave request", "details": "fake"}
        if schema_name == "CriticVerdict":
            return {"verdict": "sufficient", "missing": "", "new_query": ""}
        if schema_name == "FactStatuses":
            n = len(re.findall(r"(?m)^\d+\) ", user))
            return {"statuses": ["present"] * n, "reason": "fake judge"}
        if schema_name == "Rubric":
            return {"facts": [{"fact": "the amount", "status": "present"}], "reason": "fake judge"}
        if schema_name == "Verdict":
            return {"verdict": "correct", "reason": "fake judge"}
        raise KeyError(schema_name)

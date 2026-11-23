"""30-second check of every external dependency.  Run:  python -m scripts.smoke_test

Prints a PASS/FAIL table and writes runtime/smoke_test.json (paste the table back to Claude).
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pydantic import BaseModel  # noqa: E402

from src import config  # noqa: E402
from src.llm.client import Embedder, LLMClient, extract_json  # noqa: E402

rows, facts = [], {}


def check(name, fn):
    t0 = time.perf_counter()
    try:
        detail = fn()
        rows.append(("PASS", name, f"{1000 * (time.perf_counter() - t0):6.0f} ms", str(detail)[:110]))
    except Exception as ex:
        rows.append(("FAIL", name, f"{1000 * (time.perf_counter() - t0):6.0f} ms", f"{type(ex).__name__}: {str(ex)[:160]}"))


print("TLS trust for course endpoint:", config.COURSE_TLS_VERIFY or "verify=False (CA cert not found!)")
for k in ("QWEN_API_KEY", "EMBEDDING_API_KEY", "PINECONE_API_KEY"):
    print(f"  {k:18s}", "set" if getattr(config, k) else "MISSING in .env")

llm = LLMClient(json_mode="prompt")


def models():
    r = llm.http.get(config.QWEN_BASE_URL.rstrip("/") + "/models", headers={"Authorization": f"Bearer {config.QWEN_API_KEY}"})
    r.raise_for_status()
    d = r.json()["data"][0]
    facts["max_model_len"] = d.get("max_model_len")
    return f"{d['id']} max_model_len={d.get('max_model_len')}"


def chat_nothink():
    out = llm.chat([{"role": "user", "content": "Reply with exactly: OK"}], max_tokens=20, name="smoke")
    facts["nothink_ok"] = out["text"].strip().startswith("OK")
    return f"reply={out['text']!r} tokens={out['prompt_tokens']}+{out['completion_tokens']}"


def tool_calling():
    tools = [{"type": "function", "function": {"name": "get_policy", "description": "Look up an HR policy",
              "parameters": {"type": "object", "properties": {"topic": {"type": "string"}}, "required": ["topic"]}}}]
    out = llm.chat([{"role": "user", "content": "Use the tool to look up the parental leave policy."}],
                   tools=tools, max_tokens=150, name="smoke")
    tc = out["tool_calls"]
    facts["native_tool_calls"] = bool(tc)
    return f"tool_calls={[(t.function.name, t.function.arguments) for t in tc] if tc else None} text={out['text'][:60]!r}"


class Probe(BaseModel):
    topic: str
    days: int


MSG = [{"role": "user", "content": "Return JSON with topic='parental leave' and days=16. JSON only."}]


def json_schema_mode():
    out = llm.chat(MSG, max_tokens=80, name="smoke",
                   response_format={"type": "json_schema", "json_schema": {"name": "Probe", "schema": Probe.model_json_schema()}})
    Probe.model_validate(extract_json(out["text"]))
    facts["json_schema"] = True
    return out["text"][:80]


def guided_json_mode():
    out = llm.chat(MSG, max_tokens=80, name="smoke", extra_body={"guided_json": Probe.model_json_schema()})
    Probe.model_validate(extract_json(out["text"]))
    facts["guided_json"] = True
    return out["text"][:80]


def embeddings():
    e = Embedder()
    facts["embed_provider"] = e.provider
    v = e.embed(["parental leave policy"])[0]
    n = sum(x * x for x in v) ** 0.5
    facts["embed_dim"] = len(v)
    return f"provider={e.provider} dim={len(v)} norm={n:.3f}"


def pinecone():
    from pinecone import Pinecone
    pc = Pinecone(api_key=config.PINECONE_API_KEY)
    names = pc.list_indexes().names()
    s = pc.Index(config.PINECONE_INDEX_NAME).describe_index_stats() if config.PINECONE_INDEX_NAME in names else None
    ns = {k: v.vector_count for k, v in (s.namespaces or {}).items()} if s else None
    return f"indexes={names} namespaces={ns}"


def huggingface():
    import httpx
    r = httpx.get("https://huggingface.co/api/models/cross-encoder/ms-marco-MiniLM-L6-v2", timeout=15)
    r.raise_for_status()
    return "reachable (rerankers can download)"


def langsmith():
    import os
    if not os.getenv("LANGSMITH_API_KEY"):
        raise RuntimeError("LANGSMITH_API_KEY not set (tracing off; optional but needed for the report)")
    from langsmith import Client
    return f"ok, project={os.getenv('LANGSMITH_PROJECT')} first={next(iter(Client().list_projects(limit=1))).name}"


for n, f in [("models (1034)", models), ("chat, thinking off", chat_nothink), ("native tool calling", tool_calling),
             ("json_schema decoding", json_schema_mode), ("guided_json decoding", guided_json_mode),
             ("embeddings (bge-small)", embeddings), ("pinecone", pinecone), ("huggingface", huggingface),
             ("langsmith", langsmith)]:
    check(n, f)

print()
for r in rows:
    print(f"{r[0]:4s}  {r[1]:22s} {r[2]}  {r[3]}")
mode = "json_schema" if facts.get("json_schema") else "guided_json" if facts.get("guided_json") else "prompt"
facts["recommended_json_mode"] = mode
print("\nRecommended llm.json_mode =", mode, "| native tool calls:", facts.get("native_tool_calls"))
(config.RUNTIME_DIR / "smoke_test.json").write_text(json.dumps({"rows": rows, "facts": facts}, indent=1), encoding="utf-8")

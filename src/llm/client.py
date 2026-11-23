"""One client for the course's Qwen3-8B (vLLM) and bge-small embedding endpoints.

What it handles so the agent code doesn't have to:
  * TLS via the course CA certificate (no verify=False)
  * Qwen3 thinking switched off (enable_thinking=false) and any stray <think> block stripped
  * Structured output: JSON-schema constrained decoding when the server supports it,
    otherwise prompt-only JSON, always validated with Pydantic, with repair retries
  * Token budget: refuses calls that cannot fit in max_model_len
  * Usage accounting per request (calls, tokens, latency) for cost/latency metrics
  * Optional LangSmith tracing
"""
from __future__ import annotations

import contextvars
import json
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Type

import httpx
from pydantic import BaseModel, ValidationError

from src import config

try:                                            # tracing is optional
    from langsmith import traceable
except Exception:                               # pragma: no cover
    def traceable(*a, **k):
        def deco(f):
            return f
        return deco


class LLMError(RuntimeError):
    """Endpoint failure after retries."""


class TokenBudgetExceeded(LLMError):
    """Prompt would not fit in the model's context window."""


class StructuredOutputError(LLMError):
    """Model never produced valid JSON for the schema."""


# ----------------------------------------------------------------- usage accounting
@dataclass
class Usage:
    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_s: float = 0.0
    json_repairs: int = 0
    by_name: dict = field(default_factory=dict)

    def add(self, name, pt, ct, lat):
        self.calls += 1
        self.prompt_tokens += pt
        self.completion_tokens += ct
        self.latency_s += lat
        self.by_name[name] = self.by_name.get(name, 0) + 1

    def as_dict(self):
        return {"llm_calls": self.calls, "prompt_tokens": self.prompt_tokens,
                "completion_tokens": self.completion_tokens, "llm_latency_s": round(self.latency_s, 2),
                "json_repairs": self.json_repairs, "calls_by_step": dict(self.by_name)}


_usage: contextvars.ContextVar[Usage | None] = contextvars.ContextVar("hrnav_usage", default=None)


class track_usage:
    """with track_usage() as u: ...  -> u.as_dict() after the block."""

    def __enter__(self):
        self.u = Usage()
        self.tok = _usage.set(self.u)
        return self.u

    def __exit__(self, *exc):
        _usage.reset(self.tok)


def _record(name, pt, ct, lat):
    u = _usage.get()
    if u is not None:
        u.add(name, pt, ct, lat)


# ----------------------------------------------------------------- helpers
_THINK = re.compile(r"<think>.*?</think>\s*", re.S)


def estimate_tokens(text: str) -> int:
    """Cheap estimate (~3.6 chars/token for English on Qwen's tokenizer); used only for budgeting."""
    return int(len(text) / 3.6) + 4


def messages_tokens(messages: list[dict]) -> int:
    return sum(estimate_tokens(m.get("content") or "") + 4 for m in messages)


def extract_json(text: str) -> Any:
    """Pull the first JSON object/array out of a model reply (handles ```json fences and chatter)."""
    text = _THINK.sub("", text).strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    for opener, closer in (("{", "}"), ("[", "]")):
        start = text.find(opener)
        if start == -1:
            continue
        depth, in_str, esc = 0, False, False
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                esc = (ch == "\\") and not esc
                if ch == '"' and not esc:
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == opener:
                depth += 1
            elif ch == closer:
                depth -= 1
                if depth == 0:
                    return json.loads(text[start:i + 1])
    return json.loads(text)                     # raises JSONDecodeError


# ----------------------------------------------------------------- client
# Course guide: 1 active request per group key, 60 req/min, 8192 tokens, max 1024 output tokens.
_GLOBAL_SEM = threading.Semaphore(int(config.setting("llm.max_concurrency", 1)))


class LLMClient:
    def __init__(self, base_url=None, api_key=None, model=None, verify=None, json_mode=None):
        from openai import OpenAI
        verify = config.COURSE_TLS_VERIFY if verify is None else verify
        self.http = httpx.Client(verify=verify, timeout=config.setting("llm.timeout_s", 90))
        self.client = OpenAI(base_url=base_url or config.QWEN_BASE_URL,
                             api_key=api_key or config.QWEN_API_KEY or "missing",
                             http_client=self.http, max_retries=int(config.setting("llm.max_retries", 5)))
        self.model = model or config.MODEL_NAME
        self.max_len = config.MODEL_MAX_LEN
        self.json_mode = json_mode or config.setting("llm.json_mode", "auto")
        self._sem = _GLOBAL_SEM                  # one in-flight request per key across the whole process

    # -- raw chat ---------------------------------------------------------
    def chat(self, messages: list[dict], *, max_tokens: int | None = None, temperature: float | None = None,
             name: str = "chat", extra_body: dict | None = None, response_format: dict | None = None,
             tools: list | None = None) -> dict:
        max_tokens = min(max_tokens or config.setting("llm.max_tokens", 700), 1024)
        need = messages_tokens(messages) + max_tokens
        if need > self.max_len:
            raise TokenBudgetExceeded(f"{name}: ~{need} tokens > {self.max_len}")
        body = {"chat_template_kwargs": {"enable_thinking": bool(config.setting("llm.enable_thinking", False))}}
        body.update(extra_body or {})
        kwargs = dict(model=self.model, messages=messages, max_tokens=max_tokens,
                      temperature=config.setting("llm.temperature", 0.1) if temperature is None else temperature,
                      extra_body=body)
        if response_format:
            kwargs["response_format"] = response_format
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        t0 = time.perf_counter()
        with self._sem:
            try:
                resp = self._traced_call(name, kwargs)
            except Exception as ex:
                raise LLMError(f"{name}: {type(ex).__name__}: {ex}") from ex
        lat = time.perf_counter() - t0
        msg = resp.choices[0].message
        pt = getattr(resp.usage, "prompt_tokens", 0) or 0
        ct = getattr(resp.usage, "completion_tokens", 0) or 0
        _record(name, pt, ct, lat)
        return {"text": _THINK.sub("", msg.content or "").strip(), "tool_calls": msg.tool_calls,
                "finish_reason": resp.choices[0].finish_reason, "prompt_tokens": pt,
                "completion_tokens": ct, "latency_s": lat}

    @traceable(run_type="llm", name="qwen3-8b")
    def _traced_call(self, name, kwargs):
        return self.client.chat.completions.create(**kwargs)

    # -- structured output -------------------------------------------------
    def chat_json(self, messages: list[dict], schema: Type[BaseModel], *, name: str = "json",
                  max_tokens: int | None = None, temperature: float | None = None) -> BaseModel:
        """Return a validated Pydantic object. Strategy:
        1) constrained decoding (response_format json_schema, or vLLM guided_json) if available,
        2) parse + validate, 3) on failure send the error back and ask for a fix (json_retries)."""
        js = schema.model_json_schema()
        sys_hint = ("Reply with ONLY a JSON object that matches this JSON schema. No prose, no markdown.\n"
                    f"Schema: {json.dumps(js, separators=(',', ':'))}")
        msgs = [dict(m) for m in messages]
        if msgs and msgs[0]["role"] == "system":
            msgs[0]["content"] = msgs[0]["content"] + "\n\n" + sys_hint
        else:
            msgs.insert(0, {"role": "system", "content": sys_hint})
        mode = self.json_mode
        last_err = None
        for attempt in range(1 + int(config.setting("llm.json_retries", 2))):
            rf, eb = None, None
            if mode in ("auto", "json_schema"):
                rf = {"type": "json_schema", "json_schema": {"name": schema.__name__, "schema": js}}
            elif mode == "guided_json":
                eb = {"guided_json": js}
            try:
                out = self.chat(msgs, max_tokens=max_tokens, temperature=temperature, name=name,
                                response_format=rf, extra_body=eb)
            except LLMError as ex:
                if mode == "auto" and rf is not None and "400" in str(ex):
                    mode = "prompt"                     # server rejected constrained decoding
                    continue
                raise
            try:
                return schema.model_validate(extract_json(out["text"]))
            except (json.JSONDecodeError, ValidationError, ValueError) as ex:
                last_err = f"{type(ex).__name__}: {str(ex)[:400]}"
                u = _usage.get()
                if u is not None:
                    u.json_repairs += 1
                msgs = msgs + [{"role": "assistant", "content": out["text"][:1500]},
                               {"role": "user", "content": f"That was not valid JSON for the schema ({last_err}). "
                                                           "Reply again with ONLY the corrected JSON object."}]
        raise StructuredOutputError(f"{name}: no valid JSON after retries ({last_err})")


# ----------------------------------------------------------------- embeddings
class Embedder:
    """bge-small-en-v1.5 embeddings (384-d, L2-normalised).

    provider "local" (default) -> BAAI/bge-small-en-v1.5 run locally with sentence-transformers.
                                  The learner guide: "Embeddings are not provided on these endpoints";
                                  port 1035 returned nothing from AWS (22 Nov). See ADR-008.
    provider "api"             -> an OpenAI-compatible embeddings endpoint, if one is ever provided
    """

    def __init__(self, provider: str | None = None):
        import os
        self.provider = (provider or os.getenv("EMBEDDING_PROVIDER") or config.setting("embedding.provider", "local")).lower()
        if self.provider == "local":
            from sentence_transformers import SentenceTransformer
            self.model = SentenceTransformer("BAAI/bge-small-en-v1.5", device="cpu")
        else:
            from openai import OpenAI
            self.client = OpenAI(base_url=config.EMBEDDING_BASE_URL, api_key=config.EMBEDDING_API_KEY or "missing",
                                 http_client=httpx.Client(verify=config.COURSE_TLS_VERIFY, timeout=60), max_retries=3)

    def embed(self, texts: list[str]) -> list[list[float]]:
        if self.provider == "local":
            return self.model.encode(texts, batch_size=32, normalize_embeddings=True,
                                     show_progress_bar=len(texts) > 200).tolist()
        out = []
        b = config.EMBEDDING_MAX_BATCH_SIZE
        for i in range(0, len(texts), b):
            r = self.client.embeddings.create(model=config.EMBEDDING_MODEL, input=texts[i:i + b])
            out += [d.embedding for d in sorted(r.data, key=lambda d: d.index)]
        return out


_default: LLMClient | None = None


def get_llm() -> LLMClient:
    global _default
    if _default is None:
        _default = LLMClient()
    return _default

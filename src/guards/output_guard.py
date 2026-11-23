"""Output guard: citation validity + ungrounded-number check (the Week 1 failure mode was numeric hallucination)."""
from __future__ import annotations

import re

from src.guards.pii import redact

_CIT = re.compile(r"\[C(\d+)\]")
_NUM = re.compile(r"(?<![\w.])\$?\d[\d,]*(?:\.\d+)?%?")


def norm_num(s: str) -> str | None:
    s = s.replace("$", "").replace(",", "").rstrip("%").rstrip(".")
    try:
        f = float(s)
    except ValueError:
        return None
    return str(int(f)) if f == int(f) else str(round(f, 4))


def numbers_in(text: str) -> set[str]:
    out = set()
    for m in _NUM.findall(text or ""):
        n = norm_num(m)
        if n is not None:
            out.add(n)
    # "10K" / "10k" style
    for m in re.findall(r"\$?(\d+(?:\.\d+)?)\s?[kK]\b", text or ""):
        out.add(str(int(float(m) * 1000)))
    return out


def check(answer: str, chunks: list[dict], calculations: list[dict] | None = None) -> dict:
    """Returns {valid_citations, invalid_citations, cited_tags, ungrounded_numbers, ok}."""
    tags = {c["tag"] for c in chunks}
    cited = {f"C{n}" for n in _CIT.findall(answer or "")}
    invalid = sorted(cited - tags)
    context_nums = set()
    for c in chunks:
        context_nums |= numbers_in(c["text"])
    for calc in calculations or []:
        context_nums |= numbers_in(str(calc.get("result"))) | numbers_in(calc.get("expression", ""))
    ans_nums = numbers_in(_CIT.sub("", answer or ""))
    trivial = {str(i) for i in range(0, 13)}                 # list numbering, months, small counts
    ungrounded = sorted(n for n in ans_nums - context_nums if n not in trivial)
    return {"cited_tags": sorted(cited), "invalid_citations": invalid, "ungrounded_numbers": ungrounded,
            "has_citation": bool(cited - set(invalid)), "ok": not invalid and not ungrounded}


_ROLE_EMAIL = re.compile(r"\b[\w.+-]+@(?:gitlab\.com|ourtilt\.com)\b", re.I)


def final_scrub(answer: str, sources: str = "") -> str:
    """Last line of defence: never echo the user's PII back.
    Contact details that appear verbatim in the retrieved handbook passages (a published phone line, a role
    mailbox) are policy content, not personal data, so they are kept; so are @gitlab.com / @ourtilt.com mailboxes."""
    from src.guards.pii import PATTERNS
    keep = {}

    def _hold(v):
        k = f"@@KEEP{chr(65 + len(keep))}@@"
        keep[k] = v
        return k
    out = _ROLE_EMAIL.sub(lambda m: _hold(m.group(0)), answer or "")
    if sources:
        for _name, pat in PATTERNS:
            out = pat.sub(lambda m: _hold(m.group(0)) if m.group(0) in sources else m.group(0), out)
    out = redact(out)[0]
    for k, v in keep.items():
        out = out.replace(k, v)
    return out

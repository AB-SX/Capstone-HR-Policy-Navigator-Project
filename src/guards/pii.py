"""PII detection + redaction on user input (ADR-006). Runs BEFORE logging, tracing, caching or the LLM.

Redacts and returns the categories found, so the reply can warn the user (mentor suggestion, 17 Nov).
"""
from __future__ import annotations

import re


def _luhn_ok(digits: str) -> bool:
    s, alt = 0, False
    for d in reversed(digits):
        n = int(d)
        if alt:
            n = n * 2 - 9 if n * 2 > 9 else n * 2
        s += n
        alt = not alt
    return s % 10 == 0


PATTERNS = [
    ("password", re.compile(r"(?i)\b(pass(?:word|wd|code)?|pwd|otp|pin)\s*(?:is|:|=)\s*\S+")),
    ("email", re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")),
    ("pan", re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b")),
    ("card", re.compile(r"\b(?:\d[ -]?){13,19}\b")),
    ("aadhaar", re.compile(r"\b\d{4}\s?\d{4}\s?\d{4}\b")),
    ("ssn", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("phone", re.compile(r"(?<![\w.])\+?\(?\d[\d ()-]{8,16}\d(?![\w.])")),
    ("iban_or_account", re.compile(r"(?i)\b(?:account|a/c|iban)\s*(?:no\.?|number|#)?\s*[:=]?\s*[A-Z0-9]{8,34}\b")),
]


def redact(text: str) -> tuple[str, list[str]]:
    """Return (redacted_text, sorted list of PII categories found)."""
    found = set()
    out = text
    for name, pat in PATTERNS:
        def _sub(m, name=name):
            val = m.group(0)
            if name == "card" and not _luhn_ok(re.sub(r"\D", "", val)):
                return val
            if name == "phone" and not 10 <= len(re.sub(r"\D", "", val)) <= 13:
                return val
            found.add(name)
            return f"[REDACTED_{name.upper()}]"
        out = pat.sub(_sub, out)
    return out, sorted(found)


def warning_for(categories: list[str]) -> str:
    if not categories:
        return ""
    nice = ", ".join(c.replace("_", " ") for c in categories)
    return (f"⚠️ It looks like you shared personal or sensitive information ({nice}). I removed it and didn't use it. "
            "Please don't share passwords, IDs or account numbers here.")

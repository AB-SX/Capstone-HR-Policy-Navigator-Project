"""Prompt-injection defences (brief VI: "prompt-injection tests against the document corpus").

Two surfaces:
  1. User input       -> detect common jailbreak / instruction-override patterns; flag (not block) and log.
  2. Retrieved text   -> passages are wrapped in <policy_passages> and the system prompt says they are DATA.
                         Lines inside passages that look like instructions to the assistant are neutralised.
"""
from __future__ import annotations

import re

_INJ = re.compile(
    r"(?i)(ignore (all |any )?(previous|prior|above) (instructions|prompts|rules)"
    r"|disregard (the |your )?(system|previous) (prompt|instructions)"
    r"|you are now (?!eligible)|act as (?:an? )?(?:dan|developer mode|unrestricted)"
    r"|(?:reveal|print|show|output|repeat) (?:me )?(?:your|the) (?:full |entire |original |hidden )?(?:system )?(?:prompt|instructions)|(?:print|reveal|show|send) (?:any |all |your |the )?(?:api|secret) keys?"
    r"|new instructions?:|<\s*/?\s*system\s*>|\bjailbreak\b|override (your|all) (rules|safety))")


def detect(text: str) -> bool:
    return bool(_INJ.search(text or ""))


def sanitize_passage(text: str) -> str:
    """Neutralise instruction-like lines inside retrieved documents (they are data, never commands)."""
    if not detect(text):
        return text
    return _INJ.sub(lambda m: "[instruction-like text removed]", text)

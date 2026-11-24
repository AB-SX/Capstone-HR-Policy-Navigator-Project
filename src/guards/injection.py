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
    r"|new instructions?:|<\s*/?\s*system\s*>|\bjailbreak\b|override (your|all) (rules|safety)"
    # text inside a document that addresses the AI rather than the employee (live RAI test, 23 Nov)
    r"|(?:note|message|instructions?|reminder)s? (?:for|to) (?:any |all )?(?:ai|llm|language model|chat ?bot|the assistant|assistants?)\b"
    r"|(?:ai|llm|language model|chat ?bot)s? (?:assistants? )?(?:should|must|are to) (?:quote|say|answer|respond|reply|state|tell)"
    r"|without (?:a |any )?citations?)")


def detect(text: str) -> bool:
    return bool(_INJ.search(text or ""))


QUARANTINED = ("[Passage withheld: it contains instructions addressed to the assistant, so it is not used as "
               "policy evidence.]")


def sanitize_passage(text: str) -> str:
    """A retrieved passage that talks to the assistant is withheld entirely (it is data, never commands).
    Removing only the matched phrase left the planted claim itself in place (live RAI test, 23 Nov).
    None of the 502 handbook documents trips the detector, so real policy text is unaffected."""
    return QUARANTINED if detect(text) else text

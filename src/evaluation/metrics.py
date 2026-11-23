"""Answer-quality scoring: deterministic rules + LLM-as-judge, and the failure taxonomy (brief V).

Mentor (17 Nov): compare LLM-judge with deterministic scoring and report agreement.
"""
from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field

from src.guards.output_guard import numbers_in

_STOP = set("""a an the and or of to in on for with by is are was were be been it its this that these those as at from
your you we our their they he she his her i me my can will may must should would do does did not no yes if then than
which who whom what when where how per each any all also such into up out about over under more most less very""".split())


def _toks(s: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]+", (s or "").lower()) if t not in _STOP]


def token_f1(pred: str, gold: str) -> tuple[float, float, float]:
    p, g = _toks(pred), _toks(gold)
    if not p or not g:
        return 0.0, 0.0, 0.0
    from collections import Counter
    common = sum((Counter(p) & Counter(g)).values())
    if not common:
        return 0.0, 0.0, 0.0
    prec, rec = common / len(p), common / len(g)
    return 2 * prec * rec / (prec + rec), prec, rec


def deterministic(pred: str, gold: str) -> dict:
    """Week-1-compatible rule: correct if token F1 >= 0.5, or recall >= 0.55 and every gold number appears."""
    f1, _, rec = token_f1(pred, gold)
    gnums, pnums = numbers_in(gold), numbers_in(pred)
    nums_ok = gnums <= pnums
    return {"token_f1": round(f1, 3), "token_recall": round(rec, 3), "gold_numbers": sorted(gnums),
            "numbers_match": nums_ok, "det_correct": bool(f1 >= 0.5 or (rec >= 0.55 and nums_ok))}


REFUSAL_RE = re.compile(r"(?i)does not (cover|specify|mention)|doesn't (cover|specify|mention)|not (explicitly )?(covered|"
                        r"stated|detailed|specified)|couldn't find|cannot provide|can only help|unrelated to HR")


class Verdict(BaseModel):
    verdict: Literal["correct", "partially_correct", "incorrect"]
    reason: str = Field(..., max_length=300)
    facts: list = Field(default_factory=list)          # filled by the rubric judge (in-scope questions)


class FactCheck(BaseModel):
    fact: str = Field(..., max_length=200)
    status: Literal["present", "missing", "contradicted"]


class Rubric(BaseModel):
    facts: list[FactCheck] = Field(..., min_length=1, max_length=8)
    reason: str = Field(..., max_length=300)


RUBRIC_SYSTEM = """You check an HR-policy assistant's answer against a gold answer written by an expert.
Step 1: split the gold answer into its key facts (1 to 6 short facts: each number, condition, name, yes/no).
Step 2: for each key fact, mark it:
- "present": the assistant answer states it with the same meaning and values (1,500 USD = $1,500; 10K = 10,000)
- "missing": the assistant answer does not state it
- "contradicted": the assistant answer states something incompatible with it
Extra information in the assistant answer is NOT a problem unless it contradicts a gold fact. Ignore citation tags like [C1].
Give the reason in English, in one sentence of at most 30 words."""


def verdict_from_facts(facts) -> str:
    """Deterministic verdict from the fact checks, so the label doesn't depend on the judge's mood:
    correct = nothing contradicted and at least 2/3 of key facts present; incorrect = none present, or a
    contradiction with under half present; otherwise partially correct."""
    st = [f["status"] if isinstance(f, dict) else f.status for f in facts]
    n = len(st)
    present = sum(x == "present" for x in st)
    contradicted = "contradicted" in st
    share = present / n if n else 0.0
    if not contradicted and share >= 2 / 3 - 1e-9:
        return "correct"
    if share == 0 or (contradicted and share < 0.5):
        return "incorrect"
    return "partially_correct"


FACTCHECK_SYSTEM = """You check whether an HR-policy assistant's answer states each of a list of key facts.
For each numbered key fact, in order, output one status:
- "present": the answer states this fact with the same meaning and values (1,500 USD = $1,500 = 1500 dollars; 10K = 10,000). Wording can differ.
- "missing": the answer does not state this fact.
- "contradicted": the answer states a different value or the opposite of THIS fact.
Judge each fact only against the answer. Extra information in the answer never makes a fact missing or contradicted.
Ignore citation tags like [C1] and text like [REDACTED_EMAIL]. Give the reason in English, in at most 30 words."""


def check_facts(llm, question: str, facts: list[str], pred: str) -> Verdict:
    """Grade against a fixed, reviewed list of key facts (data/evaluation/eval_v2_keyfacts.json)."""
    from pydantic import create_model
    n = len(facts)
    Schema = create_model("FactStatuses",
                          statuses=(list[Literal["present", "missing", "contradicted"]], Field(..., min_length=n, max_length=n)),
                          reason=(str, Field(..., max_length=300)))
    numbered = "\n".join(f"{i}) {f}" for i, f in enumerate(facts, 1))
    msgs = [{"role": "system", "content": FACTCHECK_SYSTEM},
            {"role": "user", "content": f"Question: {question}\n\nKey facts ({n}):\n{numbered}\n\n"
                                        f"Assistant answer:\n{pred}\n\nReturn exactly {n} statuses, one per key fact, in order."}]
    r = llm.chat_json(msgs, Schema, name="judge", max_tokens=300, temperature=0.0)
    checked = [{"fact": f, "status": s} for f, s in zip(facts, r.statuses)]
    return Verdict(verdict=verdict_from_facts(checked), reason=r.reason, facts=checked)


JUDGE_SYSTEM = """\
You grade answers from an HR-policy assistant against a gold answer written by an expert.
- "correct": contains the gold answer's key facts (numbers, conditions, names); extra correct detail is fine.
- "partially_correct": some key facts right but something important missing or vague.
- "incorrect": wrong facts, wrong numbers, contradicts the gold answer, or doesn't answer.
Numbers must match in value (1,500 USD = $1,500 = 1500 dollars; 10K = 10,000). Ignore citation tags like [C1].
Give the reason in English, in one sentence of at most 30 words."""

JUDGE_IN_SCOPE = ("This question IS answered by the handbook (the gold answer comes from it). An assistant answer that "
                  "says the handbook does not cover it, or declines, is \"incorrect\".")
JUDGE_OUT_OF_SCOPE = ("This question is NOT answerable from the HR handbook. A polite refusal or a statement that the "
                      "handbook does not cover it is \"correct\"; any attempt to answer it is \"incorrect\".")


def judge(llm, question: str, gold: str, pred: str, in_scope: bool = True, key_facts: list[str] | None = None) -> Verdict:
    """In scope with key facts: fixed fact checklist (preferred). In scope without: the judge extracts the facts itself.
    Out of scope: one-shot verdict on whether the assistant declined."""
    user = f"Question: {question}\n\nGold answer: {gold}\n\nAssistant answer: {pred}\n\n"
    if in_scope and key_facts:
        return check_facts(llm, question, key_facts, pred)
    if in_scope:
        msgs = [{"role": "system", "content": RUBRIC_SYSTEM},
                {"role": "user", "content": user + "List the gold key facts and mark each one."}]
        r = llm.chat_json(msgs, Rubric, name="judge", max_tokens=600, temperature=0.0)
        return Verdict(verdict=verdict_from_facts(r.facts), reason=r.reason,
                       facts=[f.model_dump() for f in r.facts])
    msgs = [{"role": "system", "content": JUDGE_SYSTEM + "\n" + JUDGE_OUT_OF_SCOPE},
            {"role": "user", "content": user + "Grade it."}]
    return llm.chat_json(msgs, Verdict, name="judge", max_tokens=300, temperature=0.0)


def failure_category(row: dict) -> str | None:
    """Taxonomy for answers not judged correct: retrieval_miss | hallucination | reasoning_error |
    tool_call_error | skipped_search | over_refusal | under_refusal."""
    if row["judge"] == "correct":
        return None
    if row.get("type") == "out_of_scope":
        return "under_refusal"
    if row["status"] in ("error", "step_cap") or (row["tool_errors"] and not row["searches"]):
        return "tool_call_error"
    if not row["searches"]:
        return "skipped_search"                     # answered or refused an in-scope question without looking
    if row["status"] in ("not_covered", "refused") or REFUSAL_RE.search(row["answer"]):
        return "over_refusal" if row["gold_retrieved"] else "retrieval_miss"
    if not row["gold_retrieved"]:
        return "retrieval_miss"
    if row["ungrounded_numbers"] or row["invalid_citations"]:
        return "hallucination"
    return "reasoning_error"

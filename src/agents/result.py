"""Shared result type for every system (M1, M2) so the API, UI and evaluation treat them the same."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class AgentResult:
    question: str
    answer: str = ""
    status: str = "answered"            # answered | not_covered | refused | chitchat | ticket_pending | error | step_cap
    route: str = "policy"
    citations: list = field(default_factory=list)       # [{tag, doc_id, pages, chunk_id}] actually cited
    retrieved: list = field(default_factory=list)       # every chunk shown to the model
    tool_calls: list = field(default_factory=list)      # [{name, args, ok, error_code}]
    plan: list = field(default_factory=list)
    critic: list = field(default_factory=list)
    guard: dict = field(default_factory=dict)            # output guard result
    pii_categories: list = field(default_factory=list)
    injection_flag: bool = False
    degraded_retrieval: bool = False
    pending_ticket: dict | None = None
    usage: dict = field(default_factory=dict)
    latency_s: float = 0.0
    error: str = ""
    system: str = ""

    def to_dict(self):
        return asdict(self)

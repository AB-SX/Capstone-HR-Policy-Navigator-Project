"""HR request workflow: submissions from the graph, reviewer status changes, employee lookup."""
import json

import pytest

from src.app import tickets as tk


@pytest.fixture
def runtime(monkeypatch, tmp_path):
    monkeypatch.setattr(tk.config, "RUNTIME_DIR", tmp_path)
    with open(tmp_path / "tickets.jsonl", "w", encoding="utf-8") as f:
        f.write(json.dumps({"ticket_id": "HR-AAAA1111", "status": "submitted", "category": "leave",
                            "summary": "Parental leave request", "details": "", "submitted": "2026-11-24 10:00:00"}) + "\n")
    return tmp_path


def test_status_workflow_and_history(runtime):
    assert tk.get("hr-aaaa1111")["status"] == "submitted"
    tk.update("HR-AAAA1111", "in_progress", "Looking into it", "Priya")
    t = tk.update("HR-AAAA1111", "resolved", "Approved from 1 Dec", "Priya")
    assert t["status"] == "resolved" and [h["status"] for h in t["history"]] == ["submitted", "in_progress", "resolved"]
    v = tk.employee_view("HR-AAAA1111")
    assert v["status"] == "Resolved" and v["note"] == "Approved from 1 Dec" and "history" not in v
    assert len((runtime / "tickets.jsonl").read_text().splitlines()) == 1      # submissions never rewritten


def test_rejects_unknown_request_or_status(runtime):
    with pytest.raises(ValueError):
        tk.update("HR-NOPE0000", "resolved")
    with pytest.raises(ValueError):
        tk.update("HR-AAAA1111", "approved")
    assert tk.employee_view("HR-NOPE0000") is None


def test_direct_submission_validates_and_redacts(runtime):
    t = tk.submit("leave", "Leave from 1 Jan", "My PAN is ABCDE1234F, call +91 98765 43210")
    assert t["ticket_id"].startswith("HR-") and "ABCDE1234F" not in t["details"] and "98765" not in t["details"]
    assert tk.get(t["ticket_id"])["status"] == "submitted"
    with pytest.raises(ValueError):
        tk.submit("leave", "hi", "")
    assert tk.submit("not-a-topic", "Something odd here", "")["category"] == "other"

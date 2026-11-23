"""Ask the assistant from the terminal.

    python -m scripts.ask "How much is the home office stipend for new hires?"
    python -m scripts.ask "And what about laptops?" --system m2 --thread demo1   # same thread = follow-up
    python -m scripts.ask "Please raise a ticket for my parental leave" --system m2 --thread demo1
    python -m scripts.ask --confirm yes --thread demo1                            # human-in-the-loop decision
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("question", nargs="?", default="")
    ap.add_argument("--system", default="m2", choices=["m1", "m2"])
    ap.add_argument("--thread", default=None)
    ap.add_argument("--confirm", choices=["yes", "no"])
    ap.add_argument("--json", action="store_true", help="print the full result object")
    a = ap.parse_args()
    if a.confirm:
        from src.agents.graph import resume_m2
        r = resume_m2(a.thread, a.confirm == "yes")
    elif a.system == "m1":
        from src.agents.single_agent import run_m1
        r = run_m1(a.question)
    else:
        from src.agents.graph import run_m2
        r = run_m2(a.question, thread_id=a.thread)
    if a.json:
        print(json.dumps(r.to_dict(), indent=1, ensure_ascii=False))
        return
    print("\n" + r.answer + "\n")
    for c in r.citations:
        print(f"  [{c['tag']}] {c['doc_id']}  p. {', '.join(map(str, c['pages']))}")
    print(f"\nstatus={r.status} route={r.route} tools={[t['name'] for t in r.tool_calls]} "
          f"llm_calls={r.usage.get('llm_calls')} latency={r.latency_s}s guard_ok={r.guard.get('ok')}")
    if r.plan:
        print("plan:", [s.get('query') or s.get('expression') for s in r.plan])
    if r.critic:
        print("critic:", [c['verdict'] for c in r.critic])


if __name__ == "__main__":
    main()

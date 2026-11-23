"""HR Policy Navigator: Streamlit chat app (ADR-005).

    streamlit run src/app/navigator.py

Chat history lives in this browser session only; "New conversation" clears it.
M2 conversations are also checkpointed server-side per thread (24 h) so follow-ups and ticket confirmation work.
"""
import hmac
import os
import re
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import streamlit as st  # noqa: E402

st.set_page_config(page_title="HR Policy Navigator", page_icon="📘", layout="centered")

SYSTEMS = {"Multi-agent (M2)": "m2", "Single agent (M1)": "m1"}
STARTERS = ["What is the home office stipend for new hires, and how do I claim it?",
            "How many days of parental leave do I get?",
            "Can I expense a co-working space?",
            "Please raise an HR ticket for my parental leave request"]
DISCLAIMER = ("Answers come only from the GitLab team handbook and cite the page they used. "
              "Check with the People team before acting on anything important.")


@st.cache_resource(show_spinner="Loading the handbook index…")
def service():
    from src.app.service import get_service
    from src.retrieval.policy_search import get_engine
    get_engine()                                  # load BM25, vectors and reranker once per server
    return get_service()


def client_key() -> str:
    try:
        fwd = st.context.headers.get("X-Forwarded-For", "")
        if fwd:
            return fwd.split(",")[0].strip()
    except Exception:
        pass
    return st.session_state.sid


def tag_chips(text: str) -> str:
    text = re.sub(r"(?<!\n)\n(?!\n)", "  \n", text or "")        # keep single line breaks in markdown
    return re.sub(r"\[(C\d+)\]", r" :blue-background[\1]", text)


def init_state():
    ss = st.session_state
    ss.setdefault("sid", uuid.uuid4().hex)
    ss.setdefault("thread", uuid.uuid4().hex[:16])
    ss.setdefault("messages", [])
    ss.setdefault("authed", not os.getenv("HRNAV_ACCESS_CODE"))
    ss.setdefault("queued", None)


def access_gate():
    st.title("HR Policy Navigator")
    st.write("This demo is private. Enter the access code you were given.")
    with st.form("gate"):
        code = st.text_input("Access code", type="password")
        if st.form_submit_button("Enter"):
            if hmac.compare_digest(code.strip(), os.getenv("HRNAV_ACCESS_CODE", "")):
                st.session_state.authed = True
                st.rerun()
            st.error("That code isn't right. Check it and try again.")


def render_answer(m: dict, show_details: bool, idx: int):
    st.markdown(tag_chips(m["answer"]))
    if m.get("sources"):
        with st.expander(f"Sources ({len(m['sources'])})"):
            for s in m["sources"]:
                pages = ", ".join(map(str, s["pages"]))
                st.markdown(f"**{s['tag']}** · `{s['doc_id']}` · page {pages}")
                if s.get("excerpt"):
                    st.caption(s["excerpt"])
    t = m.get("pending_ticket")
    if m.get("status") == "ticket_pending" and t and not m.get("resolved"):
        c1, c2, _ = st.columns([1, 1, 3])
        if c1.button("Confirm and submit", key=f"yes{idx}", type="primary"):
            st.session_state.queued = ("confirm", True, idx)
            st.rerun()
        if c2.button("Cancel", key=f"no{idx}"):
            st.session_state.queued = ("confirm", False, idx)
            st.rerun()
    if show_details and m.get("status") not in (None, "user"):
        u = m.get("usage") or {}
        bits = [f"status: {m.get('status')}", f"route: {m.get('route', '-')}",
                f"model calls: {u.get('llm_calls', 0)}", f"time: {m.get('latency_s', 0)} s"]
        if m.get("cached"):
            bits.append("from cache")
        if m.get("tools"):
            bits.append("tools: " + ", ".join(m["tools"]))
        st.caption(" · ".join(bits))
        if m.get("plan"):
            st.caption("plan: " + " → ".join(p for p in m["plan"] if p))
        if m.get("critic"):
            st.caption("critic: " + ", ".join(c for c in m["critic"] if c))


def main():
    init_state()
    if not st.session_state.authed:
        access_gate()
        return
    ss = st.session_state

    with st.sidebar:
        st.subheader("Settings")
        label = st.radio("Assistant", list(SYSTEMS), help="M2 plans, checks its evidence and can draft HR tickets. "
                                                          "M1 is a single tool-calling agent.")
        system = SYSTEMS[label]
        show_details = st.toggle("Show how it answered", value=True)
        if st.button("New conversation", use_container_width=True):
            ss.messages, ss.thread = [], uuid.uuid4().hex[:16]
            st.rerun()
        st.divider()
        st.caption(DISCLAIMER)
        st.caption("Don't enter personal details. Emails, phone numbers and ID numbers are masked before the model "
                   "sees them. Tickets are only filed after you confirm.")

    st.title("HR Policy Navigator")
    st.caption("Ask about leave, benefits, expenses, equipment, travel, hiring, relocation and other GitLab policies.")

    svc = service()

    # a click on Confirm / Cancel from the previous run
    if ss.queued:
        _, yes, idx = ss.queued
        ss.queued = None
        ss.messages[idx]["resolved"] = True
        with st.spinner("Submitting…" if yes else "Cancelling…"):
            out = svc.confirm(ss.messages[idx].get("thread_id", ss.thread), yes, client_key())
        ss.messages.append({"role": "assistant", **out})

    if not ss.messages:
        st.write("Try one of these:")
        cols = st.columns(2)
        for i, q in enumerate(STARTERS):
            if cols[i % 2].button(q, key=f"starter{i}", use_container_width=True):
                ss.pending_question = q
                st.rerun()

    for i, m in enumerate(ss.messages):
        with st.chat_message(m["role"]):
            if m["role"] == "user":
                st.markdown(m["content"])
            else:
                render_answer(m, show_details, i)

    question = st.chat_input("Ask a question about GitLab HR policy") or ss.pop("pending_question", None)
    if question:
        history = [{"role": m["role"], "content": m["content"] if m["role"] == "user" else m.get("answer", "")}
                   for m in ss.messages][-int(6):]
        ss.messages.append({"role": "user", "content": question})
        with st.chat_message("user"):
            st.markdown(question)
        with st.chat_message("assistant"):
            with st.spinner("Searching the handbook…"):
                out = svc.ask(question, system, ss.thread, history, client_key())
            m = {"role": "assistant", **out}
            ss.messages.append(m)
            render_answer(m, show_details, len(ss.messages) - 1)


main()

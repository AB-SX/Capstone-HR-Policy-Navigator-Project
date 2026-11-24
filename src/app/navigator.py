"""HR Policy Navigator: the employee-facing Streamlit app (ADR-005).

    python -m streamlit run src/app/navigator.py

Settings (environment / .env):
    HRNAV_ACCESS_CODE   shared code employees enter once per session (empty = no gate)
    HRNAV_ADMIN_CODE    code for the usage page at  ?admin=1  (empty = page disabled)
    HRNAV_HR_CODE       code for the HR request review page at  ?hr=1  (empty = page disabled)
    HRNAV_DEV_MODE=1    team/demo view: M1/M2 switch and "how it answered" details
    HRNAV_SYSTEM        m2 (default) or m1 for the employee view

Privacy: chat history is kept only in the employee's browser (localStorage). The server keeps the current
conversation's redacted state for follow-ups (deleted on "New conversation", "Clear" or after 24 h idle),
a usage log without question text, and thumbs up/down feedback without chat text.
"""
import hmac
import html
import json
import os
import re
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import streamlit as st  # noqa: E402

ASSETS = Path(__file__).resolve().parent / "assets"
MARK = str(ASSETS / "mark.png")         # plain "HR" monogram: favicon, assistant avatar, sidebar brand
st.set_page_config(page_title="HR Policy Navigator", page_icon=MARK, layout="centered")

DEV = os.getenv("HRNAV_DEV_MODE") == "1"
DEFAULT_SYSTEM = os.getenv("HRNAV_SYSTEM", "m2") if os.getenv("HRNAV_SYSTEM", "m2") in ("m1", "m2") else "m2"
LS_KEY = "hrnav_chats_v1"
MAX_CHATS, MAX_MSGS = 20, 40

TOPICS = {
    "Leave and time off": ["How many consecutive days of vacation can I take?",
                           "Who administers parental leave in the US and Canada?"],
    "Expenses and equipment": ["What is the home office stipend for new hires, and how do I claim it?",
                               "Can I expense a co-working space?"],
    "Benefits and pay": ["How much is provided for professional development each year?",
                         "How long can I continue medical coverage under COBRA?"],
    "Moving and working abroad": ["How long can I work outside my primary residence?",
                                  "How far in advance must I request an international relocation?"],
}
FRIENDLY = {
    "rate_limited": "You're asking quickly. Please wait a few seconds and try again.",
    "busy": "The assistant is busy answering another question. Please try again in a minute.",
    "daily_cap": "The assistant has reached today's limit. Please try again tomorrow, or contact the People team.",
    "error": "Something went wrong while answering. Please try again; if it keeps happening, contact the People team.",
}
PRIVACY = ("Your chats are saved only in this browser on this device. Clear them any time. To answer follow-up "
           "questions the server keeps the current conversation, with personal details removed, for up to 24 hours. "
           "Feedback is stored without your question or the answer.")
DISCLAIMER = ("Answers come only from the company HR handbook and show the page they used. For decisions about your "
              "own situation, confirm with the People team.")
import base64  # noqa: E402
MARK_B64 = base64.b64encode(Path(MARK).read_bytes()).decode()
FOOTNOTE = "HR Policy Navigator can make mistakes. Check the cited handbook page, or ask the People team."
BOT_AVATAR = MARK
# One icon family (Material Symbols, Rounded, as shipped with Streamlit), one meaning each. No sparkles or robots.
TOPIC_ICONS = {"Leave and time off": ":material/event_available:", "Expenses and equipment": ":material/receipt_long:",
               "Benefits and pay": ":material/health_and_safety:", "Moving and working abroad": ":material/flight:"}

# Chat-app look: plain white canvas, grey sidebar, user turns as right-hand bubbles, assistant turns as plain text,
# rounded message box with a one-line footnote. Selectors are Streamlit 1.41 test ids / st-key-<key> classes.
CSS = """
<style>
header[data-testid="stHeader"]{background:transparent;height:2.5rem}
[data-testid="stToolbar"],[data-testid="stDecoration"],[data-testid="stAppDeployButton"],#MainMenu{display:none!important}
[data-testid="stMainBlockContainer"]{max-width:48rem;padding-top:1.5rem;padding-bottom:7rem}
h1,h2,h3{font-weight:600!important;letter-spacing:-.01em}

/* sidebar */
[data-testid="stSidebar"]{background:#f9f9f9;border-right:1px solid #ececec}
[data-testid="stSidebarUserContent"]{padding-top:.5rem}
[data-testid="stSidebar"] .stButton button{justify-content:flex-start;text-align:left;border:none;background:transparent;
  box-shadow:none;padding:.35rem .6rem;min-height:2.1rem;border-radius:.6rem;font-size:.9rem;color:#1f1f1f}
[data-testid="stSidebar"] .stButton button:hover{background:#ececec;color:#1f1f1f}
[data-testid="stSidebar"] .stButton button{overflow:hidden;max-width:100%}
[data-testid="stSidebar"] .stButton button div{min-width:0;overflow:hidden}
[data-testid="stSidebar"] .stButton button p{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
[data-testid="stSidebarHeader"]{height:2.75rem;padding-bottom:0}
[data-testid="stSidebar"] [class*="st-key-chat_cur_"] button{background:#e8e8e8;font-weight:500}
[data-testid="stSidebar"] .st-key-newchat button{border:1px solid #e3e3e3;background:#fff;font-weight:500}
[data-testid="stSidebar"] .st-key-newchat button:hover{background:#f0f0f0}
.side-brand{display:flex;align-items:center;gap:.55rem;font-weight:600;font-size:1.02rem;padding:.2rem .6rem .7rem}
.side-brand img{width:26px;height:26px;border-radius:7px}
.side-group{font-size:.75rem;font-weight:600;color:#8e8e8e;padding:.9rem .6rem .2rem;text-transform:none}
[data-testid="stSidebar"] [data-testid="stExpander"] details{border:none;background:transparent}
[data-testid="stSidebar"] [data-testid="stExpander"] summary{padding:.35rem .6rem;border-radius:.6rem;font-size:.9rem}
[data-testid="stSidebar"] [data-testid="stExpander"] summary:hover{background:#ececec}

/* empty state */
.hello{text-align:center;font-size:1.9rem;font-weight:600;margin:14vh 0 .4rem;letter-spacing:-.02em}
@media (max-width:640px){.hello{margin-top:1.5rem;font-size:1.45rem}.hello-sub{display:none}
  [data-testid="stMainBlockContainer"]{padding-top:2.5rem;padding-bottom:5rem}.st-key-suggest .stButton button p{font-size:.84rem}.st-key-suggest .stButton button{min-height:auto}}
.hello-sub{text-align:center;color:#6b6b6b;font-size:.95rem;margin-bottom:1.6rem}
.st-key-suggest .stButton button{text-align:left;justify-content:flex-start;align-items:flex-start;min-height:4.6rem;
  border:1px solid #e5e5e5;border-radius:1rem;background:#fff;padding:.7rem .9rem;color:#3a3a3a;box-shadow:none}
.st-key-suggest .stButton button:hover{background:#f7f7f7;border-color:#d9d9d9;color:#1f1f1f}
.st-key-suggest .stButton button p{font-size:.88rem;line-height:1.35}

/* access code screen */
.st-key-gate{max-width:23rem;margin:16vh auto 0;border:1px solid #ececec;border-radius:1.1rem;padding:1.6rem 1.5rem 1rem}
.gate-head{display:flex;align-items:center;gap:.6rem;font-size:1.2rem;font-weight:600;margin-bottom:.3rem}
.gate-head img{width:30px;height:30px;border-radius:8px}
.gate-sub{color:#6b6b6b;font-size:.9rem;margin-bottom:.8rem}

/* messages */
[data-testid="stChatMessage"]{background:transparent!important;padding:.4rem 0;gap:.75rem}
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]){flex-direction:row-reverse}
[data-testid="stChatMessageAvatarUser"]{display:none}
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) [data-testid="stChatMessageContent"]{
  flex:0 1 auto;max-width:80%;margin:0 0 0 auto!important;background:#f1f1f2;border-radius:1.4rem;padding:.55rem 1.1rem}
[data-testid="stChatMessageAvatarCustom"]{border-radius:8px}
.st-key-suggest .stButton button span[data-testid="stIconMaterial"]{color:#6b6b6b;margin-top:.1rem}
[data-testid="stChatMessage"] [data-testid="stExpander"] details{border:1px solid #ececec;border-radius:.8rem}
[data-testid="stChatMessage"] [data-testid="stExpander"] summary p{font-size:.85rem;color:#5d5d5d}

/* message box */
[data-testid="stBottomBlockContainer"]{max-width:48rem;padding-bottom:.6rem}
[data-testid="stChatInput"]{border-radius:1.6rem!important;border:1px solid #e0e0e0!important;background:#fff!important;
  box-shadow:0 2px 12px rgba(0,0,0,.06)}
[data-testid="stChatInput"] > div{border-radius:1.6rem;background:#fff}
[data-testid="stChatInputSubmitButton"]{background:#1f1f1f!important;border-radius:50%!important;color:#fff!important}
[data-testid="stChatInputSubmitButton"]:disabled{background:#d7d7d7!important}
[data-testid="stBottomBlockContainer"]::after{content:"__FOOTNOTE__";display:block;text-align:center;
  font-size:.72rem;color:#8e8e8e;padding-top:.45rem}
</style>
""".replace("__FOOTNOTE__", FOOTNOTE)


# ------------------------------------------------------------------ resources
@st.cache_resource(show_spinner="Loading the handbook…")
def service():
    from src.app.service import get_service
    from src.retrieval.policy_search import get_engine
    get_engine()
    svc = get_service()
    svc.purge_expired(force=True)
    return svc


def client_key() -> str:
    try:
        fwd = st.context.headers.get("X-Forwarded-For", "")
        if fwd:
            return fwd.split(",")[0].strip()
    except Exception:
        pass
    return st.session_state.sid


# ------------------------------------------------------------------ browser storage
HISTORY_OK = True
try:
    from streamlit_js_eval import streamlit_js_eval
except ImportError:                        # app still works; saved chats are simply turned off
    HISTORY_OK = False


def js(expr: str, key: str):
    return streamlit_js_eval(js_expressions=expr, key=key) if HISTORY_OK else "[]"


def load_chats():
    """Read saved chats from this browser once per session (the component answers on the next rerun)."""
    ss = st.session_state
    if ss.chats_loaded:
        return
    raw = js(f"(()=>{{try{{return localStorage.getItem('{LS_KEY}')||'[]'}}catch(e){{return '[]'}}}})()", "ls_get")
    if raw is None:
        return
    try:
        ss.chats = [c for c in json.loads(raw) if isinstance(c, dict) and c.get("id")][:MAX_CHATS]
    except (ValueError, TypeError):
        ss.chats = []
    ss.chats_loaded = True


def save_chats():
    ss = st.session_state
    if not HISTORY_OK:
        return
    ss.save_n += 1
    payload = json.dumps(json.dumps(ss.chats[:MAX_CHATS]))
    js(f"(()=>{{try{{localStorage.setItem('{LS_KEY}',{payload});return 1}}catch(e){{return 0}}}})()", f"ls_set_{ss.save_n}")


def remember_current():
    """Upsert the open conversation into the browser-side list (no server copy)."""
    ss = st.session_state
    if not ss.messages:
        return
    slim = []
    for m in ss.messages[-MAX_MSGS:]:
        if m["role"] == "user":
            slim.append({"role": "user", "content": m["content"]})
        else:
            slim.append({"role": "assistant", "content": m.get("answer", ""), "status": m.get("status"),
                         "sources": [{k: s.get(k) for k in ("tag", "pages", "title")} for s in m.get("sources", [])]})
    first = next((m["content"] for m in ss.messages if m["role"] == "user"), "Conversation")
    chat = {"id": ss.thread, "title": first[:70], "ts": int(time.time()), "msgs": slim}
    ss.chats = [chat] + [c for c in ss.chats if c["id"] != ss.thread]
    save_chats()


CATEGORY_LABELS = {"leave": "Leave and time off", "benefits": "Benefits", "payroll": "Pay and payroll",
                   "expenses": "Expenses", "equipment": "Equipment", "policy_question": "Policy question",
                   "other": "Something else"}


# ------------------------------------------------------------------ rendering
ORG = re.compile(r"\b(?:GitLab|Gitlab|GITLAB)(?!\.com|\.io|-)('s)?\b")
SHOW_ORG = os.getenv("HRNAV_SHOW_ORG") == "1"


def mask(text: str) -> str:
    """The source handbook belongs to a real company; employees see a neutral name. Email addresses and web
    links are left intact so contact details still work. HRNAV_SHOW_ORG=1 shows the original text."""
    if SHOW_ORG or not text:
        return text or ""
    out = re.sub(r"\b(?:[Tt]he )?(?:GitLab|Gitlab) (?:team )?handbook", "the HR handbook", text)
    out = ORG.sub(lambda m: "the company's" if m.group(1) else "the company", out)
    out = re.sub(r"(^|[.!?:]\s+|(?:^|\n)\s*(?:[-*]\s+|\d+\.\s+))the (company|HR handbook)",
                 lambda m: f"{m.group(1)}The {m.group(2)}", out)
    return out


def renumber(answer: str, sources: list) -> tuple[str, list]:
    """C1, C3 … become 1, 2 … in the order they are listed under Sources."""
    order = {s["tag"]: i for i, s in enumerate(sources, 1)}
    text = re.sub(r"\[(C\d+)\]", lambda m: f" :gray-background[{order[m.group(1)]}]" if m.group(1) in order else "",
                  answer or "")
    text = re.sub(r"(?<!\n)\n(?!\n)", "  \n", text)
    return text, sources


def render_answer(m: dict, idx: int):
    text, sources = renumber(mask(m.get("answer", "")), m.get("sources") or [])
    if m.get("status") in FRIENDLY:
        st.info(FRIENDLY[m["status"]] if m["status"] != "rate_limited" else m.get("answer", FRIENDLY["rate_limited"]))
    elif m.get("status") == "ticket_pending":
        if m.get("pii"):
            st.warning("You shared personal details. They were removed before anything was drafted.")
        st.markdown("I've drafted this request for you." if not m.get("resolved") else "Draft request (closed).")
    else:
        st.markdown(text)
    if sources:
        with st.expander(f"Sources ({len(sources)})", icon=":material/menu_book:"):
            for i, s in enumerate(sources, 1):
                pages = ", ".join(map(str, s.get("pages") or []))
                title = f" · {s['title']}" if s.get("title") else ""
                st.markdown(f"**{i}.** HR handbook, page {pages}{mask(title)}")
                if s.get("excerpt"):
                    st.caption(mask(s["excerpt"]))
    if m.get("status") == "ticket_pending" and m.get("pending_ticket") and not m.get("resolved"):
        t = m["pending_ticket"]
        with st.form(f"draft{idx}", border=True):
            st.markdown("**Draft request to the People team**")
            st.caption("Nothing has been sent. Check and edit the details, then submit or cancel.")
            cats = CATEGORY_LABELS
            cur = t.get("category", "other") if t.get("category") in cats else "other"
            cat = st.selectbox("Topic", list(cats), index=list(cats).index(cur), format_func=cats.get, key=f"dc{idx}")
            summ = st.text_input("Summary", value=mask(t.get("summary", "")), max_chars=150, key=f"ds{idx}")
            det = st.text_area("Details", value=mask(t.get("details", "")), max_chars=1500, key=f"dd{idx}",
                               help="Describe what you need. Don't include ID numbers or bank details.")
            c1, c2, _ = st.columns([1, 1, 3], gap="small")
            send = c1.form_submit_button("Submit to HR", type="primary")
            cancel = c2.form_submit_button("Cancel")
            if send:
                if len(summ.strip()) < 5:
                    st.error("Please add a short summary (at least 5 characters).")
                else:
                    st.session_state.queued = ("confirm", True, idx, {"category": cat, "summary": summ, "details": det})
                    st.rerun()
            if cancel:
                st.session_state.queued = ("confirm", False, idx, None)
                st.rerun()
    if m.get("status") in ("answered", "not_covered", "refused") and not m.get("history_view"):
        rating = st.feedback("thumbs", key=f"fb{idx}")
        if rating is not None and not m.get("fb_sent"):
            c = st.text_input("Anything we should know? (optional, no personal details)", key=f"fbc{idx}")
            if st.button("Send feedback", key=f"fbs{idx}"):
                service().feedback(rating, c, {**m, "n_sources": len(sources)})
                m["fb_sent"] = True
                st.toast("Thanks for the feedback")
        elif m.get("fb_sent"):
            st.caption("Feedback sent. Thank you.")
    if DEV and m.get("usage") is not None:
        u = m.get("usage") or {}
        st.caption(" · ".join(x for x in [f"status: {m.get('status')}", f"route: {m.get('route', '-')}",
                                           f"model calls: {u.get('llm_calls', 0)}", f"time: {m.get('latency_s', 0)} s",
                                           "from cache" if m.get("cached") else "",
                                           ("tools: " + ", ".join(m["tools"])) if m.get("tools") else ""] if x))
        if m.get("plan"):
            st.caption("plan: " + " → ".join(p for p in m["plan"] if p))


# ------------------------------------------------------------------ pages
def init_state():
    ss = st.session_state
    ss.setdefault("sid", uuid.uuid4().hex)
    ss.setdefault("thread", uuid.uuid4().hex[:16])
    ss.setdefault("messages", [])
    ss.setdefault("chats", [])
    ss.setdefault("chats_loaded", False)
    ss.setdefault("save_n", 0)
    ss.setdefault("authed", not os.getenv("HRNAV_ACCESS_CODE"))
    ss.setdefault("queued", None)
    ss.setdefault("system", DEFAULT_SYSTEM)


def gate(code_env: str, title: str, text: str, flag: str) -> bool:
    if st.session_state.get(flag):
        return True
    with st.container(key="gate"):
        st.markdown(f'<div class="gate-head"><img src="data:image/png;base64,{MARK_B64}"><div>{title}</div></div>'
                    f'<div class="gate-sub">{text}</div>', unsafe_allow_html=True)
        with st.form(f"gate_{flag}", border=False):
            code = st.text_input("Access code", type="password", placeholder="Access code", label_visibility="collapsed")
            if st.form_submit_button("Continue", type="primary", use_container_width=True):
                if code and hmac.compare_digest(code.strip(), os.getenv(code_env, "")):
                    st.session_state[flag] = True
                    st.rerun()
                st.error("That code isn't right. Check it and try again.")
    return False


# ------------------------------------------------------------------ admin console (?admin=1) and HR review (?hr=1)
STATUS_STYLE = {"submitted": ("#1d4ed8", "#eff4ff"), "in_progress": ("#b45309", "#fff7e6"),
                "resolved": ("#15803d", "#ecfdf3"), "closed": ("#525252", "#f2f2f2")}
CONSOLE_CSS = """<style>
[data-testid="stMainBlockContainer"]{max-width:72rem;padding-top:2rem;padding-bottom:3rem}
[data-testid="stSidebar"] [class*="st-key-nav_cur_"] button{background:#e8e8e8;font-weight:500}
.side-role{font-size:.75rem;color:#8e8e8e;padding:0 .6rem .4rem;margin-top:-.5rem}
.page-head{font-size:1.5rem;font-weight:600;letter-spacing:-.01em;margin:.2rem 0 .1rem}
.page-sub{color:#6b6b6b;font-size:.9rem;margin-bottom:1.1rem}
.sec{font-size:.95rem;font-weight:600;margin:1.3rem 0 .4rem}
[data-testid="stMetric"]{border:1px solid #ececec;border-radius:.9rem;padding:.8rem 1rem;background:#fff}
[data-testid="stMetricLabel"] p{color:#6b6b6b;font-size:.8rem}
[data-testid="stMetricValue"]{font-size:1.6rem;font-weight:600}
.pill{display:inline-block;padding:.1rem .6rem;border-radius:999px;font-size:.78rem;font-weight:500}
.req-title{font-size:1.05rem;font-weight:600;margin:.2rem 0 .2rem}
.req-meta{color:#6b6b6b;font-size:.82rem;margin-bottom:.6rem}
.req-field{font-size:.78rem;color:#8e8e8e;margin-top:.6rem}
.req-val{font-size:.92rem;white-space:pre-wrap}
.tl{border-left:2px solid #ececec;margin:.4rem 0 0 .35rem;padding-left:.9rem}
.tl-item{position:relative;padding:.15rem 0 .7rem;font-size:.85rem}
.tl-item:before{content:"";position:absolute;left:-1.27rem;top:.45rem;width:.6rem;height:.6rem;border-radius:50%;
  background:#fff;border:2px solid #9a9a9a}
.tl-note{color:#4a4a4a}
.tl-when{color:#8e8e8e;font-size:.78rem}
[data-testid="stDataFrame"]{border:1px solid #ececec;border-radius:.8rem;overflow:hidden}
</style>"""


def esc(x) -> str:
    return html.escape(str(x or ""))


OUTCOMES = {"answered": "Answered", "not_covered": "Not in the handbook", "refused": "Out of scope",
            "chitchat": "Small talk", "ticket_pending": "Request drafted", "ticket_submitted": "Request submitted",
            "ticket_cancelled": "Request cancelled", "rate_limited": "Too many questions", "busy": "Assistant busy",
            "daily_cap": "Daily limit reached", "error": "Error", "empty": "Empty message"}


def pill(status: str) -> str:
    from src.app import tickets as tk
    fg, bg = STATUS_STYLE.get(status, ("#525252", "#f2f2f2"))
    return f'<span class="pill" style="color:{fg};background:{bg}">{tk.LABELS.get(status, status)}</span>'


def page_head(title: str, sub: str = ""):
    st.markdown(f'<div class="page-head">{title}</div>' + (f'<div class="page-sub">{sub}</div>' if sub else ""),
                unsafe_allow_html=True)


def console(role: str, views: dict, flag: str):
    """Shared shell for the admin and HR pages: same sidebar look as the assistant, one view at a time."""
    ss = st.session_state
    st.markdown(CONSOLE_CSS, unsafe_allow_html=True)
    key = f"view_{flag}"
    ss.setdefault(key, next(iter(views)))
    with st.sidebar:
        st.markdown(f'<div class="side-brand"><img src="data:image/png;base64,{MARK_B64}">HR Policy Navigator</div>'
                    f'<div class="side-role">{role}</div>', unsafe_allow_html=True)
        for name, (icon, _) in views.items():
            cur = ss[key] == name
            if st.button(name, key=f"nav_{'cur_' if cur else ''}{flag}_{name}", icon=icon,
                         use_container_width=True) and not cur:
                ss[key] = name
                st.rerun()
        st.divider()
        st.markdown('<a href="./" target="_self" style="font-size:.9rem;padding:0 .6rem;color:#1f1f1f">'
                    'Open the assistant</a>', unsafe_allow_html=True)
        if st.button("Sign out", key=f"signout_{flag}", icon=":material/logout:", use_container_width=True):
            ss[flag] = False
            st.rerun()
    views[ss[key]][1]()


def lean_bars(labels: list, values: list, unit: str, horizontal: bool = False, color: str = "#1f1f1f",
              height: int = 220, label_title: str = ""):
    """Thin bars, light grid, no chart chrome. Bar thickness is fixed, so one day or one category never fills the
    whole chart width."""
    import altair as alt
    import pandas as pd
    d = pd.DataFrame({"label": labels, "value": values})
    cat = alt.X if not horizontal else alt.Y
    num = alt.Y if not horizontal else alt.X
    enc = {("x" if not horizontal else "y"): cat("label:N", sort=None if not horizontal else "-x", title=label_title or None,
                                                axis=alt.Axis(labelAngle=0, labelColor="#6b6b6b", ticks=False,
                                                              domainColor="#e5e5e5", labelLimit=180)),
           ("y" if not horizontal else "x"): num("value:Q", title=None,
                                                axis=alt.Axis(tickMinStep=1, format="d", labelColor="#8e8e8e",
                                                              gridColor="#f0f0f0", domain=False, ticks=False)),
           "tooltip": [alt.Tooltip("label:N", title=label_title or " "), alt.Tooltip("value:Q", title=unit)]}
    chart = (alt.Chart(d).mark_bar(color=color, size=12 if horizontal else 14,
                                   cornerRadiusEnd=3).encode(**enc)
             .properties(height=height).configure_view(stroke=None).configure(background="transparent"))
    st.altair_chart(chart, use_container_width=True)


def daily_counts(days_series, n_days: int = 14):
    """Questions per day for the last n_days, including days with none, labelled like '24 Nov'."""
    import pandas as pd
    end = pd.Timestamp(time.strftime("%Y-%m-%d"))
    idx = pd.date_range(end - pd.Timedelta(days=n_days - 1), end, freq="D")
    counts = pd.to_datetime(days_series, errors="coerce").dt.normalize().value_counts()
    return [x.strftime("%d %b").lstrip("0") for x in idx], [int(counts.get(x, 0)) for x in idx]


def weekly_counts(dates, n_weeks: int = 8):
    """Requests per week (Monday start) for the last n_weeks, including empty weeks, labelled like 'w/c 23 Nov'."""
    import pandas as pd
    today = pd.Timestamp(time.strftime("%Y-%m-%d"))
    start = today - pd.Timedelta(days=today.weekday())
    weeks = [start - pd.Timedelta(weeks=i) for i in range(n_weeks - 1, -1, -1)]
    d = pd.to_datetime(dates, errors="coerce").dropna().dt.normalize()
    counts = (d - pd.to_timedelta(d.dt.weekday, unit="D")).value_counts()
    return ["w/c " + w.strftime("%d %b").lstrip("0") for w in weeks], [int(counts.get(w, 0)) for w in weeks]


def usage_view():
    import pandas as pd
    from src.app import tickets as tk
    page_head("Usage", "Questions, speed and feedback. No question or answer text is stored on the server.")
    logs, fb = service().usage_rows()
    reqs = tk.all_tickets()
    df = pd.DataFrame(logs) if logs else pd.DataFrame(columns=["ts", "status", "cached", "latency_s", "llm_calls",
                                                               "prompt_tokens", "system"])
    df["day"] = df["ts"].astype(str).str[:10]
    answered = df[~df["status"].isin(["rate_limited", "busy", "daily_cap", "empty"])]
    fdf = pd.DataFrame(fb) if fb else pd.DataFrame(columns=["rating", "comment", "ts", "status"])
    today = time.strftime("%Y-%m-%d")
    c = st.columns(4)
    c[0].metric("Questions", len(answered), help="Answered, not covered, refused or chit-chat")
    c[1].metric("Median answer time", f"{answered['latency_s'].median():.1f} s" if len(answered) else "–")
    c[2].metric("Thumbs up", f"{100 * fdf['rating'].mean():.0f}%" if len(fdf) else "–", help=f"{len(fdf)} ratings")
    c[3].metric("Open HR requests", sum(t["status"] in ("submitted", "in_progress") for t in reqs),
                help=f"{len(reqs)} requests in total")
    c = st.columns(4)
    c[0].metric("Questions today", int((answered["day"] == today).sum()))
    c[1].metric("Answered from cache", f"{100 * answered['cached'].astype(bool).mean():.0f}%" if len(answered) else "–")
    c[2].metric("Model calls today", int(df[df["day"] == today]["llm_calls"].fillna(0).sum()))
    c[3].metric("Model calls per question", f"{answered['llm_calls'].mean():.2f}" if len(answered) else "–")
    if not len(df):
        st.info("No questions yet. Numbers appear here once employees start using the assistant.")
        return
    left, right = st.columns(2)
    with left:
        st.markdown('<div class="sec">Questions per day · last 14 days</div>', unsafe_allow_html=True)
        lean_bars(*daily_counts(answered["day"]), unit="Questions", height=230)
    with right:
        st.markdown('<div class="sec">Outcome</div>', unsafe_allow_html=True)
        oc = df["status"].map(lambda x: OUTCOMES.get(x, x)).value_counts()
        lean_bars(list(oc.index), [int(v) for v in oc.values], unit="Questions", horizontal=True, color="#8e8e8e",
                  height=min(260, 40 + 30 * len(oc)))
    st.markdown('<div class="sec">Thumbs-down comments</div>', unsafe_allow_html=True)
    neg = fdf[(fdf["rating"] == 0) & (fdf["comment"].fillna("") != "")] if len(fdf) else fdf
    if len(neg):
        st.dataframe(neg[["ts", "comment", "status"]].sort_values("ts", ascending=False), hide_index=True,
                     use_container_width=True, column_config={"ts": "When", "comment": "Comment", "status": "Outcome"})
    else:
        st.caption("No thumbs-down comments yet. Comments have personal details removed before they are stored.")


def requests_view(reviewer_default: str = ""):
    """Every request employees submitted, filters, a detail panel with history, and the status update form."""
    from src.app import tickets as tk
    ss = st.session_state
    page_head("HR requests", "Requests employees confirmed in the assistant or filed from the request form. "
                             "Personal details were removed before they were stored.")
    rows = tk.all_tickets()
    c = st.columns(4)
    for col, sname in zip(c, tk.STATUSES):
        col.metric(tk.LABELS[sname], sum(t["status"] == sname for t in rows))
    if not rows:
        st.info("No requests yet. They appear here when an employee submits one.")
        return
    f1, f2, f3 = st.columns([2, 1.3, 1.7])
    show = f1.multiselect("Status", tk.STATUSES, default=["submitted", "in_progress"], format_func=tk.LABELS.get)
    topic = f2.selectbox("Topic", ["all"] + tk.CATEGORIES,
                         format_func=lambda x: "All topics" if x == "all" else CATEGORY_LABELS.get(x, x))
    q = f3.text_input("Search", placeholder="Reference or words in the summary").strip().lower()
    keep = [t for t in rows if t["status"] in show and (topic == "all" or t.get("category") == topic)
            and (not q or q in t["ticket_id"].lower() or q in (t.get("summary") or "").lower()
                 or q in (t.get("details") or "").lower())]
    st.dataframe([{"Reference": t["ticket_id"], "Status": tk.LABELS[t["status"]],
                   "Topic": CATEGORY_LABELS.get(t.get("category"), t.get("category", "")),
                   "Summary": mask(t.get("summary", "")), "From": "Assistant" if t.get("source") != "form" else "Form",
                   "Submitted": t.get("submitted", ""), "Last update": t["updated"], "Reviewer": t.get("reviewer", "")}
                  for t in keep], hide_index=True, use_container_width=True)
    if not keep:
        st.caption("No requests match these filters.")
        return
    with st.expander("Breakdown by topic and week", icon=":material/bar_chart:"):
        import pandas as pd
        d = pd.DataFrame(rows)
        d["Topic"] = d["category"].map(lambda x: CATEGORY_LABELS.get(x, x))
        a, b = st.columns(2)
        tc = d["Topic"].value_counts()
        with a:
            st.caption("By topic")
            lean_bars(list(tc.index), [int(v) for v in tc.values], unit="Requests", horizontal=True,
                      height=min(260, 40 + 30 * len(tc)))
        with b:
            st.caption("By week · last 8 weeks")
            lean_bars(*weekly_counts(d["submitted"].fillna(d.get("created", ""))), unit="Requests", color="#8e8e8e",
                      height=200)

    st.markdown('<div class="sec">Open a request</div>', unsafe_allow_html=True)
    ref = st.selectbox("Request", [t["ticket_id"] for t in keep], label_visibility="collapsed",
                       format_func=lambda r: f"{r} · {mask(next(t for t in keep if t['ticket_id'] == r).get('summary', ''))[:70]}")
    t = tk.get(ref)
    left, right = st.columns([3, 2], gap="large")
    with left, st.container(border=True):
        st.markdown(
            f'<div>{pill(t["status"])}</div><div class="req-title">{esc(mask(t.get("summary", "")))}</div>'
            f'<div class="req-meta">{t["ticket_id"]} · {CATEGORY_LABELS.get(t.get("category"), t.get("category", ""))}'
            f' · submitted {t.get("submitted", "")} · from {"the assistant" if t.get("source") != "form" else "the form"}</div>'
            f'<div class="req-field">Details</div><div class="req-val">{esc(mask(t.get("details", ""))) or "—"}</div>'
            f'<div class="req-field">History</div><div class="tl">'
            + "".join(f'<div class="tl-item">{pill(h["status"])}'
                      + (f' <span class="tl-note">· {esc(h["by"])}</span>' if h.get("by") else "")
                      + (f'<div class="tl-note">{esc(mask(h["note"]))}</div>' if h.get("note") else "")
                      + f'<div class="tl-when">{esc(h["ts"])}</div></div>' for h in t["history"])
            + "</div>", unsafe_allow_html=True)
    with right, st.form(f"upd_{ref}"):
        st.markdown("**Update status**")
        new = st.selectbox("New status", tk.STATUSES, index=tk.STATUSES.index(t["status"]),
                           format_func=lambda x: tk.LABELS[x])
        note = st.text_area("Note to the employee", placeholder="Shown when they check their reference")
        by = st.text_input("Your name", value=ss.get("reviewer", reviewer_default))
        if st.form_submit_button("Save", type="primary", use_container_width=True):
            ss.reviewer = by
            tk.update(ref, new, note, by)
            st.toast(f"{ref} is now {tk.LABELS[new]}")
            st.rerun()


def admin_page():
    if not os.getenv("HRNAV_ADMIN_CODE"):
        st.info("The admin page is turned off. Set HRNAV_ADMIN_CODE to enable it.")
        return
    if not gate("HRNAV_ADMIN_CODE", "Admin", "Enter the admin code.", "admin_ok"):
        return
    console("Admin", {"Usage": (":material/monitoring:", usage_view),
                      "HR requests": (":material/assignment:", lambda: requests_view("Admin"))}, "admin_ok")


def hr_page():
    """HR reviewers: see every request employees submitted and move it through the workflow."""
    if not os.getenv("HRNAV_HR_CODE"):
        st.info("The HR review page is turned off. Set HRNAV_HR_CODE to enable it.")
        return
    if not gate("HRNAV_HR_CODE", "HR request review", "Enter the HR reviewer code.", "hr_ok"):
        return
    console("HR reviewer", {"HR requests": (":material/assignment:", requests_view)}, "hr_ok")


def _group(ts: int) -> str:
    days = (time.time() - ts) / 86400
    if time.strftime("%Y-%m-%d", time.localtime(ts)) == time.strftime("%Y-%m-%d"):
        return "Today"
    return "Previous 7 days" if days <= 7 else "Older"


def open_chat(c: dict):
    """Reopen a chat saved in this browser. It keeps its id, so it stays in the list and new turns update it."""
    ss, svc = st.session_state, service()
    svc.forget(ss.thread)
    svc.forget(c["id"])
    ss.thread = c["id"]
    ss.messages = [({"role": "user", "content": m["content"]} if m["role"] == "user" else
                    {"role": "assistant", "answer": m.get("content", ""), "status": m.get("status"),
                     "sources": m.get("sources") or [], "history_view": True, "resolved": True})
                   for m in c.get("msgs", [])]
    svc.seed(ss.thread, c.get("msgs", []))


def new_chat():
    ss = st.session_state
    service().forget(ss.thread)
    ss.messages, ss.thread = [], uuid.uuid4().hex[:16]


def sidebar():
    ss = st.session_state
    from src.app import tickets as tk
    with st.sidebar:
        st.markdown(f'<div class="side-brand"><img src="data:image/png;base64,{MARK_B64}">HR Policy Navigator</div>',
                    unsafe_allow_html=True)
        if st.button("New chat", key="newchat", icon=":material/edit_square:", use_container_width=True):
            new_chat()
            st.rerun()

        if not HISTORY_OK:
            st.caption("Saving chats is off on this server.")
        shown = None
        for c in ss.chats[:MAX_CHATS]:
            g = _group(c.get("ts", 0))
            if g != shown:
                st.markdown(f'<div class="side-group">{g}</div>', unsafe_allow_html=True)
                shown = g
            cur = c["id"] == ss.thread
            if st.button(c["title"], key=f"chat_{'cur_' if cur else ''}{c['id']}", use_container_width=True,
                         help=time.strftime("%d %b %Y, %H:%M", time.localtime(c.get("ts", 0)))) and not cur:
                open_chat(c)
                st.rerun()
        if not ss.chats:
            st.markdown('<div class="side-group">Your chats appear here, saved in this browser only.</div>',
                        unsafe_allow_html=True)

        st.divider()
        with st.expander("New HR request", icon=":material/assignment_add:"):
            with st.form("new_request", clear_on_submit=True, border=False):
                cat = st.selectbox("Topic", list(CATEGORY_LABELS), format_func=CATEGORY_LABELS.get, key="nr_cat")
                summ = st.text_input("Summary", max_chars=150, placeholder="Parental leave from 1 January", key="nr_sum")
                det = st.text_area("Details", max_chars=1500, key="nr_det",
                                   placeholder="What do you need from the People team?")
                if st.form_submit_button("Submit to HR", type="primary"):
                    try:
                        t = tk.submit(cat, summ, det)
                        st.success(f"Sent. Reference: {t['ticket_id']}")
                    except ValueError as ex:
                        st.error(str(ex))
            st.caption("Personal details such as ID or account numbers are removed automatically.")
        with st.expander("Check a request", icon=":material/pending_actions:"):
            ref = st.text_input("Reference", placeholder="HR-1A2B3C4D", key="ref_lookup")
            if ref:
                v = tk.employee_view(ref)
                if v:
                    st.markdown(f"**{v['status']}** · updated {v['updated']}")
                    st.caption(mask(v["summary"]))
                    if v["note"]:
                        st.info(v["note"])
                else:
                    st.caption("No request found with that reference. Check it and try again.")
        with st.expander("About and privacy", icon=":material/lock:"):
            st.caption(DISCLAIMER)
            st.caption(PRIVACY)
            st.caption("Please don't type personal details. Emails, phone numbers and ID numbers are removed before "
                       "the assistant sees them. Requests to HR are only sent after you confirm.")
            if ss.chats and st.button("Clear chats on this device", key="clearall", icon=":material/delete:"):
                ss.chats = []
                new_chat()
                save_chats()
                st.rerun()
        if DEV:
            with st.expander("Developer", icon=":material/code:"):
                ss.system = {"Multi-agent (M2)": "m2", "Single agent (M1)": "m1"}[
                    st.radio("Assistant", ["Multi-agent (M2)", "Single agent (M1)"],
                             index=0 if ss.system == "m2" else 1)]


def empty_state():
    st.markdown('<div class="hello">How can I help with HR today?</div>'
                '<div class="hello-sub">Ask about leave, benefits, expenses, equipment, travel or relocation. '
                'Every answer links to the handbook page it came from.</div>', unsafe_allow_html=True)
    with st.container(key="suggest"):
        cols = st.columns(2)
        for i, (topic, qs) in enumerate(TOPICS.items()):
            if cols[i % 2].button(f"**{topic}**  \n{qs[0]}", key=f"t{i}", icon=TOPIC_ICONS.get(topic),
                                  use_container_width=True):
                st.session_state.pending_question = qs[0]
                st.rerun()


def chat_page():
    ss = st.session_state
    svc = service()
    load_chats()
    sidebar()

    if ss.queued:
        _, yes, idx, edits = (list(ss.queued) + [None])[:4]
        ss.queued = None
        ss.messages[idx]["resolved"] = True
        with st.spinner("Sending your request…" if yes else "Cancelling…"):
            out = svc.confirm(ss.thread, yes, client_key(), edits)
        if yes and out.get("status") == "ticket_submitted":
            ref = (ss.messages[idx].get("pending_ticket") or {}).get("ticket_id", "")
            out["answer"] = (f"Your request has been sent to the People team. Reference: **{ref}**. "
                             "You can check its status any time under **Check a request** in the sidebar.")
        elif not yes:
            out["answer"] = "Cancelled. Nothing was sent."
        ss.messages.append({"role": "assistant", **out})
        remember_current()

    if not ss.messages and not ss.get("pending_question"):
        empty_state()

    for i, m in enumerate(ss.messages):
        with st.chat_message(m["role"], avatar=BOT_AVATAR if m["role"] == "assistant" else None):
            if m["role"] == "user":
                st.markdown(m["content"])
            else:
                render_answer(m, i)

    question = st.chat_input("Message HR Policy Navigator") or ss.pop("pending_question", None)
    if question:
        history = [{"role": m["role"], "content": m["content"] if m["role"] == "user" else m.get("answer", "")}
                   for m in ss.messages][-6:]
        ss.messages.append({"role": "user", "content": question})
        with st.chat_message("user"):
            st.markdown(question)
        with st.chat_message("assistant", avatar=BOT_AVATAR):
            with st.spinner("Thinking…"):
                out = svc.ask(question, ss.system, ss.thread, history, client_key())
            m = {"role": "assistant", **out}
            ss.messages.append(m)
            render_answer(m, len(ss.messages) - 1)
        remember_current()


def main():
    st.markdown(CSS, unsafe_allow_html=True)
    init_state()
    if st.query_params.get("admin"):
        admin_page()
        return
    if st.query_params.get("hr"):
        hr_page()
        return
    if not gate("HRNAV_ACCESS_CODE", "HR Policy Navigator", "Enter the access code shared with you by the People team.",
                "authed"):
        return
    chat_page()


main()

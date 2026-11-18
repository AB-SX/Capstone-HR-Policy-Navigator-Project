import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))

import streamlit as st
from rag_pipeline import RAGPipeline

st.set_page_config(page_title="HR Policy Navigator", layout="centered")


@st.cache_resource
def load_pipeline():
    return RAGPipeline()


pipeline = load_pipeline()

if "history" not in st.session_state:
    st.session_state.history = []
if "current" not in st.session_state:
    st.session_state.current = None

# --- Sidebar: History ---
with st.sidebar:
    st.header("Chat History")
    if not st.session_state.history:
        st.caption("No previous questions yet.")
    for i, item in enumerate(reversed(st.session_state.history)):
        label = item["query"][:50] + "..." if len(item["query"]) > 50 else item["query"]
        if st.button(label, key=f"hist_{i}", use_container_width=True):
            st.session_state.current = item

# --- Main Area ---
st.title("HR Policy Navigator")
st.caption("Ask questions about GitLab HR policies")

SAMPLE_QUESTIONS = [
    "What is the home office stipend for new hires?",
    "When is business class airfare permitted for international travel?",
    "What are the emergency benefits under the Chubb Business Travel Accident Policy?",
    "How are team member accounts handled if placed on leave during an internal investigation?",
]

# Show sample buttons only when no current result
st.markdown("**Try a sample question:**")
for i, q in enumerate(SAMPLE_QUESTIONS):
    if st.button(q, key=f"sample_{i}", use_container_width=True):
        st.session_state.pending_query = q
        st.rerun()

query = st.chat_input("Ask an HR policy question...")

if "pending_query" in st.session_state:
    query = st.session_state.pop("pending_query")

if query:
    with st.spinner("Searching policies..."):
        result = pipeline.answer(query)
    st.session_state.current = result
    st.session_state.history.append(result)
    st.rerun()

# Display current Q&A
if st.session_state.current:
    result = st.session_state.current
    st.markdown(f"### Q: {result['query']}")
    st.divider()
    st.markdown(result["answer"])
    with st.expander("View Sources"):
        for s in result["sources"]:
            st.markdown(f"- **{s['source']}** (score: {s['score']:.4f})")

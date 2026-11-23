"""Chunking + page tagging (ported verbatim from the Step 3 lab so lab numbers == production numbers).

C1 = fixed 150 words / 20 overlap (the original repo chunker)
C2 = fixed 300 / 50
C3 = heading-aware, never mid-sentence, <=200 words, heading prefixed
"""
import re
from pathlib import Path


def load_docs(processed_dir):
    return {p.stem: p.read_text(encoding="utf-8").strip()
            for p in sorted(Path(processed_dir).glob("doc_*.txt"))}


# ---------------------------------------------------------------- chunkers
def chunk_fixed(text, size=150, overlap=20):
    """C1/C2: fixed word windows (C1 = the repo's current 150/20 chunker)."""
    w = text.split()
    if len(w) <= size:
        return [" ".join(w)]
    out, start = [], 0
    while start < len(w):
        out.append(" ".join(w[start:start + size]))
        start += size - overlap          # same as repo: keeps a short tail window
    return out

_HEAD = re.compile(r"^[A-Z0-9][^.!?:;]{2,70}$")

def is_heading(line, nxt):
    """Heuristic heading: short, no closing punctuation, not a wrapped sentence."""
    s = line.strip()
    if not s or not _HEAD.match(s) or len(s.split()) > 9:
        return False
    if s.endswith(",") or s.lower().startswith(("and ", "or ", "the ", "to ", "of ")):
        return False
    return bool(nxt.strip())

def blocks_by_heading(text):
    """Split a page-window document into (heading, body) blocks; unwrap hard line breaks."""
    lines = text.splitlines()
    blocks, head, body = [], "", []
    for i, ln in enumerate(lines):
        nxt = lines[i + 1] if i + 1 < len(lines) else ""
        if is_heading(ln, nxt):
            if body:
                blocks.append((head, " ".join(body)))
            head, body = ln.strip(), []
        elif ln.strip():
            body.append(ln.strip())
    if body:
        blocks.append((head, " ".join(body)))
    return blocks

_SENT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(])")

def chunk_structural(text, max_words=200, min_words=40):
    """C3: heading-aware packing. Each chunk = 'heading: body', never cuts mid-sentence,
    merges small sections, splits big ones by sentence."""
    chunks, cur, cur_head = [], [], ""
    def flush():
        nonlocal cur
        if cur:
            body = " ".join(cur)
            chunks.append(f"{cur_head}: {body}" if cur_head else body)
            cur = []
    for head, body in blocks_by_heading(text):
        sents = []
        for s in _SENT.split(body):          # hard cap: split run-on "sentences" (lists)
            ws = s.split()
            sents += [" ".join(ws[i:i + max_words]) for i in range(0, len(ws), max_words)] or [s]
        if cur and (len(" ".join(cur).split()) >= min_words):
            flush()
        if not cur:
            cur_head = head
        elif head:
            cur.append(f"{head}:")
        for s in sents:
            if cur and len(" ".join(cur + [s]).split()) > max_words:
                flush()
                cur_head = head
            cur.append(s)
    flush()
    return [c for c in chunks if c.split()]

def build_chunks(docs, variant):
    fn = {"c1": lambda t: chunk_fixed(t, 150, 20),
          "c2": lambda t: chunk_fixed(t, 300, 50),
          "c3": lambda t: chunk_structural(t, 200, 40)}[variant]
    rows = []
    for doc_id, text in docs.items():
        for i, c in enumerate(fn(text)):
            rows.append({"chunk_id": f"{doc_id}::{variant}::{i:03d}", "doc_id": doc_id,
                         "variant": variant, "chunk_index": i, "text": c})
    return rows

# ---------------------------------------------------------------- page tagging (for citations)
_TOK = re.compile(r"[a-z0-9$]+")
def _shingles(text, n=6):
    t = _TOK.findall(text.lower())
    return {" ".join(t[i:i + n]) for i in range(max(0, len(t) - n + 1))}

def tag_pages(chunks, doc_pages, page_text):
    """Attach the PDF page numbers each chunk's text comes from (searching only its doc's pages)."""
    cache = {}
    for ch in chunks:
        cand = doc_pages.get(ch["doc_id"], [])
        s = _shingles(ch["text"])
        hits = []
        for p in cand:
            if p not in cache:
                cache[p] = _shingles(page_text[p - 1])
            if s and len(s & cache[p]) / len(s) >= 0.15:
                hits.append(p)
        ch["pages"] = hits or cand[:1]
    return chunks

# ---------------------------------------------------------------- BM25
def tokenize(text):
    return re.findall(r"\b\w+\b", text.lower())


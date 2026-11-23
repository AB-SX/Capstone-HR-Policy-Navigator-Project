"""Build the retrieval artefacts the app loads at startup, and load Pinecone.

    python -m scripts.build_index                 # variant/namespace from config/settings.yaml
    python -m scripts.build_index --variant c1 --namespace v2-c1
    python -m scripts.build_index --no-pinecone   # local files only (FAISS fallback works offline)

Writes data/index/<variant>/{chunks.jsonl, vectors.npy, manifest.json}. These ship in the Docker image.
Embeddings are cached in data/lab/embedding_cache*.npz (shared with the Step 3 lab), so re-runs are free.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src import config  # noqa: E402
from src.llm.client import Embedder  # noqa: E402
from src.retrieval.chunking import build_chunks, load_docs, tag_pages  # noqa: E402


def sha1(t: str) -> str:
    return hashlib.sha1(t.encode("utf-8")).hexdigest()


def embed_with_cache(texts: list[str], provider: str) -> np.ndarray:
    cache_f = config.LAB_DIR / ("embedding_cache.npz" if provider == "api" else f"embedding_cache_{provider}.npz")
    cache = dict(np.load(cache_f)) if cache_f.exists() else {}
    todo = [t for t in dict.fromkeys(texts) if sha1(t) not in cache]
    print(f"embeddings: {len(texts) - len(todo)} cached, {len(todo)} to embed ({provider})")
    if todo:
        emb = Embedder(provider)
        step = 256
        for i in range(0, len(todo), step):
            batch = todo[i:i + step]
            for attempt in range(4):
                try:
                    vecs = emb.embed(batch)
                    break
                except Exception as ex:                       # 429/503 from the shared endpoint
                    if attempt == 3:
                        raise
                    wait = 2 ** (attempt + 1)
                    print(f"  retry in {wait}s: {type(ex).__name__}")
                    time.sleep(wait)
            for t, v in zip(batch, vecs):
                cache[sha1(t)] = np.asarray(v, dtype=np.float32)
            np.savez(cache_f, **cache)
            print(f"  {min(i + step, len(todo))}/{len(todo)}")
    M = np.stack([cache[sha1(t)] for t in texts]).astype(np.float32)
    return M / np.maximum(np.linalg.norm(M, axis=1, keepdims=True), 1e-12)


def upsert_pinecone(chunks, M, namespace, rebuild):
    from pinecone import Pinecone, ServerlessSpec
    pc = Pinecone(api_key=config.PINECONE_API_KEY)
    name = config.PINECONE_INDEX_NAME
    if name not in pc.list_indexes().names():
        print("creating Pinecone index", name)
        pc.create_index(name=name, dimension=config.EMBEDDING_DIMENSIONS, metric="cosine",
                        spec=ServerlessSpec(cloud="aws", region="us-east-1"))
        while not pc.describe_index(name).status["ready"]:
            time.sleep(2)
    index = pc.Index(name)

    def count():
        ns = (index.describe_index_stats().namespaces or {}).get(namespace)
        return 0 if ns is None else ns.vector_count

    if rebuild and count():
        index.delete(delete_all=True, namespace=namespace)
        while count():
            time.sleep(2)
    if count() == len(chunks):
        print(f"pinecone {namespace}: already has {len(chunks)} vectors")
        return
    for i in range(0, len(chunks), 100):
        index.upsert(namespace=namespace, vectors=[
            {"id": c["chunk_id"], "values": M[i + j].tolist(),
             "metadata": {"doc_id": c["doc_id"], "variant": c["variant"], "pages": [str(p) for p in c["pages"]]}}
            for j, c in enumerate(chunks[i:i + 100])])
    t0 = time.time()
    while count() < len(chunks):                       # writes become searchable after a short delay
        if time.time() - t0 > 180:
            raise TimeoutError(f"{namespace}: only {count()}/{len(chunks)} searchable after 180 s")
        time.sleep(2)
    print(f"pinecone {namespace}: {count()} vectors searchable")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", default=config.setting("retrieval.variant", "c3"))
    ap.add_argument("--namespace", default=None)
    ap.add_argument("--no-pinecone", action="store_true")
    ap.add_argument("--rebuild", action="store_true", help="delete the namespace first")
    a = ap.parse_args()
    ns = a.namespace or (config.setting("retrieval.namespace") if a.variant == config.setting("retrieval.variant")
                         else f"v2-{a.variant}")
    provider = (os.getenv("EMBEDDING_PROVIDER") or config.setting("embedding.provider", "local")).lower()

    docs = load_docs(config.PROCESSED_DATA_DIR)
    pages = json.loads((config.PROCESSED_DATA_DIR / "pdf_pages.json").read_text(encoding="utf-8"))
    doc_pages = json.loads((config.PROCESSED_DATA_DIR / "doc_page_map.json").read_text(encoding="utf-8"))["doc_pages"]
    chunks = tag_pages(build_chunks(docs, a.variant), doc_pages, pages)
    print(f"{len(docs)} docs -> {len(chunks)} chunks ({a.variant})")

    M = embed_with_cache([c["text"] for c in chunks], provider)
    out = config.INDEX_DIR / a.variant
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "chunks.jsonl", "w", encoding="utf-8") as f:
        for c in chunks:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    np.save(out / "vectors.npy", M)
    manifest = {"variant": a.variant, "chunks": len(chunks), "dim": int(M.shape[1]), "embedding_provider": provider,
                "embedding_model": config.EMBEDDING_MODEL, "namespace": ns,
                "built": time.strftime("%Y-%m-%d %H:%M:%S"),
                "chunks_sha1": sha1("".join(c["chunk_id"] + c["text"] for c in chunks))}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print("wrote", out)
    if not a.no_pinecone:
        upsert_pinecone(chunks, M, ns, a.rebuild)


if __name__ == "__main__":
    main()

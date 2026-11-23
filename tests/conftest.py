import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config  # noqa: E402
from src.retrieval import policy_search as ps  # noqa: E402
from src.retrieval.chunking import build_chunks, load_docs  # noqa: E402


class FakeEmbedder:
    def embed(self, texts):
        out = []
        for t in texts:
            v = np.zeros(384)
            for w in ps.tokenize(t):
                v[int(hashlib.md5(w.encode()).hexdigest(), 16) % 384] += 1
            out.append((v / (np.linalg.norm(v) or 1)).tolist())
        return out


class FakeCE:
    def predict(self, pairs, **_):
        return np.array([len(set(ps.tokenize(q)) & set(ps.tokenize(t))) / 10 for q, t in pairs])


class DownPinecone:
    def query(self, **_):
        raise ConnectionError("pinecone down")


@pytest.fixture(scope="session")
def fake_engine(tmp_path_factory):
    d = tmp_path_factory.mktemp("index")
    docs = dict(list(load_docs(config.PROCESSED_DATA_DIR).items())[:40])
    chunks = build_chunks(docs, "c3")
    for c in chunks:
        c["pages"] = [1]
    (d / "c3").mkdir()
    with open(d / "c3" / "chunks.jsonl", "w", encoding="utf-8") as f:
        for c in chunks:
            f.write(json.dumps(c) + "\n")
    np.save(d / "c3" / "vectors.npy", np.array(FakeEmbedder().embed([c["text"] for c in chunks]), dtype=np.float32))
    old = config.INDEX_DIR
    config.INDEX_DIR = d
    eng = ps.PolicySearch(variant="c3", reranker="minilm-l6", backend="pinecone", embedder=FakeEmbedder(),
                          pinecone_index=DownPinecone(), cross_encoder=FakeCE())
    eng.min_score = 0.15
    ps._engine = eng                                   # policy_search() now uses the fake engine
    yield eng
    config.INDEX_DIR = old
    ps._engine = None

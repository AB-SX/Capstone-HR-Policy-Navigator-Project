"""Central configuration: secrets from .env, tunables from config/settings.yaml.

Every module imports from here, so a value is defined exactly once.
Old constant names (QWEN_API_KEY, CHUNK_SIZE, ...) are kept so the Week 1/2 code still runs.
"""
from __future__ import annotations

import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

# ----------------------------------------------------------------- paths
DATA_DIR = PROJECT_ROOT / "data"
RAW_DATA_DIR = DATA_DIR / "raw"
PROCESSED_DATA_DIR = DATA_DIR / "processed"
EVAL_DIR = DATA_DIR / "evaluation"
INDEX_DIR = DATA_DIR / "index"            # built artefacts shipped in the Docker image
LAB_DIR = DATA_DIR / "lab"                # local scratch (embedding cache), git-ignored
RUNTIME_DIR = Path(os.getenv("HRNAV_RUNTIME_DIR", PROJECT_ROOT / "runtime"))   # sqlite, logs (Docker volume)
for _d in (LAB_DIR, RUNTIME_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# ----------------------------------------------------------------- tunables
with open(PROJECT_ROOT / "config" / "settings.yaml", encoding="utf-8") as _f:
    SETTINGS: dict = yaml.safe_load(_f)


def setting(path: str, default=None):
    """setting('retrieval.top_out') -> value; env var HRNAV_RETRIEVAL__TOP_OUT overrides."""
    env_key = "HRNAV_" + path.upper().replace(".", "__")
    if env_key in os.environ:
        raw = os.environ[env_key]
        try:
            return yaml.safe_load(raw)
        except yaml.YAMLError:
            return raw
    node = SETTINGS
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return default
        node = node[part]
    return node


# ----------------------------------------------------------------- endpoints / secrets
def _ca_bundle():
    """TLS trust for the course endpoint: its private CA (certs/vm04-ca.crt) instead of verify=False."""
    p = os.getenv("COURSE_CA_CERT", str(PROJECT_ROOT / "certs" / "vm04-ca.crt"))
    if os.getenv("COURSE_TLS_INSECURE") == "1":
        return False                      # last resort; documented as an accepted risk
    return p if Path(p).exists() else False


COURSE_TLS_VERIFY = _ca_bundle()

QWEN_API_KEY = os.getenv("QWEN_API_KEY")
QWEN_BASE_URL = os.getenv("QWEN_BASE_URL", "https://103.42.50.41:1034/v1")
MODEL_NAME = os.getenv("QWEN_MODEL", "Qwen/Qwen3-8B")
MODEL_MAX_LEN = int(setting("llm.max_model_len", 8192))

EMBEDDING_API_KEY = os.getenv("EMBEDDING_API_KEY")
EMBEDDING_BASE_URL = os.getenv("EMBEDDING_BASE_URL", "https://103.42.50.41:1035/v1")
EMBEDDING_MODEL = setting("embedding.model", "bge-small-en-v1.5")
EMBEDDING_DIMENSIONS = int(setting("embedding.dim", 384))
EMBEDDING_MAX_BATCH_SIZE = int(setting("embedding.batch", 16))

PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
PINECONE_INDEX_NAME = os.getenv("PINECONE_INDEX", "hr-policy-navigator")

# ----------------------------------------------------------------- legacy names (Week 1/2 code)
TEMPERATURE = 0.2
MAX_TOKENS = 512
TOP_P = 0.8
ENABLE_THINKING = False
CHUNK_SIZE = 150
CHUNK_OVERLAP = 20
TOP_K = int(setting("retrieval.top_out", 5))
RATE_LIMIT_PER_MINUTE = int(setting("api.rate_limit_per_minute", 10))
EVAL_DATA_PATH = EVAL_DIR / "gitlab_eval_questions.json"
EVAL_V11_PATH = EVAL_DIR / "gitlab_eval_questions_v1_1.json"

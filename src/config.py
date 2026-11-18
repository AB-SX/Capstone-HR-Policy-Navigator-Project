import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# -------------------------------------------------
# Paths
# -------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_DATA_DIR = PROJECT_ROOT / "data" / "raw"
PROCESSED_DATA_DIR = PROJECT_ROOT / "data" / "processed"
EVAL_DATA_PATH = PROJECT_ROOT / "data" / "evaestions.json"

# -------------------------------------------------
# LLM API Settings (Qwen/Qwen3-8B)
# -------------------------------------------------
QWEN_API_KEY = os.getenv("QWEN_API_KEY")
QWEN_BASE_URL = os.getenv("QWEN_BASE_URL", "h1")
MODEL_NAME = "Qwen/Qwen3-8B"

# ---------------------------------------------------------------------------
# Model Parameters
# ---------------------------------------------------------------------------
TEMPERATURE = 0.1
MAX_TOKENS = 512

# ---------------------------------------------------------------------------
# Embedding API Settings (bge-small-en-v1.5)
# ---------------------------------------------------------------------------
EMBEDDING_API_KEY = os.getenv("EMBEDDING_API_KEY")
EMBEDDING_BASE_URL = os.getenv("EMBEDDING_BASE_URL", "https://103.42.50.41:1035/v1")
EMBEDDING_MODEL = "bge-small-en-v1.5"
EMBEDDING_DIMENSIONS = 384
EMBEDDING_MAX_BATCH_SIZE = 16

# ---------------------------------------------------------------------------
# Pinecone Vector DB Settings
# ---------------------------------------------------------------------------
PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
PINECONE_INDEX_NAME = "hr-policy-navigator"

# -------------------------------------------------
# Retrieval Settings
# -------------------------------------------------
CHUNK_SIZE = 150
CHUNK_OVERLAP = 20
TOP_K = 5
RERANKER_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"

# -------------------------------------------------
# App Settings
# -------------------------------------------------
RATE_LIMIT_PER_MINUTE = 10
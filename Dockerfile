# HR Policy Navigator: Streamlit app + agents + local retrieval models in one image (ADR-005, ADR-007).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    HF_HOME=/opt/hf HRNAV_RUNTIME_DIR=/app/runtime TOKENIZERS_PARALLELISM=false
WORKDIR /app

# CPU-only torch first, so sentence-transformers doesn't pull the multi-GB CUDA build
RUN pip install --index-url https://download.pytorch.org/whl/cpu torch==2.5.1
COPY requirements.txt .
RUN pip install -r requirements.txt

# Bake the embedding model and reranker into the image: no downloads when the server starts
RUN python -c "from sentence_transformers import SentenceTransformer, CrossEncoder; \
SentenceTransformer('BAAI/bge-small-en-v1.5', device='cpu'); \
CrossEncoder('cross-encoder/ms-marco-MiniLM-L6-v2', device='cpu')"

COPY .streamlit/ .streamlit/
COPY config/ config/
COPY certs/ certs/
COPY src/ src/
COPY scripts/ scripts/
COPY data/index/ data/index/
COPY data/processed/ data/processed/

RUN useradd -m app && mkdir -p /app/runtime /app/data/lab && chown -R app /app/runtime /app/data/lab /opt/hf
USER app
ENV HF_HUB_OFFLINE=1
EXPOSE 8501
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8501/_stcore/health', timeout=4)"
CMD ["streamlit", "run", "src/app/navigator.py", "--server.port=8501", "--server.address=0.0.0.0"]

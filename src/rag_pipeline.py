import logging
import sys
from pathlib import Path

import httpx
import urllib3
from openai import OpenAI

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

sys.path.append(str(Path(__file__).resolve().parent))

from config import (
    QWEN_API_KEY,
    QWEN_BASE_URL,
    MODEL_NAME,
    TEMPERATURE,
    MAX_TOKENS,
    TOP_P,
    ENABLE_THINKING,
    TOP_K,
)
from prompts.templates import build_rag_prompt, SYSTEM_PROMPT
from retrieval.hybrid_search import HybridSearch


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

logger = logging.getLogger(__name__)


class RAGPipeline:

    def __init__(self):
        logger.info("Initializing RAG pipeline...")

        self.llm_client = OpenAI(
            api_key=QWEN_API_KEY,
            base_url=QWEN_BASE_URL,
            http_client=httpx.Client(verify=False),
            timeout=60.0,
            max_retries=3,
        )

        self.retriever = HybridSearch()

        logger.info("RAG pipeline ready")

    def retrieve(self, query: str, top_k: int = TOP_K) -> list:
        """Retrieve relevant chunks for a query."""
        return self.retriever.query_hybrid(query, top_k=top_k)

    def generate(self, prompt: str) -> str:
        """Send prompt to Qwen and get response."""
        extra_params = {}
        if not ENABLE_THINKING:
            extra_params["extra_body"] = {"enable_thinking": False}

        response = self.llm_client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=TEMPERATURE,
            max_tokens=MAX_TOKENS,
            top_p=TOP_P,
            **extra_params,
        )

        return response.choices[0].message.content.strip()

    def answer(self, query: str, top_k: int = TOP_K) -> dict:
        """Full RAG pipeline: retrieve → build prompt → generate answer."""

        logger.info("Query: %s", query)

        chunks = self.retrieve(query, top_k=top_k)
        logger.info("Retrieved %s chunks", len(chunks))

        prompt = build_rag_prompt(query, chunks)

        answer = self.generate(prompt)
        logger.info("Answer generated")

        return {
            "query": query,
            "answer": answer,
            "sources": [
                {"source": c["source"], "score": c["score"]}
                for c in chunks
            ],
            "num_chunks": len(chunks),
        }

    def close(self):
        """Clean up resources."""
        self.retriever.close()
        self.llm_client.close()
        
if __name__ == "__main__":

    pipeline = None

    try:
        pipeline = RAGPipeline()

        test_queries = [
            "What is the home office stipend for new hires?",
            "How long can a US employee continue COBRA coverage?",
            "What is the daily meal reimbursement limit when traveling?",
        ]

        for query in test_queries:
            print(f"\n{'='*60}")
            result = pipeline.answer(query)
            print(f"Q: {result['query']}")
            print(f"\nA: {result['answer']}")
            print(f"\nSources:")
            for s in result['sources']:
                print(f"  - {s['source']} (score: {s['score']:.4f})")

    finally:
        if pipeline:
            pipeline.close()
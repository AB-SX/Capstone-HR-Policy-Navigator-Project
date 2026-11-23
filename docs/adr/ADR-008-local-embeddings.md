# ADR-008: Embeddings run locally (BAAI/bge-small-en-v1.5)

| | |
|---|---|
| **Status** | Accepted (22 Nov 2026) |
| **Owner (role)** | RAG / retrieval |
| **Affects** | ADR-002, LLD 3, Docker image (ADR-007) |

## Context
- The Track B learner guide: *"Embeddings are not provided on these endpoints; a RAG project needs a separate embeddings service."*
- The Week 2 code called `https://103.42.50.41:1035/v1` for `bge-small-en-v1.5`. On 22 Nov that port returned **nothing** from AWS CloudShell, while port 1034 (Qwen3-8B) answered normally.

## Decision
- Run **the same model, `BAAI/bge-small-en-v1.5` (384-d, L2-normalised)**, locally with `sentence-transformers` on CPU, behind the existing `Embedder` interface (`embedding.provider: local`).
- Queries use the BGE retrieval instruction prefix (tested in the Step 3 lab, section 6).
- Chunk vectors are built once by `scripts/build_index.py`, cached, and shipped in the Docker image. At runtime only the *query* is embedded (a few ms on CPU).
- The `api` provider stays in the code, in case the course adds an embeddings endpoint.

## Consequences
- **Positive:** no dependency on a service that doesn't exist; vectors are identical in shape to the Week 2 design; no extra per-query network call.
- **Negative:** about 130 MB more in the Docker image; the model downloads from Hugging Face on first use, so it's downloaded at image build time.
- **Track B fit:** generation still uses only the hosted ≤8B endpoint. Embedding and reranking are small, non-generative, local models; the mentor already approved local rerankers (18 Nov email). We'll mention this at the next mentor call.

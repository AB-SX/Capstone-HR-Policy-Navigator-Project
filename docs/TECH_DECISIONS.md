# Technology decisions: what we use, why, and what else we considered

One row per component. Detail lives in the linked ADRs; dated reasons in `DECISION_LOG.md`.
Constraint that shapes everything (Track B): **generation only through the hosted Qwen3-8B endpoint** (8,192-token context, ≤1,024 output tokens, 1 active request per key, 60 req/min).

| Component | Chosen | Options considered | Why this one | Ref |
|---|---|---|---|---|
| LLM | Qwen/Qwen3-8B via course vLLM endpoint | n/a (fixed by Track B) | Mandated; thinking mode turned off (`enable_thinking=false`) to save tokens and keep JSON clean | brief, guide |
| LLM client | `openai` SDK + our wrapper (`src/llm/client.py`) | LangChain `ChatOpenAI`; raw `httpx` | One place for CA-cert TLS, 1-request lock, 429/503 retries, token budget, JSON repair and usage accounting; LangChain would hide these, raw httpx would mean reimplementing the SDK | DECISION_LOG |
| Structured output | `json_schema` constrained decoding + Pydantic validation + repair retry | prompt-only JSON; vLLM `guided_json`; native tool calls only | Smoke test: json_schema works (0.4 s). Constrained decoding is the brief's "core engineering content"; Pydantic gives an explicit contract; repair handles the rare miss | DECISION_LOG |
| Tool calling | Native OpenAI tool calls (vLLM hermes parser) + Pydantic argument validation | Hand-rolled JSON-action ReAct | Smoke test: native tool calls work; validation catches malformed args and feeds errors back to the model | ADR-003 |
| Orchestration | LangGraph (M2: router → planner → executor → critic → responder) | CrewAI, AutoGen, hand-rolled loop | Explicit state graph = the brief's "explicit planner→executor→critic loop"; built-in checkpointer (persistent state) and `interrupt` (human-in-the-loop); first-class LangSmith tracing. CrewAI/AutoGen are role-chat abstractions with less control over loop caps and state | ADR-003 |
| Single-agent baseline | M1: one tool-calling agent, same tools | n/a | Gives the "single vs multi-agent" comparison the mentor asked for | ADR-003 |
| Corpus | GitLab HR handbook (1,338 pp → 502 docs) | Indian company manuals | Public and shareable; Indian manuals had licensing doubts and were too small | ADR-001 |
| Chunking | Chosen from C1 fixed-150 / C2 fixed-300 / C3 heading-aware by the Step 3 lab | n/a (experiment) | Brief requires chunking experiments; choice made on strict recall@k | ADR-002 |
| Sparse retrieval | BM25 (`rank-bm25`, in-process) | Pinecone sparse vectors; Elasticsearch | Exact-term matching (amounts, product names); in-process = no extra service | ADR-002 |
| Embeddings | `BAAI/bge-small-en-v1.5`, local, sentence-transformers | Course endpoint (doesn't exist); OpenAI/Cohere APIs | Learner guide: no embeddings endpoint; external APIs add cost and keys; same model as Week 2 | ADR-008 |
| Vector store | Pinecone serverless (free, `us-east-1`) + FAISS fallback | FAISS only; pgvector; OpenSearch | One shared managed index for team and deployment; FAISS guarantees it works offline or if Pinecone fails; mentor approved | ADR-002 |
| Fusion | Reciprocal Rank Fusion (k=60) | Weighted score sum; Pinecone hybrid alpha | Rank-based, so no score calibration between BM25 and cosine; keeps ablations clean | ADR-002 |
| Reranker | Cross-encoder, bge-reranker-base vs ms-marco-MiniLM-L6-v2 (lab decides) | LLM-as-reranker; none | Mentor suggestion; cross-encoders are cheap and accurate; an LLM reranker would spend scarce Qwen calls | ADR-002 |
| Evaluation | Own harness: LLM-as-judge + deterministic rule, failure taxonomy | RAGAS; DeepEval | Brief needs specific metrics (completion rate, tool calls, cost/latency, our 4-way taxonomy); judge-vs-rule agreement requested by mentor; RAGAS would need extra LLM calls per metric | brief V |
| Tracing | LangSmith | Langfuse; OpenTelemetry | Required by brief V. Zero-code with LangGraph; free tier; PII redacted before tracing. Langfuse self-host = heavy infra; OTel needs a separate viewer | ADR-009 |
| Guards | Own regex/checksum PII redaction, injection patterns, citation + number grounding check | Presidio; LLM guard models | Deterministic, fast, testable, no extra model calls; covers our domain's IDs (PAN, Aadhaar, cards) | ADR-006 |
| API | FastAPI | Flask; Streamlit-only | Async, pydantic models, OpenAPI docs; one container serves API + UI | ADR-005 |
| UI | React (brief: "Streamlit or React"); Streamlit kept for dev | Plain HTML; Chainlit; Backstage | Browser `localStorage` history (mentor's idea) is natural in React; plain HTML breaks the brief | ADR-005 |
| Rate limit + cache | In-process token bucket + TTL cache | Redis | One container on one instance; Redis adds a service for no gain at demo scale | ADR-007 |
| Deployment | AWS EC2 (Sydney) + Docker | ECS Fargate; Lightsail; App Runner | Same compose file locally and on AWS; SQLite checkpoints survive restarts on EBS; cheapest; region fixed by the new AWS sign-up | ADR-007 |
| Python toolchain | Python 3.12 in a `uv`-managed venv | System 3.14 with loosened pins; python.org 3.12 installer | Matches the Docker image; all pins have wheels; leaves the laptop's 3.14 untouched | DECISION_LOG |

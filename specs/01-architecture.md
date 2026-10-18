# 01 · Architecture

## 1. Component view

```
┌────────────┐   HTTPS/SSE   ┌─────────────────────────────┐
│  Frontend  │──────────────▶│  FastAPI (api/)              │
│ React+Vite │◀──────────────│   → application/              │
└────────────┘   JSON/SSE    │      → domain/ (pure)         │
                              │      ← infrastructure/        │
                              │   agent/ (ADK Agent + tools)  │
                              └───────┬──────────┬────────────┘
                                      │          │
                         ┌────────────▼──┐   ┌───▼─────────────┐
                         │ PostgreSQL     │   │ LLM provider     │
                         │ + pgvector     │   │ Gemini | Ollama  │
                         │ (ADK sessions, │   │ (LiteLLM)        │
                         │ leads, kb_chunks,│  └──────────────────┘
                         │ handoffs, ...) │
                         └────────────────┘
                                      │
                              ┌───────▼────────┐
                              │ OTel → Langfuse │
                              └─────────────────┘
```

## 2. Backend layers

`backend/src/asesor/{api,application,domain,agent,infrastructure}` (full structure in `00-master-build.md` §3).

- **Dependency rule:** `api → application → domain ← infrastructure`. `domain` imports neither ADK, FastAPI, nor SQLAlchemy — it's `Protocol`s and pure entities, testable with no network or DB.
- **`agent/`** depends on `application` (it calls the same services `api/` uses), never the other way around: the tools are thin adapters that translate LLM arguments into service calls and the result into an envelope (spec 03).
- **`application/`** orchestrates use cases (`ChatService`, `LeadService`, `HandoffService`, `KnowledgeService`, `TitleService`, `EvaluationService`) against the ports defined in `domain/` or, for the simpler repositories, directly against their concrete SQL implementation.
- **`infrastructure/`** implements those ports: SQLAlchemy repositories, the pgvector retriever, embeddings and LLM adapters, telemetry, fault injection.

## 3. Key ports

The `Protocol` isn't centralized in `domain/ports.py` for everything: it lives there for `LeadRepository` (the first one, F2) and alongside the service that uses it for `HandoffRepository` (`application/handoff_service.py`) — decoupling paid off its cost in both cases because tests have replaced them with in-memory doubles since day one. The repositories added later (`session_titles`, `feedback`, `evaluations`) are injected by their concrete SQL class directly, with no intermediate `Protocol`: there's only one real implementation, and adding the interface wouldn't change how they're tested (they already use a "fake" class with the same duck-typed contract, spec 09).

| Port | Where the `Protocol` lives | Implementations | Used by |
|---|---|---|---|
| `LlmProvider` | (ADK's own signature, not ours) | Gemini (AI Studio/Vertex), Ollama via LiteLLM | `agent/`'s `Agent` factory, `TitleService`, `EvaluationService`, the compaction summarizer (spec 06 §2) |
| `EmbeddingsPort` | `domain/knowledge.py` | Gemini (`gemini-embedding-001`/`-2`), Ollama (`embeddinggemma`) | `KnowledgeService`, `scripts/ingest_kb.py` |
| `LeadRepository` | `domain/ports.py` | `SqlLeadRepository` | `LeadService` |
| `HandoffRepository` | `application/handoff_service.py` | `SqlHandoffRepository` | `HandoffService` |
| `SqlSessionTitleRepository`, `SqlFeedbackRepository`, `SqlEvaluationRepository` | no `Protocol`, concrete class | (themselves) | `TitleService`, the feedback router, `EvaluationService` |
| `KnowledgeRetriever` | `domain/knowledge.py` | pgvector HNSW cosine (`PgVectorRetriever`) | `KnowledgeService` |

`Settings` (`config.py`) validates invalid provider combinations at startup (e.g. `EMBEDDINGS_PROVIDER=ollama` with `LLM_PROVIDER` in a mode that doesn't support it) and fails fast with a clear message.

## 4. Flow of a chat turn

1. The frontend does `POST /api/v1/chat/stream {session_id, message}` with the `X-User-Id` header.
2. `api/` validates that the session belongs to the user (404 if not), opens a `trace_id`, and delegates to `ChatService`.
3. `ChatService` invokes `runner.run_async(...)` on the "Luis" `Agent`; the L1/L2 plugins run before the model (spec 07).
4. The `Agent` decides whether to call tools (`save_lead`, `request_human_handoff`, `search_knowledge_base`); each tool call goes through L3 and hits `application/`.
5. ADK events are mapped to SSE (`message.delta`, `tool.started/finished`, `lead.updated`, `hitl.confirmation_required`, `guardrail.triggered`, `error`) — full contract in spec 02.
6. When the turn closes: L4 reviews the output, latency/tokens are recorded (spec 08), and the event is persisted in the ADK session.

## 5. Why ADK (summary; detail in ADR-001)

`google-adk` provides `Runner`, `DatabaseSessionService`, event compaction, and native tool confirmation — it solves memory and HITL without reinventing that infrastructure, and it separates the decision-making core from the UI (an explicit requirement of the challenge). LangGraph was ruled out because of the greater integration effort with Postgres/HITL given the scope and timeline of the challenge; keeping n8n was ruled out because it doesn't satisfy "decoupled from the UI" nor allow for production-grade tests/observability.

## 6. Trade-offs and what to revisit at scale

| Decision | Accepted trade-off | Revisit if it scales |
|---|---|---|
| A single `Agent` with 3 tools | Simplicity, one prompt to maintain | If tools/domains grow, consider specialized ADK sub-agents with routing |
| Custom SSE over `run_async` instead of `adk api_server` | Full control over the HTTP contract and guardrails, but streaming maintenance is on us | Reconsider `api_server` if ADK stabilizes it and it covers tool confirmation + our own auth |
| A single Postgres instance (sessions + pgvector + our own tables) | One service to operate, simple transactions | Separate OLTP from vector storage (or use a dedicated vector store) if KB volume or RAG QPS grows a lot |
| ADK's `DatabaseSessionService` for memory | Reuses official compaction and scoping | If per-session event volume gets very high, revisit explicit retention/purge policies |
| ADK tool confirmation (experimental) for HITL | Less custom code if it works | Fallback already designed (ADR-002); if ADK never stabilizes it, the fallback becomes the primary path |
| Observability via Langfuse, no-op without keys | The app never depends on an external service to start | If alerting is required, add an extra exporter (e.g. Prometheus) without touching the domain |

## 7. Infrastructure

A single `docker-compose.yml` (db, backend, frontend; Ollama under the optional `local-llm` profile, which assumes an NVIDIA GPU). `backend` and `frontend` mount the source code and hot-reload, so `--build` is only needed when dependencies change. `Makefile` with `up`, `up-llm`, `rebuild`, `down`, `lint`, `typecheck`, `test`, `ingest-kb`, `migrate` targets. See spec 11 for the local-models profile.

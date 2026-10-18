# CLAUDE.md

Virtual automotive advisor — migrating an n8n workflow to Google ADK 2.x + FastAPI + React. Technical challenge (AI Engineer), due Friday 18-Sep-2026 15:00 (Peru time).

## Source of truth

After F0, **don't re-read `specs/prompts/00-master-build.md` in full**. Read `specs/` (numbered specs 00–11, `decisions/ADR-*.md`, `open-questions.md`) and this file. `PROGRESS.md` has the phase checklist.

## Operating rules

1. **Spec-Driven Development.** If the code diverges from a spec, update the spec in the same PR.
2. **One branch per phase** from `develop`: `feature/*`, `docs/*`, `fix/*`. Atomic conventional commits → `make lint typecheck test` green → PR to `develop` (what, why, how to test, ATs covered) → merge commit (no squash).
3. **Mandatory checkpoints:** end of F0 (already happened); blockers or decisions not covered by the specs (note them in `specs/open-questions.md` and ask); before merging `develop → main`.
4. **ADK 2.x is never written from memory.** Use the `google-agents-cli-adk-code`, `google-agents-cli-eval`, `google-agents-cli-observability` skills; verify every class/signature against the installed package before using it (document it in `specs/notes/adk-api.md`). Don't use the agents-cli scaffold.
5. **Confidentiality.** Nothing from `.local/` enters the history (already in `.gitignore`). Don't mention brands or companies from the hiring process.
6. **Languages.** Code, specs, and README are in English; the bot replies in whichever language the end user writes in — judged from their actual words, including on the first message — defaulting to Peru Spanish with informal "tú" only when that's genuinely unclear (e.g. a bare "hola"/"hi").
7. **Architecture.** `api → application → domain ← infrastructure`; `domain` has no ADK/FastAPI/SQLAlchemy imports; `agent` uses `application`. Detail in `specs/01-architecture.md`.

## Closed decisions (summary; detail in `specs/01-architecture.md` and `00-master-build.md` §2)

Python 3.12 + uv + FastAPI + Pydantic v2 + SQLAlchemy 2 async + Alembic + `google-adk>=2`. One `Agent` ("Luis") + 3 tools (`save_lead`, `request_human_handoff`, `search_knowledge_base`) + guardrail plugins. Custom SSE over `runner.run_async`. `LlmProvider`: Gemini (default) or Ollama/Gemma 4 via LiteLLM, env-only. ADK's `DatabaseSessionService` over Postgres + pgvector (`vector(768)`, HNSW cosine) for RAG. OTel → Langfuse (no-op without keys). Frontend React + Vite + TS strict + Tailwind, types from OpenAPI.

## Current status

**F0–F7 complete and merged to `develop`** (F8, local models, was moved up within F6). **F9** remains (README, diagrams, demo script, `v1.0.0` tag, P0) — the only blocker left for delivery.

**Still missing a GitHub remote and `gh auth login`**, so phase merges are done locally with `git merge --no-ff` and the merge commit's body serves as the PR description — see `specs/open-questions.md`.

## Local models

The project runs **with no API key at all**: agent `ollama_chat/gemma4:12b` with `OLLAMA_THINK=low` and a 32768 context, embeddings via `embeddinggemma:300m`. Gemini remains available by switching environment variables; both profiles are in `.env.example`.

**Everything inside Docker by default, nothing native.** `COMPOSE_PROFILES=local-llm` in `.env.example` makes `docker compose up -d` (with no flags) already include Ollama and pull the four models it needs — whoever clones the repo with just Docker doesn't need to install Ollama on their machine. The Ollama entries in the selector's catalog aren't declared by hand (`MODEL_CHOICES`): they're discovered live against `/api/tags` + `/api/show` when the backend starts (`infrastructure/llm/ollama_discovery.py`, spec 11 §3.1), with their real capabilities (thinking / tool use).

Before switching models, read `specs/decisions/ADR-003-modelos-locales.md`. The essentials: if `docker compose exec ollama ollama ps` doesn't say `100% GPU`, the model doesn't fit and latency multiplies — check both free VRAM **and** the WSL VM's RAM (`%USERPROFILE%\.wslconfig`).

## Commands

`make` isn't installed on Windows; the `Makefile` is the canonical interface (CI, Docker, Linux/macOS), and these are the direct equivalents:

```bash
cd backend && uv run ruff check . && uv run ruff format --check .   # lint
cd backend && uv run mypy                                          # typecheck
cd backend && uv run pytest                                        # tests
cd frontend && npm run typecheck && npm run build                  # frontend
docker compose exec backend uv run python scripts/ingest_kb.py     # KB ingestion (scripts/ and kb/ mounted into the backend)
docker compose up -d                                              # make up (hot reload; --build only if dependencies change)
```

Default ports **8090** (backend), **5190** (frontend), and **5490** (Postgres), deliberately outside the usual ones: it's normal to have other projects using 8000, 5173, and 5432. Changed via `BACKEND_PORT`, `FRONTEND_PORT`, and `POSTGRES_PORT`.

## Where to look for what

| Question | Spec |
|---|---|
| What changes from the n8n baseline | `specs/00-baseline-analysis.md` |
| Folder structure, layers, trade-offs | `specs/01-architecture.md` |
| Endpoints and SSE events | `specs/02-api-contract.md` |
| Contract for the 3 tools | `specs/03-tools.md` |
| Dialog state machine | `specs/04-dialog-state.md` |
| Agent instruction | `specs/05-agent-policy.md` |
| Sessions, memory, RAG | `specs/06-memory-rag.md` |
| Guardrails L1–L4, fallbacks, fault injection | `specs/07-guardrails.md` |
| Traces, metrics, feedback, evals | `specs/08-observability-feedback.md` |
| Acceptance tests | `specs/09-acceptance-tests.md` |
| What to cut if time runs short | `specs/10-priorities.md` |
| LLM/embeddings providers | `specs/11-llm-providers.md` |
| Why ADK and not LangGraph/n8n | `specs/decisions/ADR-001-framework.md` |
| Blockers and pending prerequisites | `specs/open-questions.md` |

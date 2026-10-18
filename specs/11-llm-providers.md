# 11 · LLM and embeddings providers

## 1. `LlmProvider` port

`domain/ports.py` defines the `Protocol`; two adapters in `infrastructure/llm/`:

| Adapter | Use | Selection |
|---|---|---|
| Gemini | Default | AI Studio or Vertex AI, based on `GOOGLE_GENAI_USE_VERTEXAI` |
| Ollama / Gemma 4 | Local (P2, spec 10) | Via LiteLLM, `LLM_PROVIDER=ollama` |

No model is hardcoded: `AGENT_MODEL`, `GUARDRAIL_MODEL`, `EVAL_MODEL`, `FALLBACK_MODEL` are mandatory environment variables (startup fails if they're missing while the corresponding provider is active). Gemini model IDs change frequently — they're verified against the current official documentation before being fixed in `.env.example`, never assumed from memory (gotcha #6, master prompt).

## 2. Gemini

- Two possible backends under the same adapter: AI Studio (`GOOGLE_API_KEY`) or Vertex AI (`GOOGLE_GENAI_USE_VERTEXAI=true` + GCP project credentials). `Settings` validates that the variables required for the chosen backend are present.
- No fixed `temperature` for `AGENT_MODEL` (spec 05 §3): Gemini 3.x recommends the default; low values can induce tool-calling loops.
- `gemini-embedding-2` doesn't accept `task_type` as an API parameter: the task instruction (e.g. "retrieval query" vs. "retrieval document") goes as text inside the embedding prompt, not as a structured argument.
- The free tier returns 429 fairly often under demo/testing load → exponential backoff + `FALLBACK_MODEL` (spec 07 §3) isn't optional, it's part of the expected happy path in development.

## 3. Ollama / Gemma 4 (moved up to F6, detail in ADR-003)

- Mandatory `ollama_chat/` prefix in LiteLLM (not `ollama/`): the `ollama/` prefix can produce tool-calling loops and ignore context in some models.
- `OLLAMA_API_BASE` via env, with no host default baked into the code (to support a container, a native host, or a GPU host).
- **Never `:latest`**, either for the server image (`docker-compose.yml`) or for the models (`AGENT_MODEL`, `GUARDRAIL_MODEL`, `FALLBACK_MODEL`, `EMBEDDINGS_MODEL`): a tag that points at "whatever's latest" can resolve to a different variant the next time someone spins the project back up, with a different size or capabilities — exactly the kind of silent incompatibility this project already ran into once with the Ollama image (ADR-003). The current fixed tags live in `.env.example` and `docker-compose.yml`.

## 3.1 Model catalog: Gemini by hand, Ollama discovered

`GET /api/v1/models` (spec 02) doesn't read a static catalog for Ollama. `infrastructure/container.py` builds the real catalog at startup:

- Entries that are **not** Ollama (typically the Gemini one) come from `MODEL_CHOICES` (JSON in env), unchanged from the original design.
- Ollama entries are **discovered**: `infrastructure/llm/ollama_discovery.discover_ollama_models` calls `GET /api/tags` (what's installed) and then `POST /api/show` for each model (its `capabilities`). Models without `"completion"` in `capabilities` are dropped — so `embeddinggemma` and any other embeddings-only model never show up in the chat selector, with no manually-maintained exclusion list needed.
- Any Ollama entry manually declared in `MODEL_CHOICES` is ignored: Ollama is either dynamic or it isn't, so the catalog never drifts out of sync with what the server actually has *pulled*.
- Every discovered option carries `supports_tools` and `supports_thinking`, taken literally from `capabilities` (`"tools"`, `"thinking"`). This isn't just informational for the UI (`ModelOption.supports_*`, badges in the selector): `build_base_model` only sends the `think` parameter to LiteLLM when the chosen option supports it, instead of always assuming it for the main model like before — sending it to a model without that capability returns a 400 "does not support thinking" (ADR-003).
- The selector's default model is the one matching `AGENT_MODEL`, whether declared by hand or discovered — not "the first one in the list," which under dynamic discovery depends on the order Ollama happens to report it in.
- If `OLLAMA_API_BASE` isn't configured, or Ollama doesn't respond at startup, the Ollama portion of the catalog is left empty (a warning log, the backend startup doesn't fail).
- Discovery runs **once, at backend startup**, not on every request to `/api/v1/models`: pulling a new model while the backend is already running doesn't make it appear on its own — it takes a restart (`docker compose restart backend`) for it to query `/api/tags` again.

**Adding a new local model — two different paths, don't mix them up:**

1. **Native Ollama** (the one using `OLLAMA_API_BASE=http://localhost:11434` from `.env.example` by default, and what this dev machine runs): `ollama pull <model>:<tag>` on the host, then `docker compose restart backend`. Doesn't touch any file in the repo — it's just for *this* installation.
2. **Ollama inside Docker** (the `local-llm` profile, for someone cloning the repo with no Ollama of their own): the model has to end up *pulled* inside the `ollama-models` volume so it's there next time someone brings the profile up. It's added to `OLLAMA_EXTRA_MODELS` in `.env` (a space-separated list, e.g. `mistral:7b llama3.1:8b`) — the `ollama-pull` job in `docker-compose.yml` downloads them alongside the four defaults. Neither `MODEL_CHOICES` nor `docker-compose.yml` ever needs to be touched: discovery (previous point) handles the rest.

## 4. `Embeddings` port

| Adapter | Model | Dimension |
|---|---|---|
| Gemini | `gemini-embedding-001` or `gemini-embedding-2` | projected/truncated to 768 |
| Ollama | `embeddinggemma` | 768 native |

768 was chosen because pgvector indexes (HNSW/IVFFlat) up to 2000 dimensions on the `vector` type, and 768 is compatible with both providers without needing two table schemas. Switching the embeddings provider requires a full re-ingestion (spec 06 §4): the startup check forces it if it detects a different `embedding_model` in `kb_chunks`.

## 5. Environment variables (summary)

`LLM_PROVIDER` (`gemini`|`ollama`), `GOOGLE_API_KEY`, `GOOGLE_GENAI_USE_VERTEXAI`, `AGENT_MODEL`, `GUARDRAIL_MODEL`, `EVAL_MODEL`, `FALLBACK_MODEL`, `OLLAMA_API_BASE`, `EMBEDDINGS_PROVIDER`, `EMBEDDINGS_MODEL`. Documented and commented in `.env.example` (F1).

# 00 · n8n baseline analysis

> Source: `.local/baseline_n8n.json` (workflow "Asesor Automotriz Virtual - Baseline Challenge"). This file is not versioned; this document paraphrases its content so the public repo doesn't depend on it.

## 1. n8n node → ADK component map

| n8n node | Type | ADK / custom component |
|---|---|---|
| `When chat message received` | `chatTrigger` | `POST /api/v1/chat/stream` (FastAPI + SSE) |
| `Postgres Chat Memory` | `memoryPostgresChat` (custom `sessionKey`, table `workflow.auto_chat_histories`) | ADK's `DatabaseSessionService` over Postgres (spec 06) |
| `Google Vertex Chat Model` | `lmChatGoogleVertex`, `gemini-1.5-pro`, `temperature 0.2` | `LlmProvider` port → Gemini adapter, model via `AGENT_MODEL` (spec 11) |
| `guardar_lead` | `toolCode` (inline JS) | `save_lead` tool, thin adapter over `LeadService` (spec 03) |
| `solicitar_contacto_humano` | `toolCode` (inline JS, ticket via `Math.random`) | `request_human_handoff` tool + `HandoffService` + ADK tool confirmation (specs 03, 04, ADR-002) |
| `base_conocimientos_autos` | `toolVectorStore` | `search_knowledge_base` tool (spec 03) |
| `PGVector Auto Knowledge` | `vectorStorePGVector`, table `workflow.rag_auto_knowledge` | pgvector on the same Postgres instance, table `kb_chunks` (spec 06) |
| `Google Vertex Embeddings` | `embeddingsGoogleVertex`, `text-embedding-004` | `Embeddings` port → Gemini adapter, `gemini-embedding-001`/`-2` (spec 11) |
| `AGENTE_LUIS` | `agent` (full system message, `retryOnFail`, `maxTries: 3`, `waitBetweenTries: 3000`) | ADK `Agent` "Luis" (spec 05) + exponential backoff in the LLM adapter (spec 07) |

## 2. Baseline instruction (faithful summary)

Sections of the original `systemMessage`: ROL (ROLE), VOZ (VOICE), SALUDO Y APERTURA (GREETING AND OPENING) (two variants: with/without name), GUARDAR DATOS DEL CONTACTO (SAVE CONTACT DATA), CONSULTA DE INFORMACIÓN (INFORMATION LOOKUP), DERIVACIÓN A ESPECIALISTA (HANDOFF TO A SPECIALIST), EL ARTE DE NO HOSTIGAR Y CONTINUIDAD (THE ART OF NOT PESTERING, AND CONTINUITY) (one question per turn, anti-loop, "just browsing"), LÍMITES Y SEGURIDAD (LIMITS AND SAFETY) (off-topic, jailbreak).

Canned phrases preserved verbatim (source of truth for specs 05 and 07) — these are the bot's actual Spanish replies, kept as-is since that's literally what the deployed bot says in Peru Spanish:
- Greeting without a name: *"Hola 👋 Soy Luis, tu asesor automotriz. ¿Con quién tengo el gusto?"*
- Greeting with a name: *"¡Hola [Nombre]! 👋 ¿En qué te puedo asesorar hoy con tu próximo auto?"*
- No data in the KB: *"Por el momento no cuento con el detalle técnico exacto sobre ese modelo, pero puedo anotarlo para que un especialista te dé el dato preciso 😊"*
- "Just browsing": *"¡Perfecto! Aquí estoy si quieres comparar modelos o resolver dudas 😊"*
- Off-topic: *"Mi especialidad es ayudarte a encontrar el auto ideal y resolver dudas sobre vehículos 😊 Cuéntame si te puedo guiar con algún modelo."*
- Jailbreak / injection: *"No puedo realizar esa acción 😊 ¿En qué te ayudo respecto a tu búsqueda de auto?"*

Business rules to preserve: one question per turn, anti-loop ("if a piece of data was already given, don't ask for it again"), no prices/quotes/stock, handoff on test drive / immediate purchase / dissatisfaction / out of scope.

## 3. Gaps verified against the JSON

1. **Discontinued models.** `modelName: "gemini-1.5-pro"` (Chat Model) and `modelName: "text-embedding-004"` (Embeddings) are no longer valid, current IDs in the Gemini API. → IDs are set only via env vars (`AGENT_MODEL`, `EMBEDDINGS` in spec 11) and verified against the official documentation before every phase.
2. **`sessionKey` with an unsafe fallback.** `"={{ $json.sessionId || 'session_default' }}"`: if the frontend doesn't send a `sessionId`, every conversation without one shares the same memory row — a history leak across users. → sessions are created explicitly by the backend (`POST /api/v1/sessions`), with no shared fallback (specs 02, 06).
3. **Code tools with no contract.** The `toolCode` blocks for `guardar_lead` and `solicitar_contacto_humano` declare no input schema (n8n infers the parameters from the LLM without validation), persist nothing real (the "save" is a `JSON.stringify` held in the node's own memory), and the ticket is generated with `"TICK-" + Math.floor(Math.random() * 90000 + 10000)` — not persistent, collision-prone, not auditable. → explicit Pydantic schemas, real persistence in `leads`/`handoffs`, ids from database PKs (spec 03).
4. **Field mismatch between the prompt and the code.** The `systemMessage` asks the model to save `canal_contacto`, but the `guardar_lead` code reads `session_id`, `nombre`, `tipo_vehiculo_interes`, `uso_principal`, `etapa` — `canal_contacto` is never used anywhere. On top of that, `session_id` (a technical identifier) is exposed as an argument the LLM is expected to fill in. → `session_id`/`user_id` are never LLM arguments: they arrive via `ToolContext` (spec 03).
5. **State never injected.** The prompt says *"If the context does NOT have a Name"* / *"If the context ALREADY has a Name"*, but no node ever assembles that context before the agent runs — the LLM has to infer it from the raw history, which breaks down once memory gets compacted or across sessions. → the lead record and the stage are explicitly injected into the instruction on every turn (specs 05, 06).
6. **HITL with no real loop.** `solicitar_contacto_humano` ends in the node's own `JSON.stringify`; there's no workflow pause, no human queue, and no user confirmation before it executes — the "ticket" never reaches anyone. → ADK tool confirmation + a `handoffs` table with statuses and admin endpoints (specs 03, 04, ADR-002).
7. **Guardrails by prompt only.** The LÍMITES Y SEGURIDAD instructions depend entirely on the model honoring them; there's no deterministic layer, no classifier, no output filter — vulnerable to jailbreak-instruction variations the model doesn't recognize. → L1–L4 (spec 07).
8. **Ungoverned RAG and memory.** `PGVector Auto Knowledge` has no visible ingestion process, similarity threshold, or source metadata; `Postgres Chat Memory` has no token limit or compaction; no traces, spans, or latency/token metrics anywhere. → idempotent ingestion + `RAG_MIN_SCORE` (spec 06), `EventsCompactionConfig` (spec 06), OTel + Langfuse (spec 08).
9. **`temperature: 0.2`.** Configured on the `lmChatGoogleVertex` node. It doesn't carry over cleanly to the Gemini 3.x family: Google recommends leaving the default (1.0); low values can induce tool-calling loops. Intentional, documented deviation, not a bug to replicate (spec 05).

## 4. What stays unchanged in substance

Luis's role and voice, the six canned phrases from section 2, the three tools (same purpose, new contract), the knowledge source (general automotive documentation via RAG), and the policy of never giving prices/quotes/stock.

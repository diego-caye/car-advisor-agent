# 03 · Agent tools

The tools are thin adapters in `agent/tools/`: they parse arguments with Pydantic, call an `application/` service, and return the common envelope. `session_id` and `user_id` are read from ADK's `ToolContext` — they are **never** parameters the LLM has to fill in (baseline gap #4, spec 00).

## 1. Common envelope

```json
{"status": "ok" | "no_results" | "error", "data": {...}, "error": {"code": str, "message": str, "retryable": bool}}
```
`data` is present if `status="ok"`/`"no_results"`; `error` is present if `status="error"`. A Pydantic validation error is caught and turned into `status="error"`, `error.code="VALIDATION_ERROR"` — the agent reads it and asks for the data naturally, never exposing the traceback.

## 2. `save_lead`

Partial upsert of the current `user_id`'s lead record (not the session's: the lead lives at the user level, spec 06).

**Input**
| Field | Type | Rule |
|---|---|---|
| `name` | `str?` | 1–80 characters |
| `phone` | `str?` | normalized to 9 Peruvian digits or E.164 |
| `email` | `EmailStr?` | |
| `preferred_channel` | `enum?` | `WHATSAPP \| CALL \| EMAIL \| CHAT` |
| `contact_consent` | `bool?` | required to be `true` if `phone` or `email` are sent in the same call; if not → `error.code=CONSENT_REQUIRED` and the contact data isn't persisted |
| `primary_use` | `enum?` | `CITY \| WORK \| FAMILY \| TRAVEL \| MIXED` |
| `vehicle_type_interest` | `enum?` | `SUV \| SEDAN \| HATCHBACK \| PICKUP \| VAN \| CROSSOVER \| OTHER` |
| `powertrain_interest` | `enum?` | `GASOLINE \| DIESEL \| HYBRID \| ELECTRIC \| LPG_CNG \| UNDEFINED` |
| `interest_level` | `enum?` | `LOW \| MEDIUM \| HIGH`, inferred by the LLM from conversational cues |
| `just_browsing` | `bool?` | `true` the first time the user says they're just browsing/comparing (spec 04). Not a lead field: it isn't persisted in `leads`, it's written to the session state (dialog state). It can be sent alone, with no other field |

All fields are optional (partial upsert: only what's sent gets updated). At least one field must be present, otherwise → `error.code=EMPTY_UPDATE` — `just_browsing=true` on its own counts as present and doesn't trigger that error.

**Behavior:** persists via `LeadService.upsert(user_id, ...)`; the **stage is recalculated in the domain** (state machine, spec 04) from the resulting lead — the LLM never assigns it directly. Returns `{status: "ok", data: {lead: {...}, stage: str}}` and the backend emits the `lead.updated` SSE event.

## 3. `request_human_handoff`

**Input**
| Field | Type | Rule |
|---|---|---|
| `reason` | `enum` | `TEST_DRIVE \| FORMAL_QUOTE \| IMMEDIATE_PURCHASE \| DISSATISFACTION \| OUT_OF_SCOPE` |
| `requirement_summary` | `str` | 10–500 characters |
| `preferred_channel` | `enum?` | same enum as `save_lead` |
| `urgency` | `enum?` | `LOW \| MEDIUM \| HIGH` |

**Behavior:**
1. Requires user confirmation before it executes — via ADK's native tool confirmation (`tool_context.request_confirmation`). The F3 spike confirmed it works over our SSE, so **no fallback is implemented**: see ADR-002.
2. **Idempotent per session:** at most one `OPEN` handoff per `session_id`, guaranteed by a partial unique index in Postgres (`WHERE status = 'OPEN'`) in addition to the service-level check. If one is already open, the tool doesn't create another: it returns the existing one with `ya_existia: true` and the agent communicates that ("you already have a request in progress").
3. Once confirmed, it creates the handoff in `OPEN` state (transitions `OPEN → IN_PROGRESS → CLOSED` are managed by `PATCH /api/v1/handoffs/{id}`, spec 02) and the dialog stage moves to `HANDED_OFF` (spec 04).
   If canceled, nothing is created and the stage reverts to the previous stage.
4. Returns `{status: "ok", data: {handoff_id, ticket, reason, status: "OPEN", ya_existia}}`. The `ticket` is `TICK-` plus the table's id with padding: persistent and auditable, unlike the baseline's `Math.random` (gap #3).

## 4. `search_knowledge_base`

Equivalent to the baseline's `base_conocimientos_autos` node, now with an explicit threshold and source.

**Input**
| Field | Type | Rule |
|---|---|---|
| `query` | `str` | 1–300 characters |
| `category` | `enum?` | `BODY_TYPES \| SEGMENTS \| POWERTRAIN \| TRANSMISSION \| FUEL_ECONOMY \| MAINTENANCE \| SAFETY \| USAGE \| GLOSSARY` |
| `top_k` | `int` | 1–8, default 4 |

**Behavior:** embeds `query` with the configured `Embeddings`, searches by cosine similarity in `kb_chunks` (filtering by `category` if given), and sorts by score. If the best score is below `RAG_MIN_SCORE` (env) → `status: "no_results"`, `data: null` — the agent uses the baseline's honest phrase (specs 05, 07). If there are results: `data: {"resultados": [{"chunk_id", "title", "category", "source", "score", "content"}]}`, of length `top_k`.

## 5. Tool guardrails (L3, see spec 07)

- Strict Pydantic validation before touching `application/` — any field outside its enum or range is rejected before it ever reaches the DB.
- `session_id`/`user_id` always come from `ToolContext`, never from the LLM.
- Maximum N tool calls per turn (env `MAX_TOOL_CALLS_PER_TURN`, default 4) — prevents loops; once exceeded, the next tool call returns `status: "error"`, `error.code=TOOL_CALL_LIMIT`.
- PII (`phone`, `email`) is masked in telemetry spans/logs (spec 08), never in the clear.

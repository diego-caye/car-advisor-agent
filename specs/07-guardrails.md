# 07 · Guardrails and fallbacks

## 1. Layers

| Layer | Where | What it does | Fails as |
|---|---|---|---|
| **L1 deterministic** | ADK plugin, before the model | Max message length, Unicode normalization, invisible/control characters, ES/EN injection patterns (e.g. "ignore your instructions," "reveal your prompt," "from now on you are," role tags like `system:`/`assistant:`, suspicious base64/hex blocks) | Match → canned jailbreak response **without calling the LLM**; SSE `guardrail.triggered {layer: L1, category}` |
| **L2 classifier** | **Not implemented (P1)** — see below | Planned design: `GUARDRAIL_MODEL` with structured output `{label: in_scope \| off_topic \| injection \| abuse, confidence}` | Short timeout (`GUARDRAIL_L2_TIMEOUT_MS`) → **fail-open** (lets it through) with a warning log — L4 still acts as an output-side safety net |
| **L3 tools** | Before running each tool | Pydantic validation, ids from `ToolContext`, `MAX_TOOL_CALLS_PER_TURN`, PII masked in spans (detail in spec 03 §5) | Rejection → `status: error` envelope returned by the tool to the agent |
| **L4 output** | After the model, before it reaches the user | Canary token leak → canned response; mentions of price/quote/stock/discount → safe message + handoff offer | Replaces the message; SSE `guardrail.triggered {layer: L4, category}` |

L1 runs on the incoming user message (L2 would run there too, once it exists); L3 runs on every tool call; L4 runs on the model's outgoing message, before it's streamed over SSE (applied to the full buffer, not to each delta, so nothing leaks before the leak is detected).

**Bilingual by design [NEW]:** since the agent now replies in whichever language the user writes in (spec 05 §"LANGUAGE"), L1's injection patterns and L4's pricing patterns each have both a Spanish and an English regex (e.g. `cuesta`/`costs`, `precio de lista`/`list price`), and the canned safe-reply substituted on a block (L1's jailbreak reply, L4's pricing/canary reply) is picked in the matching language via a small heuristic detector, `agent/language.py` — it looks at the blocked text itself (the user's message for L1, the model's flagged reply for L4), not at any stored per-session state.

**Actual status (verified against the code, F9):** only L1, L3, and L4 are implemented — matching `PROGRESS.md` F6 ("L2 classifier (P1) — not implemented; L1 + L4 cover the challenge's ATs"), not a new deviation. `agent/guardrails/plugin.py` documents this in its own docstring.

## 2. `guardrail.triggered` categories

**Emitted today** (verified against the code): `injection`/`too_long` from L1 (`agent/guardrails/l1.py`), `pricing_leak`/`canary_leak`/`pseudo_tool_call` from L4 (`agent/guardrails/l4.py`). `off_topic` and `abuse` belong to L2's design and aren't emitted yet — they depend on the classifier being implemented. Each maps to one of the baseline's canned phrases (jailbreak/off-topic) or to a new L4 message for `pricing_leak`/`canary_leak` (spec 05 §1, with a handoff offer).

## 3. Infrastructure fallbacks

| Failure | Path |
|---|---|
| Exception in a tool | `status: error` envelope; the agent explains it to the user without jargon (never exposes stack traces) |
| Model: 429 / 5xx / timeout | Exponential backoff, 3 attempts (replicates the baseline's `retryOnFail`/`maxTries: 3`) → if exhausted, retries once with `FALLBACK_MODEL` → if that also fails, a friendly message + SSE `error {code, message, retryable: true}` |
| RAG down (Postgres/pgvector not responding) | Same path as `search_knowledge_base` → `no_results`: the baseline's honest phrase, the turn doesn't break |
| DB down (session/lead) | 503 with `{code: UPSTREAM_UNAVAILABLE, retryable: true}` and a clear UI message; `/readyz` already reports it before the user even tries to chat |

## 4. Fault injection (demo)

With `ENABLE_FAULT_INJECTION=true` (only if `APP_ENV=dev`), the `X-Debug-Fault: tool_error | model_429 | model_timeout | rag_down` header on `POST /chat/stream` forces the corresponding failure **after** input guardrails run, so every fallback path can be demonstrated without depending on it happening organically. Selector in the frontend's dev panel (spec `docs/ui.md`). Ignored if `APP_ENV != dev`.

## 5. Environment variables

`GUARDRAIL_MODEL` (reserved for L2 once it's implemented; in the meantime, reused as the lightweight model by `TitleService` and the `EventsCompactionConfig` summarizer — spec 06 §2, spec 08 §5 — nothing to do with guardrails today), `GUARDRAIL_L2_TIMEOUT_MS`, `GUARDRAIL_CANARY_TOKEN`, `MAX_TOOL_CALLS_PER_TURN`, `FALLBACK_MODEL`, `ENABLE_FAULT_INJECTION`, `RAG_MIN_SCORE` (spec 06).

## 6. Fail-safe principle

L1 and L3 are deterministic and **fail-closed** (if something can't be validated, it's rejected). L2 is probabilistic and **fail-open** (an LLM outage shouldn't take down the chat) — which is why L4 exists as a second net over the output, not just L2 on the input.

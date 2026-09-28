# 08 · Observability and feedback

## 1. Pipeline

OpenTelemetry (Python SDK) + `openinference-instrumentation-google-adk` → OTLP exporter → Langfuse. Without `LANGFUSE_*` configured, the exporter falls back to no-op (`ConsoleSpanExporter` disabled or `NoOpTracerProvider`) — the app works the same, just without a trace backend. Missing telemetry never raises an exception.

## 2. Custom spans

| Span | Custom attributes | When |
|---|---|---|
| `guardrail.l1` | `matched: bool`, `category?` | on every incoming message |
| `guardrail.l2` | `label`, `confidence`, `timed_out: bool` | on every incoming message (if L1 didn't block it) |
| `guardrail.l4` | `matched: bool`, `category?` | on every outgoing response |
| `rag.retrieve` | `query`, `category?`, `top_k`, `best_score`, `result_count` | on every `search_knowledge_base` call |
| `hitl.request` | `reason`, `session_id` | when proposing `request_human_handoff` |
| `hitl.confirm` | `approved: bool` | when resolving the confirmation |
| `eval.judge` | `criterion`, `score` | for each criterion evaluated (spec §4) |

All are children of the turn span opened by `ChatService` (which carries the `trace_id`).

## 3. Per-turn data

- `trace_id` is created **before** invoking `runner.run_async` (never `run`: with `run` the OTel context doesn't reach the child spans — a master-prompt gotcha).
- Latency measured server-side (from receiving the POST to `message.completed`).
- Tokens in/out: sum of every LLM call in the turn (the agent **and** the L2 classifier, if it ran).
- Emitted in the `message.completed` SSE event (spec 02) and in a structured JSON log (`stdout`, one object per turn) so it can be grepped without depending on Langfuse.
- Span/log attributes: `session_id`, `user_id`, `provider` (gemini/ollama), `model`, `stage`, `guardrail_blocked: bool`, `hitl: bool`.
- PII (the lead's `phone`, `email`) is masked before entering any span or log (spec 03 §5) — never in the clear in Langfuse.

## 4. User feedback

`POST /api/v1/feedback {session_id, trace_id, score: 1 | -1, message, comment?}` → inserts into the `feedback` table **and** records a `user-feedback` score in Langfuse against the received `trace_id` (Langfuse allows attaching scores to an already-closed trace). If Langfuse isn't configured, only the table write happens — it's non-blocking. `message` (the text of the rated response) is stored denormalized in the row itself, so feedback can be listed without depending on the ADK history still having that event.

`GET /api/v1/feedback?limit=` (no token, unlike `/handoffs` — reason in spec 02) lists the most recent feedback first. The frontend consumes it in the dev panel ("Feedback" section): it loads on its own when the panel opens, and each row is clickable — it navigates to `/c/:session_id` for the conversation where that feedback was given, instead of being just a floating number with no context.

## 5. Post-execution evaluation (P1)

A background task (doesn't block the response to the user) that runs with `EVAL_MODEL`, sampled by `EVAL_SAMPLE_RATE` (env, 0–1), over a fraction of turns. Evaluates per turn:

| Criterion | What it measures |
|---|---|
| Empathetic tone | Consistency with Luis's VOICE (spec 05) |
| Brevity | 2–3 sentences, no heavy markdown |
| A single question | Doesn't stack several questions in one turn |
| No prices | Doesn't mention prices/quotes/stock/financing |
| Faithfulness to RAG context | If `search_knowledge_base` ran with results, the response doesn't contradict or invent beyond those chunks |

Persists to the `evaluations` table (`session_id`, `message_id`, criterion, score, short justification) and emits `quality.<criterion>` scores to Langfuse against the turn's `trace_id`. Never blocks or delays `message.completed`.

**Implemented in F7** (`EvaluationService`): a single call to the judge per turn (not one per criterion) that returns a JSON verdict per criterion; `fidelidad_rag` (RAG faithfulness) is only requested if the turn called `search_knowledge_base`. Scheduled as a `BackgroundTasks` call from within `_stream` (chat.py), once the turn's final text is known — not earlier, because unlike `title_service` it needs the result, not just the input message. A turn resumed via `chat/confirmations` (HITL) is never sampled: there's no fresh user message to evaluate there.

There's also an offline equivalent — a golden dataset of conversations (`backend/tests/evalset/`, the `evalset` type in spec 09) that runs against the real model with the same judge mechanism, plus tool trajectory and off-topic containment. This is the piece that "runs on-topic and off-topic conversations to check the agent doesn't stray from its script" — offline and on-demand, not sampled online like this mechanism.

## 6. Environment variables

`LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST`, `LANGFUSE_PROJECT_ID` (for the dev panel's link), `EVAL_MODEL`, `EVAL_SAMPLE_RATE`.

## 7. What to look at in Langfuse (for the README, F9)

The trace tree for a turn (agent → tools → guardrails), total latency vs. per-span latency, cumulative tokens in/out, the `user-feedback` score, and `quality.*` scores when evaluation ran.

# 10 · Priorities

Deadline: Friday 18-Sep-2026, 15:00 (Peru time). If time is short: cut P2 first, then P1; **never P0**.

## P0 — essential for the challenge

- Layered backend architecture, validated Settings, CI green (F1)
- "Luis" agent on ADK with `save_lead`, the state machine, Postgres sessions, SSE, base telemetry (F2)
- `request_human_handoff` with HITL (confirmation or fallback), handoffs, admin endpoints (F3)
- Real-time chat frontend connected via the API, end-to-end flow (F4)
- RAG (`search_knowledge_base`) with an ingested KB and RAG/no-data ATs (F5)
- L1 and L3 guardrails, tool/model/RAG/DB fallbacks, fault injection for the demo (F6; L2/L4 are P1 within this phase)
- README, diagrams, a 5–7 min video, specs kept in sync, `develop → main` PR, `v1.0.0` tag (F9)

## P1 — valuable, doesn't block the minimum delivery

- L2 (classifier) and L4 (output) guardrails — without them, L1+L3 already cover the challenge's direct-injection ATs
- User feedback (`POST /feedback`) and post-execution evaluation (F7)
- Explicit memory compaction via `EventsCompactionConfig` with tuned thresholds (without it, ADK still keeps memory, just without fine-grained token control)
- A runnable ADK evalset

## P2 — nice-to-have if time allows

- Local models (Ollama/Gemma 4) and their Docker overrides (F8, ADR-003)
- A handoff operator view in the UI (beyond the raw admin endpoints)
- Complete dev panel (fault injection is already minimally functional at P0; visual refinements are P2)
- A path to production on GCP (Cloud Run + Cloud SQL) — documented in the README only, not implemented

## Relationship to the rubric

| Rubric area | Weight | Phases covering it |
|---|---|---|
| SDD and prompting | 20% | F0, spec 05 |
| Agent architecture + UI | 25% | F1, F2, F4 |
| Harness (tools, HITL, guardrails, fallbacks) | 20% | F2, F3, F6 |
| Memory + RAG | 15% | F2, F5, F6 (spec 06) |
| UX | 10% | F4 |
| Observability | 10% | F2 (base), F7 (feedback/evals) |

Prioritizing P0 covers 100% of the rubric in its minimal form; P1 strengthens the harness and observability; P2 is a differentiator but its absence isn't penalized if time runs short.

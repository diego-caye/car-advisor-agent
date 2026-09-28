# ADR-001 · Framework for the decision-making core

## Status
Accepted

## Context

The challenge asks for an n8n automotive-advisory workflow to be migrated into code, with the decision-making core **decoupled from the UI** (a web chat UI consumes it via API), multi-turn memory per session/user in SQL, tools with an explicit contract, real HITL, guardrails/fallbacks, and observability for traces/latency/tokens. See the baseline's verified gaps in `../00-baseline-analysis.md`.

Options evaluated: **keep n8n** (with improvements), **Google ADK 2.x**, **LangGraph**.

## Options

### Keep n8n
- Quick to adjust (the workflow already exists).
- Doesn't cleanly satisfy "decoupled from the UI": n8n is workflow-first, not a library that can be embedded in a custom backend with domain unit tests.
- No typing, no automatable tests for the business logic, no fine-grained control over memory/compaction, limited native HITL, manual token/latency observability.
- Ruled out: doesn't meet the challenge's architecture, harness, and testing requirements.

### LangGraph
- Very flexible for custom state graphs, good observability ecosystem (LangSmith).
- Requires building by hand what ADK gives out of the box for this case: Postgres session persistence, event compaction, and tool confirmation for HITL — more custom surface area to maintain and test within the challenge's timeline.
- The integration curve with Postgres and with a confirmation mechanism equivalent to ADK's isn't as direct given the time available.
- Ruled out for this scope: greater integration effort with no clear advantage, given the challenge already uses the Google ecosystem (Gemini) and values a dedicated agent framework.

### Google ADK 2.x (chosen)
- `Runner` + `DatabaseSessionService` provide persistent memory on Postgres with no low-level custom code.
- `EventsCompactionConfig` solves history-size control without trimming `contents` by hand (avoids breaking Gemini 3's thought signatures in function calling).
- Native tool confirmation covers the primary HITL path (though experimental — mitigated with a fallback, see ADR-002).
- Integrates well with OpenTelemetry via `openinference-instrumentation-google-adk` → Langfuse.
- Accepted downsides: a relatively new package (the 2.x API changed from 1.x), some features (tool confirmation) are experimental, and it can't be written from memory — every signature is verified against the installed package (an operational rule of the project, not just of this decision).

## Decision

Google ADK 2.x for the decision-making core (the "Luis" `Agent` + 3 tools + guardrail plugins), with a custom FastAPI layer exposing SSE over `runner.run_async` (not `adk api_server`, to keep full control over the HTTP contract defined in `02-api-contract.md`).

## Consequences

- Every ADK class/signature used in the code (from F2 onward) is verified against the installed package before being written; documented in `specs/notes/adk-api.md`.
- Tool confirmation (experimental) starts with a short spike in F3; if it doesn't turn out stable over our own SSE, the fallback documented in ADR-002 is used without blocking the phase.
- If a future ADK 2.x version deprecates or breaks `DatabaseSessionService`/`EventsCompactionConfig`, the `LlmProvider` port and the `domain`/`agent` separation (spec 01) contain the blast radius: only `agent/` and `infrastructure/` should need to change, not `domain/` or `application/`.

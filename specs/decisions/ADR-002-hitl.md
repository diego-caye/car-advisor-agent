# ADR-002 · HITL mechanism

## Status
Accepted — primary path confirmed by a spike on 2026-09-15 (F3).

## Context

The challenge requires real HITL: interruption, handoff, and assisted confirmation (spec 03 §3, spec 04 §2). The n8n baseline had none of the three: its `solicitar_contacto_humano` ended in a `JSON.stringify` with a `Math.random` ticket, with no pause, no human queue, and no user confirmation (gap #6 of `00-baseline-analysis.md`).

`00-master-build.md` §8 flagged ADK's native tool confirmation as **experimental** and called for starting F3 with a short spike through our own SSE; if it didn't come out clean, we'd fall back to a custom mechanism (`pending_confirmation` in session state, the turn ending, and the UI creating the handoff on confirmation).

## Options

### A. Native ADK tool confirmation (chosen)
The tool calls `tool_context.request_confirmation(hint=..., payload=...)`. ADK pauses the turn and emits a synthetic `adk_request_confirmation` function call whose args carry `originalFunctionCall` and the `toolConfirmation` with our payload. To resume, a function response with role `user` is sent, with that same name and the confirmation call's id, and ADK re-executes the original tool with `tool_context.tool_confirmation` populated.

### B. Custom fallback
The tool leaves `pending_confirmation` in the session state and returns; the turn ends normally. `POST /chat/confirmations` creates the handoff directly from the service, without going back through the agent, and starts a new turn so the agent can communicate it.

## Spike

A custom `Runner` was set up with `InMemorySessionService`, a scripted `FakeAdkLlm`, and a handoff tool, running two turns:

1. **Turn 1.** The model calls `request_human_handoff`. The tool requests confirmation and returns. Observed: ADK emits the `adk_request_confirmation` function call with `originalFunctionCall` + `toolConfirmation` (including the payload with the reason and summary), the tool responds with `pendiente_de_confirmacion`, and **no handoff is created**.
2. **Turn 2.** The function response is sent with `confirmed=True` and the confirmation's id. Observed: ADK **re-executes the tool** with `tool_confirmation` populated, the tool creates the handoff, and the agent produces its closing text.

Result: the primary path works over our own SSE, without `adk api_server` and without touching the history by hand.

Requirement discovered during the spike: the `App` needs `resumability_config=ResumabilityConfig(is_resumable=True)`; without it the turn can't be resumed.

## Decision

**Option A.** No fallback is implemented: it would add a second code path for the same use case without solving anything the primary path doesn't already cover.

Translation into our contract (spec 02):
- `adk_request_confirmation` → SSE `hitl.confirmation_required {confirmation_id, reason, resumen, preferred_channel, urgency}`, where `confirmation_id` is that function call's id and the rest comes from the payload the tool chose.
- `POST /api/v1/chat/confirmations {session_id, confirmation_id, approved}` builds the function response and resumes the stream with the same events as a normal turn.
- Approving executes the tool and the stage moves to `HANDED_OFF`; canceling (`approved=false`) returns the stage to the previous stage and creates nothing.

## Consequences

- We depend on a feature ADK marks as experimental. The risk is bounded: AT-08, AT-09, and AT-10 cover all three paths (confirm, cancel, idempotent second request), so a regression on a version bump is caught in CI, not at the demo.
- The shape of the confirmation response (`name = adk_request_confirmation`, the call's id, `ToolConfirmation.model_dump()`) is an internal detail of ADK 2.9.1. It's isolated in `ChatService.resume_with_confirmation` and documented in `specs/notes/adk-api.md` §6, the only place to touch if it changes.
- Handoff idempotency doesn't come from ADK: it's a partial unique index in Postgres (`ux_handoffs_one_open_per_session`, `WHERE status = 'OPEN'`) plus the service's `open_or_get`, so two concurrent confirmations can't create two open tickets.
- If ADK ever pulled the feature, option B remains viable and the change point is localized; that's why it isn't discarded in this ADR, just not implemented today.

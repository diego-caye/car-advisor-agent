# Open questions

Blockers, decisions the specs don't fully cover, and prerequisites still pending from the human. These get resolved before the relevant phase needs them; they don't block F0.

## Prerequisites · status

Detected when starting F0 (2026-09-15) and updated when closing F1.

### Resolved

- **Git repository.** Initialized locally in F0 (`git init -b main`) with `main`, `develop`, and one branch per phase.
- **Python 3.12.** It does exist, though not on PATH: `uv` resolves `cpython-3.12.11`. The project pins it with `requires-python = ">=3.12,<3.13"` and `uv sync` picks it up automatically. Nothing else needs installing.
- **`google-adk`.** Installed and verified in F1: **2.9.1** (pinned exactly in `backend/pyproject.toml`), imports correctly under Python 3.12.11.
- **Gemini model IDs.** Confirmed against the official documentation on 2026-09-15 and fixed in `.env.example`: `gemini-3.8-flash` (agent), `gemini-3.5-flash-lite` (guardrail L2), `gemini-3.5-flash` (eval), `gemini-3.7-flash` (fallback, deliberately a different generation from the main one), `gemini-embedding-001` (768 dims, stable; `gemini-embedding-2-preview` is still in preview and is the one that doesn't accept `task_type`).
- **Docker, uv, Node.** Docker 29.8.0 / Compose v5.5.1, uv 0.10.12, Node 24.14.1.
- `.local/baseline_n8n.json` present and covered by `.gitignore`; the local `.env` was created in F1 and is also ignored (verified with `git check-ignore`).

### Open

- **`gh` CLI not installed** and no remote repo on GitHub. Phase merges are being done locally with `git merge --no-ff`, using the merge commit's body as the PR description (what, why, how to test, ATs covered). **Action for the human:** create the public repo, `gh auth login`, `git remote add origin ...`, and `git push` both `main` and `develop`. Without this, the GitHub Actions CI (`.github/workflows/ci.yml`) never runs, and the "public repo" deliverable stays pending.
- **ADK skills not installed** (`npx skills add google/agents-cli`). Needed at the start of F2 to verify ADK 2.x signatures.
- **A real `GOOGLE_API_KEY` — blocks F4's DoD.** The local `.env` has a placeholder that only satisfies the startup validation. With it, the backend returns `error` on every turn, so the only path exercisable in the browser is the failure path, not streaming, activity chips, and the HITL card. All of that is covered by tests against `FakeAdkLlm`, but F4's DoD calls for seeing it end-to-end in the browser, and the delivery video needs it too. It's also needed for real KB ingestion in F5 (embeddings).
- **GNU `make` isn't installed on Windows** (Chocolatey is). The `Makefile` is the canonical interface and works in CI, Docker, and Linux/macOS. On this machine the commands are run directly (`cd backend && uv run pytest`, etc.). **Optional:** `choco install make -y` from an elevated console.
- **Ports already in use on this machine.** Other containers of the user's already use 8000 and 5173. `docker-compose.yml` publishes configurable ports (`BACKEND_PORT`, `FRONTEND_PORT`, `POSTGRES_PORT`) and this machine's local `.env` moves them to 8008 and 5174. The repo's defaults stay at 8000/5173 for whoever clones it.

- **Another native Postgres on the host.** A `postgresql-x64-18` service is listening on 0.0.0.0:5432, so the project's container could only bind IPv6, and `localhost:5432` was hitting the native Postgres (authentication failed). The compose file now publishes `POSTGRES_PORT=5442` via `.env`. In CI and on a clean machine, the default stays 5432.

## Resolved in F2 (documented in `specs/notes/adk-api.md`)

- User-scope prefix: it's `user:` (there are also `app:` and `temp:`). Decision made: it's **not** used for the lead — the `leads` table is the single source of truth (spec 06 §1).
- `EventsCompactionConfig(token_threshold=..., event_retention_size=..., summarizer=...)`, verified. It's wired up; thresholds still need tuning with long conversations (F7).
- State injection into the instruction: `instruction` accepts a callable `(ReadonlyContext) -> str | Awaitable[str]`. That path is used instead of `{state_key}` placeholders, because the lead record is JSON and its braces collide with the templating.

## Still open for F3 and beyond

- Stability of ADK 2.x's native tool confirmation (`ToolContext.request_confirmation`, `EventActions.requested_tool_confirmations` — both exist) over our SSE streaming. F3 spike and ADR-002.
- Whether the ADK 2.x SDK exposes a "thinking" level configurable via env for the agent's model (spec 05 §3). Not investigated in F2: it doesn't block anything, it's a latency optimization.
- `App(name=...)` has to match the agent's directory for `adk eval` to find the sessions. Our structure doesn't follow ADK's directory convention; revisit when setting up the evalset in F7.

## Found during the F9 spec↔code sync

- **`just_browsing` was never actually triggered — resolved.** The flag existed end-to-end (canned phrase, injected into the instruction) but no code ever wrote it. The human chose to close this before delivery: `save_lead` gained an optional `just_browsing: bool` field that writes `SOLO_MIRANDO_KEY` to the session state (the same pattern already used for the stage), with a real AT-05 (`test_at_agent_core.py`) and verified live against the real model.
- **`GUARDRAIL_MODEL` has nothing to do with any guardrail.** The name suggests the L2 classifier (never implemented, still P1), but in the real code that model is used by `TitleService` and the `EventsCompactionConfig` summarizer (spec 06 §2) — the variable's name drifted from its actual use. It wasn't renamed in F9 given the cost of touching `config.py`/`.env.example`/`docker-compose.yml`/tests days before delivery; documented in spec 07 §5 and here for whoever picks this up.

## Other open decisions, non-blocking

- Exact format of `ADMIN_TOKEN` (a simple static bearer vs. something more elaborate) — defined in F3 alongside the admin endpoints; a static env-based bearer is enough for the challenge's scope.
- Peruvian phone-number normalization library vs. E.164 — defined in F2 while implementing `save_lead`; probably a simple custom function, no new dependency.

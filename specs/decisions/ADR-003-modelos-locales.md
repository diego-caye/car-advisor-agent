# ADR-003 · Local models with Ollama

## Status
Accepted — moved up from F8 (P2) to F6 by the human's decision on 2026-09-15.

## Context

`00-master-build.md` planned local models for F8, as P2. They were moved up because the project didn't have a `GOOGLE_API_KEY` with billing enabled, and that blocked three things at once: verifying F4 in the browser, ingesting the KB with real embeddings, and calibrating `RAG_MIN_SCORE` against a real score distribution.

Hardware available: RTX 5080 (16 GB VRAM), 32 GB RAM, Ollama 0.24 in Docker with GPU access.

## Decision

A local profile by default, swappable to Gemini by changing only environment variables:

| Role | Local | Gemini |
|---|---|---|
| Agent | `ollama_chat/gemma4:latest` with `OLLAMA_THINK=low` | `gemini-3.8-flash` |
| Guardrail L2 / eval | `ollama_chat/qwen3:4b-instruct` | `gemini-3.5-flash-lite` / `-flash` |
| Fallback | `ollama_chat/llama3.2:latest` | `gemini-3.7-flash` |
| Embeddings | `embeddinggemma` (768 dims) | `gemini-embedding-001` |

The agent went through three candidates before settling, and each change came from a measurement:

1. `gemma4:latest` — split onto the CPU and took 19 s per turn. It seemed not to fit in VRAM; the real cause was something else (see "The local model needs system RAM, not just VRAM" below).
2. `qwen3:4b-instruct` — very fast (1.2 s) and 100% on GPU, but it **never called `save_lead`**. It did call the other two tools, so it wasn't a wiring problem: the non-reasoning variant doesn't reliably decide to call a silent save-data tool.
3. `gemma4:latest` again, after fixing the WSL RAM limit and freeing up VRAM: **100% GPU, 5–10 s per turn, and all three tools working.** This is the one that stayed.

`qwen3:4b` (with thinking) remains a fallback option: it fits on the GPU with much less free VRAM and also calls all three tools, at the cost of terser responses.

**The `:latest` tags in the table above describe this machine, already tuned — not the template for GitHub.** `.env.example` and `docker-compose.yml` pin explicit tags (`gemma4:12b`, `llama3.2:3b`, `embeddinggemma:300m`, image `ollama/ollama:0.34.0`), so a clean download is reproducible instead of inheriting whatever `:latest` resolves to on a given day (spec 11 §3). `gemma4:12b` isn't exactly the same weight class as `gemma4:latest` (which resolved here to the 8B variant) — it's the closest named variant; if this table's VRAM/context tuning doesn't hold for that fresh download, it has to be re-measured with `ollama ps`, not assumed.

The server image started out pinned to `0.24.0` (the one on this machine) and had to be bumped: `gemma4:12b` didn't exist as a tag for Ollama until 0.30.3 (0.30.5 to avoid a known crash in that variant), so `0.24.0` failed to pull it with `pull model manifest: 412 requires a newer version of Ollama`. Verified with a real clean download of the four models against `0.34.0`: it works, and it even revealed that the engine's own version changes how Ollama reports a model's capabilities — `qwen3:4b-instruct` comes back with `thinking=true` on `0.34.0` and `false` on this machine's native `0.24.0` install.

The `EmbeddingsPort` port and `build_base_model` isolate the difference: outside `container.py` and `config.py`, no layer knows which provider is active.

**Dockerized Ollama became this machine's default path, not just the template's.** Up to this point, this machine's `.env` still pointed at native Ollama (`host.docker.internal:11434`) while `.env.example` already recommended the `local-llm` profile. At the human's request — whoever downloads the repo shouldn't depend on anything installed outside Docker — the real `.env` was changed too: `OLLAMA_API_BASE_CONTAINER=http://ollama:11434`, `COMPOSE_PROFILES=local-llm`, `OLLAMA_PORT=11435` (the host's 11434 already belongs to native Ollama, which still exists for other projects but this one no longer touches it). `AGENT_MODEL`/`FALLBACK_MODEL` moved from `gemma4:latest`/`llama3.2:latest` to the fixed tags `gemma4:12b`/`llama3.2:3b` that `docker-compose.yml` was already pulling, so the app runs against exactly what the Dockerized Ollama has installed.

`EMBEDDINGS_MODEL` was the only change with a real cost: it went from `embeddinggemma` (no tag) to `embeddinggemma:300m`, and `verify_embedding_model()` compares the string as-is against what's stored in `kb_chunks` at ingestion time — a tag change, even for the same model, looks like a different model. `scripts/ingest_kb.py` had to be re-run (71 chunks, against the Dockerized Ollama) before the backend would start without the `EmbeddingModelMismatchError`.

Verified end-to-end against the Dockerized Ollama exclusively: a greeting with `save_lead` and a technical question that triggers `search_knowledge_base` with a correct answer, `ollama ps` confirms all three models at `100% GPU` with the same context (32768) already calibrated for the native install. The first turn took 90 s (cold load of the model just brought up in this container); the second, 39 s.

## Integration findings

Each one cost an iteration and none of them was documented anywhere.

### 1. Gemma 4 only calls tools if "thinking" is on

With `think: false` the model **completely ignores** the tools: it answers in prose "I'll check my knowledge base" and emits no `tool_call` at all. With `think: true` it calls them correctly. Verified directly against the Ollama API, isolating ADK and LiteLLM.

Since the whole agent depends on the tools, `OLLAMA_THINK=true` isn't optional in the local profile.

### 2. The reasoning leaked onto the screen

With thinking on, ADK turns the reasoning into `types.Part(text=..., thought=True)`. Our SSE translator was concatenating **every** part, so the user saw the model's internal monologue ("Thinking Process: 1. Analyze the user input…") before the actual response.

Fix: `agent/parts.py::visible_text()` skips parts with `thought=True`, and is used in the three places that assemble text (SSE, message history, and the L4 filter). This applies to Gemini too, which marks its reasoning the same way.

### 3. LiteLLM resolves the provider from `llm_request.model`

`ResilientLlm` wraps the real model for retries and fallback (spec 07). LiteLLM doesn't look at its own instance's `model` field but at `llm_request.model`, which ADK fills with the agent's canonical name — i.e., the wrapper's name. Result: `BadRequestError: LLM Provider NOT provided. You passed model=resilient`.

Fix: `ResilientLlm._call` sets `llm_request.model` to the delegate's before invoking it, so each model (primary or fallback) sees its own identifier.

### 4. Turns with no visible text

Gemma 4 sometimes produces only reasoning and no response, leaving an empty bubble in the UI. The translator now detects a turn with no visible text and emits a recovery phrase, except when the turn legitimately ends with no text (a pending HITL confirmation or an already-reported error).

### 5. The context has to be declared

`gemma4` declares a context of 131072 tokens, but Ollama uses its own (much smaller) default and **silently truncates** unless told otherwise. `num_ctx` is passed explicitly on every call, from `OLLAMA_CONTEXT_LENGTH` (16384 with 16 GB of VRAM; 32768 with 24 GB or more).

### 6. The prefix matters and is validated

`ollama/` can cause tool-calling loops; only `ollama_chat/` is treated as a conversational model. `Settings` rejects startup if `LLM_PROVIDER=ollama` and `AGENT_MODEL` doesn't start with `ollama_chat/`, with a message explaining which one to use.

### 7. `LiteLlm` doesn't ship in the base install

`from google.adk.models.lite_llm import LiteLlm` fails with `ImportError` on a bare `google-adk`. The extra is required: `google-adk[extensions]==2.9.1`.

## The local model needs system RAM, not just VRAM

This was the highest-impact finding, and the initial diagnosis was wrong: it looked like a VRAM problem, and it was actually **two separate limits stacked on top of each other**.

On an RTX 5080 (16.3 GB) with 31 GB of RAM, `gemma4:latest` (~10 GB) ran two-thirds on CPU and took 19 s per turn. Lowering the context didn't help. The real error only showed up when Ollama was asked to load the model from scratch:

```
model requires more system memory (6.7 GiB) than is available (6.0 GiB)
```

**Cause 1 — the WSL VM.** Docker Desktop on Windows runs on WSL2, which, without a `.wslconfig`, takes 50% of the machine's RAM by default: 15.2 GB out of 31. Inside that VM, with the rest of the containers running, Ollama was left with ~6 GB of system RAM — not enough for the part of the model that doesn't fit on the GPU. The machine's full 31 GB never reached Docker.

**Cause 2 — other processes holding onto VRAM.** Another container on the machine (a speech-synthesis service) kept its model loaded on the GPU even while idle, using ~4.8 GB. This isn't a bug: most ML services do *eager loading* because loading the model is slow, and on top of that PyTorch doesn't return freed VRAM to the driver, it keeps it in its own pool. Ollama is the exception: it unloads the model after its `keep_alive` window.

With `.wslconfig` (`memory=24GB`) and that container stopped, 14.2 GB of VRAM were freed up and **`gemma4` moved to 100% GPU with a 32768 context**.

| Configuration | Split | Latency per turn |
|---|---|---|
| `gemma4`, WSL at 15 GB, other models on GPU | 66% CPU / 34% GPU | 16–32 s |
| `gemma4`, WSL at 24 GB, VRAM freed | **100% GPU** | **5–10 s** |
| `qwen3:4b-instruct` (comparison) | 100% GPU | 1.2 s |

### How to diagnose it

`ollama ps` is the tell: the `PROCESSOR` column shows whether the model is entirely on the GPU or split.

```bash
docker exec <ollama> ollama ps                    # CPU/GPU split
docker exec <ollama> ollama stop <model>          # unload
docker exec <ollama> nvidia-smi --query-gpu=memory.free --format=csv
wsl -d docker-desktop -e sh -c "free -h"          # the VM's real RAM
```

If the model is split, check **both** things: free VRAM and available RAM inside the WSL VM.

### On widening the context

Widening `num_ctx` grows the KV cache. With the model already overflowing, going from 8k to 32k nearly doubled latency; with the model entirely on the GPU, it comes for free.

And widening it is **necessary**, not optional: this app's real turns measure between 2,400 and 9,600 input tokens (an instruction of ~2.2k, three tool schemas, RAG fragments, and history). With Ollama's default, the prompt would be silently truncated, which is what produces incoherent or cut-off responses. Hence `OLLAMA_CONTEXT_LENGTH=32768`.

### Reasoning is the price of tools working

`qwen3:4b-instruct` responded in 0.4–3.7 s but never called `save_lead`, so the lead record never got filled in — and capturing the lead is a requirement of the challenge, not decoration. The reasoning variant does call it, at the cost of latency:

| Configuration | `save_lead` | Latency per turn |
|---|---|---|
| `qwen3:4b-instruct` (no thinking) | **no** | 0.4–3.7 s |
| `qwen3:4b` + `think=low` | yes | 12–30 s |
| `qwen3:4b` + `think=true` | yes | 10–17 s |

In isolation, `think=low` responds in ~3 s. Inside the application it climbs to 12–30 s because the real context (an instruction of ~2.2k tokens plus three tool schemas) makes the model reason much more, and ADK calls the model twice per turn when a tool is involved: once to decide it, and once to write the response with its result.

The reasoning levels (`low`, `medium`, `high`) work and settle the question spec 05 §3 left open about whether the SDK exposes them: yes, via Ollama's `think` parameter.

**Path to improve if latency is a problem:** shorten the system instruction, which is what inflates the reasoning the most. Not done here because the instruction encodes the baseline's canned phrases and rules, and trimming it blindly risks drifting from the spec.

### Reference table

Measure with the model unloaded, because what matters is what's free, not what's installed.

| Free VRAM | Free RAM in the WSL VM | Suggested model | Context |
|---|---|---|---|
| ~4 GB | 4 GB | `llama3.2` | 8192 |
| ~9 GB | 8 GB | `qwen3:4b` | 32768 |
| ~14 GB | 16 GB | `gemma4:latest` | 32768 |
| 24 GB or more | 24 GB | a larger `gemma4` | 32768 |

On Windows, besides the model, the WSL VM also needs sizing in `%USERPROFILE%\.wslconfig`:

```ini
[wsl2]
memory=24GB
swap=8GB
autoMemoryReclaim=gradual
```

The changes require `wsl --shutdown`, which restarts every container. Ones with `restart: unless-stopped` come back on their own.

### 8. Small models write out the call instead of emitting it

Gemma 4 sometimes returned the tool call **as text** in the response:

```
Hola 👋 Soy Luis, tu asesor automotriz. ¿Con quién tengo el gusto?
save_lead(name="Diego", primary_use=None, vehicle_type_interest=None, ...)
```

The tool was never executed and the user saw that in the chat bubble. Caught by looking at a browser capture, not in the tests: it doesn't happen with `FakeAdkLlm`.

L4 now detects and strips these pseudo-calls (`strip_pseudo_tool_calls`). It doesn't fix the tool not being executed — that's on the model — but it keeps the user from seeing code.

### 9. RAG + thinking sometimes runs out the output token budget

Found while running the evalset (`backend/tests/evalset/`, F7) against real `gemma4:12b`: the question "what's the difference between an SUV and a crossover?" (which triggers `search_knowledge_base`) once ended in

```
upstream error FinishReason.MAX_TOKENS: Maximum tokens reached
```

`asesor/api/sse.py::translate` already handles this as designed (spec 07): an `event.error_code` translates to a retryable SSE `error`, never a broken bubble or a crash — the failure handling worked as intended. It's not an isolated case of "no visible text" (finding #4): there, the model produces nothing at all; here it does produce something (reasoning + the response itself) but runs out of token budget before closing it, with `OLLAMA_THINK=low` and a 32768 context already active.

The fix wasn't investigated in depth (raising `num_predict`/`max_tokens` explicitly, or trimming the KB fragments that go into the context) because it didn't reproduce on repeated runs of the same case — it looks occasional, not systematic. Left noted for whoever picks up F7/evalset next: if it becomes frequent, the first suspect is the size of the KB chunks injected as the tool's result, not the model itself.

## Differences vs. Gemini

- **Conversational quality:** good on both local models. They respect the role, the Peruvian "tú," the 2–3 sentence limit, and the baseline's canned phrases. RAG-grounded answers stay faithful to the retrieved fragments.
- **Tool-call consistency:** lower than Gemini's. In one run the agent captured `name` and `primary_use`; in another only `name`; in another it wrote the call as text. The state machine doesn't break because the domain recalculates the stage, not the model.
- **Latency:** with the model properly sized, comparable to Gemini Flash (~1–2 s per conversational turn).
- **Cost and privacy:** zero cost per token and no data leaves the machine. This is what makes it feasible to develop and record the demo without a billing account.

## Consequences

- The repo starts up with no API key at all: `docker compose up` plus the two `ollama pull`s and the project runs in full.
- The `local-llm` profile in `docker-compose.yml` brings up its own Ollama with a volume and a pull job. It started as two override files (`local-llm` + `gpu`) so as not to break startup on machines without an NVIDIA GPU; they were unified into profiles because the profile already serves that purpose: a plain `docker compose up -d` never touches the GPU. The cost is that the profile assumes a GPU; anyone without one points `OLLAMA_API_BASE` at a host Ollama and skips the profile, which is also the common case on Windows.
- `RAG_MIN_SCORE` was calibrated for `embeddinggemma` (0.42). Switching embeddings models forces both a re-ingestion **and** a re-calibration; the startup check catches the former, the latter is manual.
- Going back to Gemini means changing six environment variables and re-ingesting the KB. No code is conditioned on the provider outside `container.py` and `config.py`.

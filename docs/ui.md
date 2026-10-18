# UI spec · Automotive advisor

Design plan written before the code (F4), updated in F6 when adopting shadcn/ui and again when moving from a blue + amber palette to black and white with light/dark mode. The goal is for it to read like an advisory tool a Peruvian would confidently chat with, not like a generic AI demo.

## 0. Component base

Components come from **shadcn/ui** (`radix-nova` preset, Radix primitives, Lucide icons), installed in `src/components/ui/` and versioned with the repo: it isn't an opaque dependency, it's our own code that can be read and modified. What it provides — and what we weren't going to redo well by hand — is the accessible overlay behavior: the model selector's `Select` and the delete `AlertDialog` need focus trapping, Escape-to-close, keyboard navigation, and correct `aria-*` attributes.

The palette from section 2 **isn't** kept separate: it's expressed directly in shadcn's semantic tokens (`--primary`, `--muted-foreground`, `--border`…), so that any component added later comes out already matching the product's identity. Having two color systems coexist was the surest way for them to drift apart.

A custom component, not from shadcn, controls the mode: `ThemeToggle` toggles the `.dark` class on `<html>` and persists the choice in `localStorage`. An inline script in `index.html` applies it before the first render so there's no flash of the wrong theme, and until the person touches the button the app follows the OS theme.

**UI chrome is bilingual (EN/ES), separately from the agent's own replies.** The agent already mirrors whichever language the user writes in (spec 05 §LANGUAGE) — that's a prompt-level behavior, not this layer. The UI's own copy (buttons, labels, empty states, dev panel, error messages) goes through `react-i18next` + `i18next-browser-languagedetector`: on first load it reads the browser's language (`navigator.language`) and renders English or Spanish accordingly, defaulting to Spanish when that's unresolvable — same default-to-Spanish convention as the agent's own LANGUAGE rule. A `LanguageToggle` button next to `ThemeToggle` lets the person override it by hand; the choice persists in `localStorage` (key `asesor.language`) and wins over the browser default on later visits. Translation strings live in `src/i18n/locales/{en,es}.json`; `src/features/chat/labels.ts` exposes small `label(t, key)` helpers (`stageLabel`, `reasonLabel`, `channelLabel`, `toolActivityLabel`) instead of the old static `Record<string, string>` maps, since the label now depends on the active language and has to be resolved through `t` at render time. The bot's own canned KB content and example conversations in this doc stay in Spanish regardless of the UI language, same documented exception as before.

## 1. Principles

1. **The conversation leads.** Chat occupies the center and a comfortable reading width (~68 characters). Everything else is support and can collapse.
2. **The agent's work is visible, not noisy.** When Luis checks the technical guide or saves data, a discreet chip shows up in the timeline, not a modal or a full-screen spinner.
3. **Nothing gets decided for the user.** Handing off to a human advisor always goes through a confirmation card with explicit buttons.
4. **Errors say what happened and what to do.** Never a raw code or a stack trace.
5. **Low visual weight.** One typeface family, 1px borders, almost no shadows. Hierarchy comes from color and space, not from boxes.

### Anti-patterns we deliberately avoid

A cream background with a terracotta accent; black with a neon accent; a kit of identical SaaS cards with the same shadow; all-caps labels above every heading; decorative "→" arrows on buttons; purple gradients; robot illustrations.

## 2. Color

Pure black and white, with no color accent: typographic contrast alone provides hierarchy, and nothing competes for attention with what Luis says. `--primary` inverts between modes (black on white in light mode, white on black in dark mode) instead of being a fixed hue, which is how shadcn resolves a "primary button" in a neutral palette. A successful handoff and errors keep a discreet color because they're state, not decoration — dropping them entirely would have cost the interface clarity.

| Token | Light | Dark | Role |
|---|---|---|---|
| `--background` | `#FFFFFF` | `#0A0A0A` | App background |
| `--card` | `#FFFFFF` | `#171717` | Agent bubble, dev panel |
| `--sidebar` | `#FAFAFA` | `#141414` | Sidebar |
| `--popover` / `--secondary` | `#F2F2F2` | `#262626` | Selector menu, HITL card |
| `--border` / `--input` | `#E2E2E2` | `#2B2B2B` | 1px separators and borders |
| `--foreground` | `#0A0A0A` | `#F2F2F2` | Primary text |
| `--muted-foreground` | `#6B6B6B` | `#A3A3A3` | Metadata, timestamps, chips |
| `--primary` / `--ring` | `#171717` | `#F2F2F2` | Primary button, activity dot, focus |
| `--primary-foreground` | `#FAFAFA` | `#171717` | Text on the primary button |
| `--color-accent-soft`, `--color-user-bubble` | = `--secondary` | = `--secondary` | Activity chip background, user bubble |
| `--color-ok` | `#1A7A42` | `#4ADE80` | Handoff confirmed |
| `--destructive` | `#C0362C` | `#E5645A` | Errors and deletion |

`:root` carries the light theme and `.dark` the dark one; which one applies is decided by `ThemeToggle` (section 0), not a media query — so an explicit choice never gets overridden by the OS.

Contrast in both modes: `--foreground` on `--background` ≈ 19:1 (light) and ≈ 17:1 (dark); `--muted-foreground` on `--card`/`--sidebar` stays above 4.5:1. The primary button uses `--primary-foreground` on `--primary`, never a shade of text on a background of the same shade.

## 3. Typography

A single family, **Geist Variable**, served from the bundle itself (`@fontsource-variable/geist`) rather than a CDN, so it doesn't depend on the network or leak visits to a third party. Falls back to the system stack if it fails to load for any reason:

```
font-family: "Geist Variable", "Segoe UI", system-ui, sans-serif
```

| Role | Size / weight |
|---|---|
| Agent name in the header | 15px / 600 |
| Conversation text | 15px / 400, 1.55 line height |
| Activity chips and metadata | 12px / 500 |
| Model selector | 12px / 500 |
| Dev panel labels | 11px / 500, `letter-spacing: .04em` |
| Dev panel numbers (latency, tokens) | 12px / 500, tabular (`font-variant-numeric: tabular-nums`) so they don't jitter on update |

No forced uppercase except in the dev panel's labels, where it helps separate the label from the value.

## 4. Layout

```
┌──────────┬────────────────────────────┬────────┐
│ + Nueva  │  Luis · asesor automotriz  │  Dev   │
│──────────│                            │────────│
│ Hoy      │   ┌──────────────────┐     │ Etapa  │
│ · SUV... │   │ Hola 👋 Soy Luis │     │ DESCUB │
│ · Híbr.. │   └──────────────────┘     │        │
│          │        ┌─────────────┐     │ Lead   │
│          │        │ Busco un SUV│     │ nombre │
│          │        └─────────────┘     │ uso    │
│          │   ◦ Consultando la guía…   │        │
│          │                            │ 340 ms │
│          │ ┌────────────────────────┐ │ 1.2k tk│
│          │ │ Escribe tu mensaje     │ │ traza→ │
└──────────┴─┴────────────────────────┴─┴────────┘
   240px            flexible              280px
```

(the mockup above shows the UI's Spanish copy, one of its two languages — see "UI chrome is bilingual" in section 0)

- **Sidebar (240px).** A "New conversation" button and the session list. Each row shows the **conversation title** on the first line and date + stage on the second; the title is generated by the lightweight model in the background from the first message, so until it arrives it reads "New conversation." The trash icon appears on hover (and on keyboard focus) and opens an `AlertDialog` clarifying that the messages are lost but not the lead record. It collapses under 900px into a header button.
- **Chat panel (flexible).** A thin header with the agent's name and connection status; the message list; the input field anchored at the bottom.
- **Dev panel (280px, collapsible).** The lead record and stage live, the last turn's latency and tokens, a link to the trace in Langfuse. Collapses with a button and its state is remembered in `localStorage`.

### Responsive

Below 900px the dev panel is fully hidden and the sidebar becomes a drawer. Below 600px bubbles take up 92% of the width. The input field never detaches from the bottom edge.

## 5. Key components

### Message bubble
Agent on the left over `--card`, user on the right over `--color-user-bubble`. 14px radius with the speaker's corner at 4px. No avatar: alignment alone distinguishes who's speaking.

**On streaming (revisited in F6).** The agent's text arrives in a single event, not token by token. This isn't a simplification: the L4 output filter needs to see the complete response before it goes out, and a delta that's already been sent can't be retracted from the browser — reasoned through in `specs/02-api-contract.md` §4. What does happen live, and is where the feeling that the advisor is working comes from, are the tool activity chips, the lead record, and the HITL card.

**Typing indicator.** Since the agent's bubble doesn't exist until the complete response arrives, there would otherwise be nothing on screen between sending and the response: with a cold local model that's tens of seconds, and the UI would look frozen. Three animated dots fill that gap from the very first instant, and at 8 seconds a line of text is added. Aware of the model provider selected: with an Ollama one it says local models sometimes take longer than usual; with an API one (Gemini) the text is generic ("this can take a few seconds"), because there the delay has nothing to do with loading a model onto this machine's GPU. Respects `prefers-reduced-motion`.

**Retry and edit (under the message, not at the bottom of the screen).** When the last message went unanswered, the corresponding user message shows two small text buttons right below it — never in the middle of the conversation, only on the last one, because it's the only one that can ever need it:

- **"↻ Retry"** resends that same text without duplicating the bubble.
- **"✎ Edit"** turns that same bubble into an editable field, focused right there — it doesn't send the text to the main input field below. On confirming ("Save and send"), the bubble keeps the corrected text and is resent; no separate message is added. "Cancel" or Escape discards the change without touching anything.

It used to live as a large button at the bottom of the screen next to the error banner; with more than one message in the conversation it wasn't clear what would be retried, so it was moved to sit right against the specific message.

### Activity chip
Its own line, `--color-accent-soft` background, `--muted-foreground` text, a `--primary` dot on the left. Appears on `tool.started` and resolves when `tool.finished` arrives.

| Tool | Text |
|---|---|
| `search_knowledge_base` | "Consultando la guía técnica…" |
| `save_lead` | "Guardando tus datos…" |
| `request_human_handoff` | "Preparando tu solicitud…" |

(these activity texts are shown in Spanish since that's the product's actual UI copy)

### HITL card
Triggered by `hitl.confirmation_required`. Elevated background, 1px `--primary` border. Shows the reason in natural language (not the enum), the requirement summary, and the channel if known. Two buttons: **"Confirmar solicitud"** (primary) and **"Ahora no"** (ghost). On confirming, the card is replaced by a success line in `--color-ok`: "Solicitud enviada · TICK-00042."

Reasons in natural language: `TEST_DRIVE` → "agendar un test drive"; `FORMAL_QUOTE` → "una cotización formal"; `IMMEDIATE_PURCHASE` → "avanzar con la compra"; `DISSATISFACTION` → "atender un reclamo"; `OUT_OF_SCOPE` → "hablar con un especialista".

### Model selector
In the header, to the left of the dev-panel button. A `Select` listing the catalog from `GET /api/v1/models` with a per-provider badge ("local" or "API"). The chosen model is sent on every turn and remembered in `localStorage`; it's **not** tied to the conversation, so the model can be switched mid-chat without losing the history or the lead record — it's the most direct way to teach the same conversation with Gemma 4, Qwen3, and Gemini. Hidden if only one option is configured, and disabled while a turn is in flight. Options whose provider isn't configured (Gemini with no API key) come out disabled with a "not configured" note instead of being hidden, so it's visible what exists and why it can't be used.

### Conversation title
Generated by `GUARDRAIL_MODEL` (the small model) from the user's first message, in the background and after the turn, so it doesn't add latency to the response. Three to six words, 48 characters max. If the model returns something unusable, the user's own message is used, truncated: a conversation always has to be distinguishable from the others in the list.

### Error
A band above the input field, `--destructive` border, just the text of what happened — no button of its own. The "Retry" button lives next to the specific message being resent (see Message bubble), not here: a single one at the bottom of the screen didn't make clear what would be retried once there were several messages in the conversation. Triggered in three cases: the backend sends an `error` event; the SSE connection drops with no closing event at all (backend crash, network down — there's no way to tell it apart from a legitimate turn except that nothing conclusive ever arrives); or the turn stays completely silent for more than three minutes, the client-side inactivity timeout. All three cases use the same signal because, from the point of view of someone waiting for a response, they're the same problem: nothing arrived, and there has to be a way to retry without reloading the page.

### Dev panel
The lead record field by field (empty ones in `--muted-foreground` with a dash), the stage as a badge, and, for the last turn: latency in ms, tokens in/out, and a link to the trace if `LANGFUSE_PROJECT_ID` is set. The fault-injection selector was added in F6, along with the functionality behind it.

### Routes and deferred session creation
Every conversation lives at its own URL, `/c/:id`, genuinely navigable: it can be reloaded, pasted into another tab, or opened with Ctrl/Cmd+click without losing your place. `/` is the draft — the conversation not yet created in the backend.

The "New conversation" button only returns to the draft (`/`) and clears local state; it doesn't call the API. The session is only created once the first real message is sent, so a repeated click on the button no longer left an empty row per click — nor did reloading the page with the unused draft, which was the real cause of "New conversation" piling up in the sidebar (two earlier fixes had only patched two symptoms of the same underlying problem: simultaneous clicks and repeated normal clicks, but not the early session creation itself).

Going straight to `/c/:id` (a link, a refresh, browser back/forward) loads that conversation; if the `id` doesn't exist or doesn't belong to this user, it falls back to the draft instead of leaving the screen stuck.

### A conversation left without a response
The backend doesn't persist that a turn failed, only the exchange itself (recording "this didn't work" would complicate the data model for something ADK already resolves by simply leaving nothing written). If, on loading a conversation, the last saved message is from the user, there was no response — the model failed, the connection dropped mid-way, whatever it was. The same retry signal as a live failure is reconstructed: the "Retry" icon shows up under that message and resends its text to the same conversation, without duplicating the bubble already on screen.

The real reason behind this, found by inspecting the database live: a turn whose connection drops mid-way makes ADK cancel the agent's task (`Root node <agent> was cancelled`) before writing any event at all — not even an error one. Before this fix, reloading a conversation like that left the user's message just sitting there with no hint that it could be retried.

## 6. Accessibility and quality

- Visible focus on every interactive element: a `--ring` ring that inverts with the theme like the rest of the palette. Never `outline: none` with no replacement.
- The input field is a `textarea`: Enter sends and Shift+Enter breaks the line, which is already what's expected from a chat.
- The message list is `aria-live="polite"` so a screen reader announces responses as they arrive.
- Activity chips and the connection status are announced with `role="status"`.
- `prefers-reduced-motion`: the cursor blink and bubble-entry transitions disappear.
- Minimum 40px touch targets on the HITL card's buttons.
- TypeScript strict with `noUncheckedIndexedAccess`; API types are generated from the backend's `/openapi.json`, never written by hand.
- Vitest tests for the SSE parser and the chat reducer: they're the UI's real stateful logic, and where a bug would be invisible at a glance.

## 7. What's out of scope for F4

👍/👎 feedback buttons (arriving in F7, together with the endpoint backing them) and the fault-injection selector (F6). Documented here so the design already reserves room for them: feedback goes under each agent response, and the selector at the bottom of the dev panel.

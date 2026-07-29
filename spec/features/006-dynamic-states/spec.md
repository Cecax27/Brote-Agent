# 006 - Dynamic States

**Status:** Planning

## What makes

This feature replaces the static "answering..." state with lively intermediate status messages that stream while the agent works. Instead of the user staring at a single loading indicator, they see what Flora is doing step by step — making the app feel alive and setting expectations about what the agent is doing.

Concretely it delivers:

- **SSE streaming endpoint — `POST /chat/stream`.** A new endpoint that mirrors the `/chat` logic but returns a Server-Sent Events (SSE) stream. The final event contains the full `ChatResponse` (reply, conversation_id, proposed_action, vision_request). Intermediate events carry status updates. The existing `/chat` endpoint is untouched and stays single-shot.

- **Status vocabulary — context-aware Spanish messages.** A curated set of status messages mapped to real agent steps:
  - `loading_memory` — when loading conversation history from Supabase ("Recordando nuestra última charla…")
  - `reading_garden` — when building plant context from Supabase ("Mirando tu jardín…", "Buscando en tu jardín…")
  - `analyzing_photo` — when analyzing an image (vision endpoints; "Analizando la foto…")
  - `thinking` — when waiting for Gemini's response ("Pensando…", "Déjame pensar…")
  - `writing_memory` — when persisting messages to Supabase ("Guardando esto para no olvidarlo…")
  Each status group has multiple variants; the emitter picks one at random to keep the experience from feeling robotic.

- **Status hook mechanism — `StatusEmitter`.** A lightweight callback-based emitter that the chat flow calls at each step. It yields SSE events through an async generator, so the streaming response can consume them. Statuses are only emitted when that step is actually happening — if a step is skipped (e.g. no conversation history to load), its status is never emitted.

- **Optional humor — lighthearted, on-brand.** Some status variants carry Flora's playful tone without turning help into a joke. Examples: "Conectando con la sabiduría vegetal…", "Déjame consultar con las hojas…". Humor is always optional — each status group has one or two playful variants mixed in with neutral ones.

- **Vision endpoint streaming.** `POST /vision/analyze-stored` and `POST /vision/analyze-upload` gain an optional streaming mode via `Accept: text/event-stream` header — same status emitter pattern, emitting `analyzing_photo` and `thinking` statuses while the vision call runs.

- **Settings.** `dynamic_states_enabled: bool = True` — kill-switch to disable streaming globally. `dynamic_states_include_humor: bool = True` — toggle to disable playful variants.

- **Tests** for the new behaviour: SSE stream yields correct status events for each step; status events have the expected `event` and `data` shape; the final SSE event matches the single-shot `/chat` response; humour toggle suppresses playful variants; kill-switch makes `/chat/stream` behave like `/chat` (single response); vision streaming emits the expected statuses; 502 errors still emit final error event.

## Why

A companion app that feels "alive" can't freeze for 3–10 seconds with zero feedback. The roadmap frames this as the feature that "makes the app feel alive and sets expectations about what the agent is doing." It's the difference between "is it working?" and "ah, está mirando mi jardín, qué bien."

006 lands after 005 because it streams the conversation flow that 005 defined. Without persistence (005), there's no `loading_memory` step to stream. Without vision (004), there's no `analyzing_photo` step. 006 is the polish layer on top of the pipeline built by 001–005.

## Acceptance criteria

- `POST /chat/stream` returns `200` with `Content-Type: text/event-stream`. The stream emits `status` events for each step the agent executes (resolve conversation, load history, build context, Gemini call, persist), followed by a final `result` event containing the full `ChatResponse` JSON.
- Each SSE `status` event carries `{"step": "<step_key>", "message": "<spanish status>"}` with standard SSE fields (`event: status`, `data: {...}`).
- The `result` SSE event carries `event: result`, `data: <ChatResponse JSON>`.
- Status events are only emitted when their corresponding step actually runs. A new conversation (no history) never emits `loading_memory`. A call without a plant_id never emits `reading_garden`.
- The stream terminates after the `result` event. On a Gemini 502 error, the stream emits a final `error` event with the 502 error envelope.
- Status message variants are randomized per emission — the same step on two different calls may show different variants.
- `dynamic_states_include_humor = False` removes all playful/humour variants from the pool, leaving only neutral statuses.
- `dynamic_states_enabled = False` causes `/chat/stream` to behave identically to `/chat` (returns a single-shot JSON response, no SSE).
- `POST /vision/analyze-stored` and `POST /vision/analyze-upload` with `Accept: text/event-stream` return SSE with `analyzing_photo` and `thinking` statuses followed by a `result` event.
- Without the `Accept: text/event-stream` header, the vision endpoints behave exactly as they did before (single-shot JSON).
- The existing `/chat` endpoint is untouched — no behavior change, no status events.
- `uv run pytest` passes, including the new SSE tests. `uv run ruff check` and `uv run ruff format --check` pass.

## Out of reach

- **Replacing `/chat` with SSE unconditionally.** 006 adds `/chat/stream` alongside `/chat`; it does not force all clients to handle SSE. The mobile app can adopt streaming when ready.
- **Real-time progress indicators (percentages, ETA).** The agent doesn't know how long Gemini will take. Statuses are qualitative, not quantitative.
- **Web search statuses (007).** 007 will add `searching_web` statuses to the vocabulary once web search is implemented.
- **Streaming the Gemini reply token-by-token.** SSE streams status events and the final reply; it does not stream the reply text character-by-character. Token streaming is a separate feature (larger scope: the Gemini SDK supports it, but it requires refactoring the structured-response parser).
- **Status customisation per user / per locale.** Statuses are hardcoded Spanish; no user-customizable status messages or multi-language support.

(End of file - total 74 lines)

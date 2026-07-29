# 006 - Dynamic States

## Phase 0 — Pre-flight & constitution sync

- [ ] Confirm decisions in `plan.md`: SSE not WebSockets, new `/chat/stream` endpoint, randomized variants, humour toggle, kill-switch, vision via Accept header, separate handler file
- [ ] Add settings to `app/config/settings.py`: `dynamic_states_enabled` (default `True`), `dynamic_states_include_humor` (default `True`)
- [ ] Update `.env.example`: `DYNAMIC_STATES_ENABLED`, `DYNAMIC_STATES_INCLUDE_HUMOR`
- [ ] Extend `spec/constitution/tech-stack.md`: add `app/dynamic_states/` to file map, list new settings/env vars, reframe "No streaming" hard limit as lifted by 006

## Phase 1 — Status vocabulary (`app/dynamic_states/statuses.py`)

- [ ] Create `app/dynamic_states/` package (`__init__.py`)
- [ ] `app/dynamic_states/statuses.py`:
  - Define `STATUS_GROUPS: dict[str, list[dict]]` with step keys: `loading_memory`, `reading_garden`, `analyzing_photo`, `thinking`, `writing_memory`
  - Each variant is `{"text": "...", "humor": True/False}`
  - `loading_memory` variants: "Recordando nuestra última charla…", "Recuperando el hilo de la conversación…", "Repasando lo que hablamos…"
  - `reading_garden` variants: "Mirando tu jardín…", "Revisando mis apuntes de tus plantas…", "Buscando en tu jardín…", "Consultando el estado de tus plantas…" + humor: "Conectando con la sabiduría vegetal…", "Las hojas me están contando…"
  - `analyzing_photo` variants: "Analizando la foto…", "Examinando la imagen…", "Observando cada detalle…" + humor: "Acerco la lupa virtual…", "Mis ojos digitales están trabajando…"
  - `thinking` variants: "Pensando…", "Déjame pensar…", "Preparando una respuesta…", "Elaborando una respuesta…" + humor: "Déjame consultar con las hojas…"
  - `writing_memory` variants: "Guardando esto para no olvidarlo…", "Anotando en el diario…"
- [ ] Helper function `pick_status(step_key: str, include_humor: bool) -> str` that picks a random variant for the given step, filtering humour when disabled

## Phase 2 — StatusEmitter (`app/dynamic_states/emitter.py`)

- [ ] `app/dynamic_states/emitter.py`:
  - `class StatusEvent(NamedTuple)`: `event` (str, e.g. "status"), `data` (dict)
  - `format_sse(event: StatusEvent) -> str`: returns `"event: {event}\ndata: {json}\n\n"`
  - `def create_status_event(step: str, message: str) -> StatusEvent`: returns `StatusEvent("status", {"step": step, "message": message})`
  - `def create_result_event(data: dict | BaseModel) -> StatusEvent`: serializes the response dict/model
  - `def create_error_event(code: str, message: str) -> StatusEvent`
  - `async def stream_chat(...) -> AsyncGenerator[str, None]`: the main generator that yields status SSE events interleaved with actual work. Accepts: `body`, `user`, `settings`, `include_humor`. Steps:
    1. Resolve conversation (emit `loading_memory` if loading existing, skip if new)
    2. Plant scoping
    3. Load history (emit `loading_memory` if has messages)
    4. Persist user message (emit `writing_memory`)
    5. Build context (emit `reading_garden` if plant scoped)
    6. Gemini call (emit `thinking`)
    7. Persist assistant + title + bump (emit `writing_memory`)
    8. Yield `result` event with ChatResponse
  - On UpstreamError, yield an `error` event with the 502 envelope

## Phase 3 — SSE chat route (`app/api/sse_routes.py`)

- [ ] `app/api/sse_routes.py`:
  - `POST /chat/stream` — FastAPI route with `Depends(get_authenticated_user)`
  - Check `settings.dynamic_states_enabled`; if False, delegate to the existing single-shot `/chat` flow and return JSON
  - If enabled, call `stream_chat(...)` and return `StreamingResponse(generator, media_type="text/event-stream", headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"})`
  - Same `ChatRequest` / `ChatResponse` models reused from `routes.py`

## Phase 4 — Vision SSE

- [ ] `app/vision/routes.py`:
  - Both `POST /vision/analyze-stored` and `POST /vision/analyze-upload` check `request.headers.get("accept") == "text/event-stream"`
  - When SSE requested, return `StreamingResponse` that emits `analyzing_photo` → `thinking` → `result` (or `error`)
  - Helper: `async def stream_vision(...) -> AsyncGenerator[str, None]` containing the vision flow with status yields
  - When SSE not requested, existing single-shot JSON behavior unchanged

## Phase 5 — Wire into main

- [ ] `app/main.py`: import and mount SSE router from `app.api.sse_routes`
- [ ] Confirm `/docs` shows `POST /chat/stream` and the vision endpoints' SSE behavior (noted in description)

## Phase 6 — Contract & docs

- [ ] `docs/api-contract.md`: document `POST /chat/stream` (SSE event types, status event shape, result event shape, error event shape, Accept header for vision)
- [ ] `README.md`: add new env vars
- [ ] `spec/constitution/tech-stack.md`: confirm all updates reflect 006 file map + lifted "No streaming" limit

## Phase 7 — Tests

- [ ] `tests/test_sse_chat.py`:
  - SSE stream yields correct status events for new conversation (no loading_memory)
  - SSE stream yields loading_memory for existing conversation
  - SSE stream yields reading_garden when plant_id present
  - SSE stream yields thinking before Gemini call
  - SSE stream yields writing_memory after Gemini
  - Result event matches single-shot ChatResponse shape
  - 502 error → stream emits error event
  - kill-switch disabled → returns JSON, not SSE
  - humour disabled → no humorous variants in status events
  - Status event has correct shape (`event: status`, `data: {"step": "...", "message": "..."}`)
- [ ] `tests/test_sse_vision.py`:
  - Vision SSE stream yields analyzing_photo → thinking → result
  - Vision without Accept header returns JSON
- [ ] Regression: `uv run pytest` full suite passes; `uv run ruff check` and `uv run ruff format --check` pass

## Phase 8 — Manual smoke (optional, gated on real Supabase)

- [ ] Real `/chat/stream` call — observe SSE events in the response stream
- [ ] Confirm statuses appear in expected order
- [ ] Confirm final result has `conversation_id` + `reply`

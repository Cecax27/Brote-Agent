# 006 - Dynamic States — Plan

## Approach

Add a new `POST /chat/stream` SSE endpoint that wraps the existing `/chat` flow with intermediate status events. The existing `/chat` single-shot endpoint is untouched. A `StatusEmitter` async generator yields SSE events; the route handler iterates it and streams to the client.

Vision endpoints gain streaming support via `Accept: text/event-stream` header — opt-in, not a new route.

## Decisions

### 1. SSE via `StreamingResponse`, not WebSockets

SSE is simpler, works over HTTP/1.1, and has built-in FastAPI support via `StreamingResponse`. WebSockets are overkill for a unidirectional server→client status stream. SSE also works with Cloud Run's request-response model (the stream counts as one long-lived request).

### 2. New `/chat/stream` endpoint, not modifying `/chat`

Adding streaming to `/chat` would change its response type from `application/json` to `text/event-stream`, breaking existing clients. A separate endpoint lets the mobile app migrate at its own pace. The streaming endpoint reuses the same underlying logic — it calls the same conversation store, context builder, and Gemini functions.

### 3. StatusEmitter as an async generator, not a callback registry

An async generator (`async def emit_statuses(...) -> AsyncGenerator[str, None]`) naturally maps to SSE streaming: each `yield` produces one SSE event, and the route handler iterates it with `async for event in emitter:`. No queues, no background tasks, no lifecycle management. The chat flow is expressed as a linear sequence of `yield status(...)` + `await do_work(...)` calls inside the generator.

### 4. Randomized status variants per group

Each status group (`loading_memory`, `reading_garden`, etc.) has a list of 2–5 Spanish message variants. The emitter picks one with `random.choice()` on each emission. Humour variants are tagged and filtered out when `dynamic_states_include_humor` is disabled.

### 5. Shared chat logic extracted into an async function

To avoid duplicating the entire `/chat` flow, a new `_execute_chat(...)` async function in `app/api/chat_flow.py` contains the 006 step sequence (resolve → history → persist-user → context → Gemini → persist-assistant → title → bump). Both `/chat` and `/chat/stream` call it. The streaming version wraps each step with a `yield status(...)`.

Actually, simpler approach: the streaming endpoint contains its own copy of the flow, with status yields interleaved. The flow is ~50 lines; duplicating it is cheaper than engineering a generalized pipeline abstraction that both endpoints can share. If the flow diverges in later features, keeping them separate avoids accidental coupling.

Wait — let's reconsider. The existing `/chat` handler in `routes.py` is ~140 lines. Copying that into a streaming handler means maintaining two copies. The right tradeoff: extract the core flow steps into individual async helpers (resolve, build, call, persist) and let both handlers compose them. But that's premature abstraction for V0.1.

**Decision: keep it simple.** The streaming handler in `app/api/sse_routes.py` contains the full flow with status yields. The existing `/chat` handler in `routes.py` is unchanged. If both diverge, it's two files to edit — manageable for this codebase size. If they converge later, extraction is trivial.

### 6. Vision streaming via `Accept` header, not new routes

`POST /vision/analyze-stored` and `POST /vision/analyze-upload` check `request.headers.get("accept") == "text/event-stream"`. When present, the handler returns SSE with status events; otherwise, the existing JSON response. This is the standard HTTP content negotiation pattern and avoids route proliferation.

### 7. Kill-switch via settings

`dynamic_states_enabled: bool = True` — when `False`, `/chat/stream` returns a single-shot JSON response identical to `/chat`. This is a safety net for production issues (SSE bugs, client compatibility).

### 8. Status vocabulary file

`app/dynamic_states/statuses.py` — a module with `STATUS_GROUPS: dict[str, list[dict]]` where each variant has `text` and `humor` fields. The emitter picks from the pool, filtering humour when disabled.

## File map (new/modified)

```
app/
├── dynamic_states/
│   ├── __init__.py
│   ├── statuses.py          # STATUS_GROUPS vocabulary
│   └── emitter.py           # StatusEmitter async generator + yield helpers
├── api/
│   ├── sse_routes.py        # POST /chat/stream handler
│   └── ... (existing unchanged)
├── config/
│   └── settings.py          # + dynamic_states_enabled, dynamic_states_include_humor
├── vision/
│   └── routes.py            # + Accept: text/event-stream branch
├── main.py                  # + mount SSE router
tests/
├── test_sse_chat.py         # SSE chat stream tests
└── test_sse_vision.py       # SSE vision stream tests
```

## Risks

- **SSE + Cloud Run idle timeout.** Cloud Run has a request timeout (default 300s, configurable). Gemini calls under 30s are safe. If a call takes longer, Cloud Run kills the connection. Mitigation: the existing `/chat` timeout handling applies; the SSE stream is just a wrapper.
- **SSE buffering.** Some reverse proxies buffer the entire response before sending to the client. Cloud Run + Google Front End does NOT buffer SSE by default, but we should set `X-Accel-Buffering: no` header as a safety measure.
- **Client SSE parsing complexity.** The mobile app (React Native) needs an SSE client. This is standard — EventSource API or a polyfill. Not an agent concern, but worth noting.

## Dependencies

No new Python dependencies. FastAPI's `StreamingResponse` and `asyncio` are already available. `random` from stdlib.

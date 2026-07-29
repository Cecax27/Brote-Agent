# Roadmap

## V0.1 Foundation — "The First Sprout"

The bare minimum to have a running agent online: a Python service exposing a REST API, a basic agent loop, and an automated deploy to Google Cloud Run. No Supabase, no tools, no persistence — just a health-checked endpoint that can hold a plant-care conversation. Everything in V1.0 builds on top of this.

### 000-agent-foundation
What: The skeleton of the whole project — project layout, dependencies, a minimal REST API, a basic agent call to Gemini, and an automated Cloud Run deploy.
- [x] Initialize `uv` project — `pyproject.toml`, `uv.lock`, Python version pin
- [x] Project layout — `app/` package with `main.py` entrypoint, `agent/` module, `config/` for settings, `tests/`
- [x] Config and env loading — `pydantic-settings` reading env vars (Gemini key, port, model name); no secrets in code
- [x] Minimal web framework — FastAPI, mount a `/health` endpoint that returns 200 (used by Cloud Run)
- [x] Basic REST API contract documented — routes, request/response JSON shapes, error structure
- [x] Minimal agent loop — a single `POST /chat` endpoint that receives a message, calls Gemini with a bare system prompt, returns the reply
- [x] Placeholder system prompt — just enough persona (calm, Spanish, plant-care focused) to test end-to-end
- [x] Structured logging — JSON logs to stdout (Cloud Run captures stdout)
- [x] Error handling — structured JSON error responses, never leak stack traces to the client
- [x] Local dev workflow documented — `uv run`, local run command, how to point at a test Gemini key
- [x] `Dockerfile` — multi-stage, lean runtime image, listen on `$PORT`
- [x] Cloud Run deploy config — `cloudbuild.yaml`, region, memory, concurrency, min instances set to 0
- [x] Secret management — load Gemini key from Secret Manager, never baked into the image
- [x] CI pipeline — GitHub Actions on push to `main`: lint, test, build, deploy, smoke test
- [x] Smoke test against the live endpoint after deploy (hit `/health`)
- [x] Basic test setup — `pytest` runner, 5 tests hitting `/health` and `/chat` with mocked Gemini client
- [x] Lint and format via `ruff` — `ruff check` and `ruff format` wired into CI

## V1.0 — "Flora Awakens"

The first complete version of the Brote-Agent backend: a conversational plant-care companion that reads and writes the user's Supabase data, understands photos, searches the web, and keeps the experience lively while staying focused on plant care.

Each feature below is scaffolded as `spec/features/NNN-name/` with `spec.md`, `plan.md`, and `tasks.md` before any code is touched. V0.1 is the only exception — it establishes the project itself.

### 001-conversation-foundation
What: A REST endpoint the mobile app calls to have a plant-care conversation with the AI. Stateless, no history stored on the agent side.
- [x] Define the chat API contract — request/response shape, streaming vs. single-shot, error format
- [x] Gemini client setup — provider key from secret manager, model selection, temperature tuning for a calm friendly tone
- [x] System prompt engineering — Flora personality (relaxed, cheerful, non-judgmental), always ends with a concrete next step
- [x] Plant-care scope guardrail — refuse off-topic requests gracefully to avoid wasting credits
- [x] Spanish-only responses — all AI output in Spanish, matching the app
- [x] Request validation and structured error responses
- [x] Cloud Run deployment config — container, health check, scaling

### 002-supabase-read-access
What: The AI can read the user's plants and their history. Security and privacy are mandatory — a user can only ever access their own data.
- [x] Decide the auth hand-off — how the app passes the Supabase session to the agent (access token in header)
- [x] Verify the user's identity — validate the Supabase JWT (JWT secret) — local HS256 decode, no round-trip
- [x] Scoped Supabase client — query as the authenticated user so Row Level Security applies (access token as key)
- [x] Context builder — gather the relevant plant(s), journal entries, watering schedule, light history, photo metadata to inject into the AI context window
- [x] Data minimization — capped `.limit()`, date windows, photo metadata only (no URLs/bytes); configurable caps in settings
- [x] **Include user display name in context** — fetch the user's name from Supabase and pass it to the AI so Flora can address the user by name. Use `raw_user_meta_data->>'name'` or a profile lookup; keep it minimal.
- [ ] Verify RLS isolation — confirm PostgREST denial on cross-user reads (manual probe pending)
- [ ] Ruff — `ruff check` and `ruff format --check` pass
- [ ] Manual smoke — test against real Supabase project with seeded data (gated on user's Supabase prerequisites)

### 003-supabase-write-actions
What: The AI can write data back to Supabase on the user's behalf when they confirm an action.
- [x] Define the writable surface — which tables/fields the AI is allowed to write (e.g., watering schedules, journal entries)
- [x] Proposed-action flow — AI suggests an action, returns a structured action payload, app asks the user to confirm
- [x] Confirm-and-execute endpoint — agent writes to Supabase only after explicit user confirmation
- [x] Example flow: watering schedule — user asks watering frequency, AI answers and offers to create the schedule, user confirms, AI writes it
- [x] Write under the user's identity — writes respect RLS / user_id ownership
- [x] Save-a-tip flow — let the user save a useful snippet from a conversation into a plant's journal before the conversation disappears
- [x] Audit logging — record what the AI wrote on whose behalf

### 004-image-analysis
What: The user can send photos and the AI analyzes them — plant health, pest/disease symptoms, species identification.
- [x] Image upload contract — how the app sends images (direct upload to Supabase Storage + URL, or multipart to the agent)
- [x] Vision model integration — send image + prompt to Gemini vision capabilities
- [x] Plant health diagnosis — analyze leaves for yellowing, spots, pests, dehydration, etc., and recommend care
- [x] Plant identification — suggest species from a photo with a confidence indicator
- [x] Calibration guidance — ask the user for context (light, recent watering) before diagnosing so the AI avoids inventing answers
- [x] Photo size and cost limits — resize/optimize images before sending to the vision model to control cost and latency

### 005-conversation-continuation
What: The AI remembers what was said. Instead of every `/chat` call being a blank slate, the agent stores messages in `ai_conversations` / `ai_messages` and loads recent history into the Gemini context window for a real ongoing conversation.
- [ ] Create new conversation — POST endpoint that returns a `conversation_id` the client attaches to subsequent messages
- [ ] Store messages — on each `/chat` call, persist the user message and AI reply as `ai_messages` rows (role `user` / `assistant`)
- [ ] Load conversation history into context — fetch the last N messages for the active conversation and include them in the prompt before the user's current message
- [ ] List user conversations — GET endpoint returning all conversations for the authenticated user (id, title, plant_id, updated_at)
- [ ] Get conversation messages — GET endpoint returning the full message list for a conversation
- [ ] Auto-title — generate a short Spanish title from the first user message and store it on the conversation row
- [ ] Scope conversations to plants — conversations optionally link to a `plant_id`; the context builder respects this when loading history
- [ ] Token budget — cap history length (configurable message count) to stay within model context limits

### 006-dynamic-states
What: Replace the static "answering..." state with lively intermediate status messages while the AI works. Makes the app feel alive and sets expectations about what the agent is doing.
- [ ] Stream intermediate status events from the agent alongside the final answer (SSE or chunked response)
- [ ] Status vocabulary — context-aware messages like "Revisando mi wiki de plantas…", "Buscando en tu jardín…", "Analizando la foto…", "Buscando en internet…"
- [ ] Map statuses to real agent steps — reading Supabase, running web search, analyzing image, generating response
- [ ] Optional humor — lighthearted messages that stay on-brand without turning help into a joke
- [ ] Keep statuses honest — only emit a status when that step is actually happening

### 007-web-search
What: The agent can search the internet to answer with current, sourced information and hand the user useful links.
- [ ] Integrate a web search tool the AI can call during a conversation
- [ ] Source-grounded responses — when the AI uses search results, reference them and surface links (articles, videos, products)
- [ ] Decide when to search — let the model decide, or trigger on recognized intents (care guides, pest identification, product recommendations)
- [ ] Rate limiting and cost controls — avoid runaway search loops
- [ ] Trustworthiness — prefer reputable sources, never invent links, say so when info is missing

## Non-Goals (V1.0)

Explicitly out of scope for the first version. Keep these out of the codebase unless revisited.

- **Image creation.** No text-to-image generation. Not now, not later.
- **Off-topic conversation.** The agent specializes in plant care only. Guard against burning credits on unrelated questions; decline gracefully and steer back to plants.

## Backlog / Ideas

- Voice input / spoken conversations
- Proactive nudges — agent-initiated reminders based on plant state
- Multi-language support beyond Spanish
- Specialized diagnosis models (beyond general vision)
- Cost dashboard for the user's AI usage

> Each new feature is created as `spec/features/NNN-name/` with `spec.md`, `plan.md`, and `tasks.md` before any code is touched.
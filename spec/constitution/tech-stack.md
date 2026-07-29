# Tech Stack

## Canonical Commands

| Command | Description |
|---------|-------------|
| `uv run` | Run the app locally (uvicorn app.main:app --reload) |
| `uv run pytest` | Run tests |
| `uv run ruff check` | Lint the code |
| `uv run ruff format --check` | Check formatting |
| `uv run ruff format` | Apply formatting |
| `uv sync` | Install dependencies |
| `uv lock` | Lock dependencies |

## File Map

```
brote-agent/
├── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI app factory + uvicorn entrypoint
│   ├── api/
│   │   ├── __init__.py
│   │   ├── routes.py        # GET /health, POST /chat
│   │   └── errors.py        # Exception handlers -> JSON error envelope
│   ├── agent/
│   │   ├── __init__.py
│   │   ├── loop.py          # call_gemini(message, ...) -> reply
│   │   └── prompts.py       # Flora persona system prompt
│   ├── auth/                # JWT verification + FastAPI dependency
│   │   ├── __init__.py
│   │   ├── tokens.py        # verify_access_token → claims; AuthError
│   │   └── dependency.py    # get_authenticated_user → UserIdentity
│   ├── actions/              # Propose → confirm → execute write flow
│   │   ├── __init__.py
│   │   ├── models.py         # CreateWateringSchedulePayload, AddJournalEntryPayload, payload_digest
│   │   ├── registry.py       # ALLOWED_ACTIONS, resolve_action() → ActionSpec
│   │   ├── tokens.py         # issue_confirm_token / verify_confirm_token (HMAC, single-use)
│   │   ├── handlers.py       # create_watering_schedule, add_journal_entry (write via RLS)
│   │   ├── routes.py         # POST /actions/execute
│   │   └── audit.py          # log_action_executed() → structlog (no content text)
│   ├── config/
│   │   ├── __init__.py
│   │   └── settings.py      # pydantic-settings: GEMINI_API_KEY, SUPABASE_URL, …
│   ├── supabase/            # RLS-scoped Supabase client + context builder
│   │   ├── __init__.py
│   │   ├── client.py        # build_user_client(url, access_token) → AsyncClient
│   │   ├── schema.py        # TABLE_* / COL_* name constants
│   │   └── context.py       # build_plant_context → ContextBundle
│   ├── vision/               # Image analysis — retrieve from Supabase or inline, resize, Gemini vision
│   │   ├── __init__.py
│   │   ├── images.py         # validate_image_bytes, resize_image (Pillow)
│   │   ├── retrieval.py      # resolve stored photos via RLS + fetch from public bucket
│   │   ├── core.py           # analyze_image_with_gemini (multimodal)
│   │   ├── models.py         # ImageRef, VisionAnalyzeResponse, VisionAnalysis, etc.
│   │   ├── routes.py         # POST /vision/analyze-stored, POST /vision/analyze-upload
│   │   └── audit.py          # log_vision_call() → structlog (no bytes/URLs)
│   └── logging.py           # structlog JSON to stdout
├── tests/
│   ├── __init__.py
│   ├── conftest.py          # Client fixture, Gemini mock, JWT helpers
│   ├── test_chat.py         # /chat with mocked Gemini; /health smoke
│   ├── test_auth.py         # 401 paths (missing, malformed, expired, bad sig)
│   ├── test_chat_context.py # context injection, RLS deny, minimization, 502
│   └── test_actions_registry.py  # action model, registry, token lifecycle tests
├── docs/
│   └── api-contract.md      # Routes, request/response JSON, error envelope
├── .dockerignore
├── Dockerfile               # Multi-stage, lean runtime image
├── cloudbuild.yaml          # Build + deploy to Cloud Run
├── pyproject.toml           # uv-managed; ruff + pytest config
├── uv.lock
└── README.md                # Local dev workflow
```

## Data Models

### POST /chat request

```json
{
  "message": "string (required, 1-2000 chars)",
  "plant_id": "string | null (optional)"
}
```

**Headers:** `Authorization: Bearer <supabase_access_token>` (required).

### POST /chat response

```json
{
  "reply": "string",
  "proposed_action": {
    "action_type": "create_watering_schedule | add_journal_entry",
    "plant_id": "uuid",
    "title": "string (short, ES)",
    "summary_es": "string (ES confirmation line)",
    "payload": { "..." },
    "confirm_token": "string (HMAC-signed, single-use, 5-min TTL)"
  } | null
}
```

### POST /actions/execute request

```json
{
  "action_type": "create_watering_schedule | add_journal_entry",
  "plant_id": "uuid",
  "payload": { "..." },
  "confirm_token": "string"
}
```

**Headers:** `Authorization: Bearer <supabase_access_token>` (required).

### POST /actions/execute response

```json
{
  "action_id": "uuid",
  "action_type": "string",
  "status": "executed"
}
```

### Error response (any endpoint)

```json
{
  "error": {
    "code": "string",
    "message": "string"
  }
}
```

### GET /health response

```json
{
  "status": "ok"
}
```

## Conventions

- **Python:** 3.12. Use `uv` for dependency management.
- **Formatting:** `ruff format` (line length 100), `ruff check` with all rules.
- **Type hints:** All public functions and methods must have type annotations.
- **Error handling:** Structured JSON error envelope `{"error": {"code": "...", "message": "..."}}`. Never leak stack traces.
- **Logging:** `structlog` with JSON renderer to stdout. One log per request (method, path, status, duration_ms).
- **Config:** `pydantic-settings` reading from env vars. `.env` in dev (gitignored). Secrets from Secret Manager in Cloud Run.
- **Testing:** `pytest` with async support (`pytest-asyncio`). Mock external services (Gemini).
- **API:** FastAPI with async handlers. Validate request bodies with Pydantic models.
- **Docker:** Multi-stage build. Runtime image listens on `$PORT`. `.dockerignore` excludes `.git`, `tests`, `.venv`, caches.
- **CI:** GitHub Actions on push to `main`: lint, format check, tests, build, deploy, smoke test.
- **Cloud Run:** `us-central1`, min-instances=0, concurrency=80, memory=512Mi. Gemini key from Secret Manager as `GEMINI_API_KEY` env var.
- **Secrets:** Never in code, never in images, never in logs. `.env` in dev (gitignored).
- **Supabase:** Official `supabase-py` async client. RLS-scoped reads and writes via the user's access token (defense-in-depth). Never use the service-role key for user-facing operations — it bypasses RLS. Writes are propose→confirm→execute only; never spontaneous.
- **Auth:** `Authorization: Bearer <supabase_access_token>` on `/chat`. Token verified by calling Supabase's `/auth/v1/user` endpoint. The agent verifies identity, never authenticates.
- **Privacy:** Context contents (journal text, plant names) are never logged — only row counts and durations. RLS is the isolation fence; application code never filters by `user_id` manually.
- **Language:** All AI responses in Spanish. Code and docs in English.

## Hard Limits

These are V1.0-scoped limits — features may lift individual items as they land (see `spec/constitution/roadmap.md`). Current status:

- ~~No Supabase~~ — lifted by 002 (Supabase read access).
- ~~No auth~~ — lifted by 002 (JWT verification).
- ~~No writes~~ — lifted by 003 (propose→confirm→execute flow).
- No streaming (single-shot responses).
- No conversation persistence.
- ~~No image analysis~~ — lifted by 004.
- No web search.
- Spanish-only AI responses.

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
│   │   ├── loop.py          # call_openai(message) -> reply
│   │   └── prompts.py       # Placeholder Spanish plant-care system prompt
│   ├── config/
│   │   ├── __init__.py
│   │   └── settings.py      # pydantic-settings: OPENAI_API_KEY, PORT, OPENAI_MODEL...
│   └── logging.py           # structlog JSON to stdout
├── tests/
│   ├── __init__.py
│   ├── conftest.py          # Client fixture, OpenAI mock fixture
│   └── test_chat.py         # /chat with mocked OpenAI; /health smoke
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
  "message": "string (required, 1-2000 chars)"
}
```

### POST /chat response

```json
{
  "reply": "string"
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
- **Testing:** `pytest` with async support (`pytest-asyncio`). Mock external services (OpenAI).
- **API:** FastAPI with async handlers. Validate request bodies with Pydantic models.
- **Docker:** Multi-stage build. Runtime image listens on `$PORT`. `.dockerignore` excludes `.git`, `tests`, `.venv`, caches.
- **CI:** GitHub Actions on push to `main`: lint, format check, tests, build, deploy, smoke test.
- **Cloud Run:** `europe-west1`, min-instances=0, concurrency=80, memory=512Mi. OpenAI key from Secret Manager as `OPENAI_API_KEY` env var.
- **Secrets:** Never in code, never in images, never in logs. `.env` in dev (gitignored).
- **Language:** All AI responses in Spanish. Code and docs in English.

## Hard Limits

- No Supabase in V0.1 (foundation only).
- No auth in V0.1 (`/chat` is anonymous per-request).
- No streaming in V0.1 (single-shot responses).
- No conversation persistence.
- No image analysis.
- No web search.
- Spanish-only AI responses.

# 000 - Agent Foundation

## Approach

Bootstrap a `uv`-managed Python project and ship the smallest closed loop: a `POST /chat` that calls OpenAI and returns a Spanish reply, behind a `/health` that Cloud Run can probe, containerised and deployed on every push to `main`.

The work is sequenced so that each phase produces something runnable, de-risking the platform before any conversational or Supabase work starts:

1. **Bootstrap & config** — `uv init`, project layout under `app/`, `pydantic-settings` for env. Produces a process that imports cleanly.
2. **API & agent loop** — FastAPI app with `/health` and `/chat`; a minimal `agent/` module that calls the OpenAI SDK with a placeholder Spanish persona; a documented API contract.
3. **Observability & errors** — JSON logs to stdout via `structlog`; FastAPI exception handlers emitting a uniform `{ "error": { "code", "message" } }` envelope, never leaking tracebacks.
4. **Container & Cloud Run** — multi-stage `Dockerfile` listening on `$PORT`; `cloudbuild.yaml` deploying to Cloud Run with min instances 0, concurrency and memory set; OpenAI key mounted from Secret Manager as an env var.
5. **CI & smoke test** — GitHub Actions on push to `main`: ruff checks, pytest, build, deploy, then a smoke test hitting the live `/health`.
6. **Tests & lint** — `pytest` with one `/chat` test mocking the OpenAI client; `ruff check` + `ruff format --check` wired into CI and runnable locally.
7. **Docs** — README local-dev workflow; the REST contract doc; an OpenAPI surface is fine but the canonical contract stays in the repo as docs.

Everything that needs GCP accounts, billing, IAM, OpenAI keys, or repo settings cannot be automated by code and is tracked in `users-tasks.md`.

## Implementation

File map (matches the roadmap layout — `app/` package with `main.py` entrypoint, `agent/` module, `config/` for settings, `tests/`):

```
brote-agent/
├── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI app factory + uvicorn entrypoint
│   ├── api/
│   │   ├── __init__.py
│   │   ├── routes.py        # GET /health, POST /chat
│   │   └── errors.py        # exception handlers -> JSON error envelope
│   ├── agent/
│   │   ├── __init__.py
│   │   ├── loop.py          # call_openai(message) -> reply
│   │   └── prompts.py       # placeholder Spanish persona system prompt
│   ├── config/
│   │   ├── __init__.py
│   │   └── settings.py      # pydantic-settings: OPENAI_API_KEY, PORT, OPENAI_MODEL...
│   └── logging.py           # structlog JSON to stdout
├── tests/
│   ├── __init__.py
│   ├── conftest.py          # client fixture, OpenAI mock fixture
│   └── test_chat.py         # /chat with mocked OpenAI; /health smoke
├── docs/
│   └── api-contract.md      # routes, request/response JSON, error envelope
├── .dockerignore
├── Dockerfile               # multi-stage, leans on uv
├── cloudbuild.yaml          # build + deploy to Cloud Run
├── pyproject.toml           # uv-managed; ruff + pytest config
├── uv.lock
└── README.md                # local dev workflow
```

Key flows:

- **`/health`** — `GET` returns `200 {"status":"ok"}`. No external calls. Cloud Run probes it.
- **`/chat`** — `POST {"message": "..."}`; the route validates the body, calls `agent.loop.call_openai(message)`, returns `{"reply": "..."}`. On a bad body → `400`; on OpenAI failure → `502` (or `500`), all in the uniform error envelope.
- **Config** — `Settings` via `pydantic-settings` reading env: `OPENAI_API_KEY`, `PORT` (default 8080), `OPENAI_MODEL` (default decided in Decisions), `LOG_LEVEL`. `.env` loaded locally; in Cloud Run env vars come from Secret Manager.
- **Logging** — `structlog` configured to emit JSON to stdout; one log per request (method, path, status, duration_ms), and a log per OpenAI call (model, latency). Never logs the raw key.
- **Errors** — A top-level exception handler wraps any unhandled exception into the JSON error envelope and logs the traceback server-side only.
- **Dockerfile** — Stage 1 installs `uv` and the project into a venv; Stage 2 copies the venv into a slim runtime image and runs `uvicorn app.main:app --host 0.0.0.0 --port $PORT`. `.dockerignore` excludes `.git`, `tests`, `.venv`, caches.
- **Cloud Run** — `cloudbuild.yaml` builds and deploys with `--min-instances 0`, `--concurrency` set, `--memory` set, `--region` from a substitution, and `--set-secrets` to mount the OpenAI key.
- **CI** — GitHub Actions workflow on push to `main`: ruff check, ruff format --check, `uv run pytest`, `gcloud builds submit` (or direct deploy), then a step that curls the live `/health` and fails on non-200.

## Decisions

Recommended defaults, all to be confirmed before code is touched:

- **Web framework:** FastAPI + Uvicorn. Rationale: async-first, fits the later OpenAI streaming work (005), trivial `/health`, good request validation via Pydantic. Alternatives considered: Starlette (fine, but FastAPI pays low overhead for a lot), Litestar, Flask (sync, worse fit for async OpenAI).
- **Python version:** 3.12 (latest stable, matches Cloud Run runtime and OpenAI SDK support).
- **OpenAI client:** official `openai` Python SDK, async mode.
- **Logging:** `structlog` with a JSON renderer to stdout.
- **CI provider:** GitHub Actions (the repo is on GitHub).
- **Cloud deploy:** Cloud Run via `cloudbuild.yaml` invoked from CI; Artifact Registry for the image.
- **Secrets:** OpenAI key in Secret Manager, mounted into Cloud Run as an env var via `--set-secrets`; locally via `.env` (gitignored).
- **Default model:** `gpt-4o-mini` for the placeholder persona (cheap enough for foundation smoke tests), overridable via `OPENAI_MODEL`. **Pending user confirmation** — depends on their OpenAI plan / cost appetite.
- **Cloud Run region:** **Needs user input** — recommend a region close to the Brote audience (likely Spanish-speaking users) such as `europe-west1`.
- **Port:** default `8080`, honour `$PORT` at runtime.

Open gaps the user must resolve are in `users-tasks.md`.

## Risks

- **`spec/constitution/tech-stack.md` is empty (0 bytes).** The AGENTS.md workflow says a feature's plan must respect `tech-stack.md`, and the constitution takes precedence. With it empty there is nothing to respect and conventions can drift. Mitigation: populate `tech-stack.md` as part of this foundation (it explicitly "establishes the project itself"), at minimum with the canonical command list, file map, and conventions. This is tracked below and in `users-tasks.md`.
- **OpenAI cost during CI/smoke tests.** CI pytest mocks OpenAI (no spend), but the post-deploy smoke test only hits `/health` (no spend). Manual `/chat` tests do spend. Mitigation: use `gpt-4o-mini` and a cost cap on the OpenAI org if available.
- **Cloud Run cold starts.** Min instances 0 saves cost but adds cold-start latency to the first `/chat` after idle. Acceptable for V0.1; revisit in 001.
- **IAM/Secret Manager wiring.** A frequent source of deploy failures (runtime SA needs Secret Accessor; Cloud Build needs to depoy + read secret). Mitigation: `users-tasks.md` lists exactly which roles to grant before the first deploy.
- **Framework lock-in.** Picking FastAPI now is low-risk and reversible for the API surface we have, but it is a decision worth confirming.
- **Port/env mismatch between local and container.** Mitigation: single source of truth in `config/settings.py`, README documents both local and container run.
- **Roadmap items span "code" and "cloud" work.** Some checklist entries (deploy config, CI, secret management) cannot be finished by code alone; they require manual cloud setup. Splitting between `tasks.md` (code) and `users-tasks.md` (manual) keeps status honest.
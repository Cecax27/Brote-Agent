# 000 - Agent Foundation

Phase buckets mapped from the `roadmap.md` checklist. Items requiring manual cloud/account work (not doable in code) are tracked in `users-tasks.md` and referenced here where they gate a phase.

## Phase 0 — Pre-flight & decisions

- [x] Confirm decisions in `plan.md`: web framework (FastAPI), Python version (3.12), logging (structlog), CI (GitHub Actions), default OpenAI model (gpt-4o-mini), Cloud Run region (europe-west1)
- [x] Populate `spec/constitution/tech-stack.md` with the canonical command list, file map, and conventions
- [ ] Confirm the `users-tasks.md` cloud prerequisites are satisfied before Phase 4 (GCP project, APIs enabled, Artifact Registry, Secret Manager, OpenAI key, GitHub↔GCP auth)

## Phase 1 — Project bootstrap & config

- [x] Initialize `uv` project — `pyproject.toml`, `uv.lock`, Python version pin
- [x] Project layout — `app/` package with `main.py` entrypoint, `agent/` module, `config/` for settings, `tests/`
- [x] Config and env loading — `pydantic-settings` reading env vars (OpenAI key, port, model name); no secrets in code
- [x] Local dev workflow documented — `uv run`, local run command, how to point at a test OpenAI key

## Phase 2 — Minimal API & agent loop

- [x] Minimal web framework — mount a `/health` endpoint that returns 200 (used by Cloud Run)
- [x] Minimal agent loop — a single `POST /chat` endpoint that receives a message, calls OpenAI with a bare system prompt, returns the reply
- [x] Placeholder system prompt — just enough persona (calm, Spanish, plant-care focused) to test end-to-end
- [x] Basic REST API contract documented — routes, request/response JSON shapes, error structure

## Phase 3 — Observability & error handling

- [x] Structured logging — JSON logs to stdout (Cloud Run captures stdout)
- [x] Error handling — structured JSON error responses, never leak stack traces to the client

## Phase 4 — Container & Cloud Run

- [x] `Dockerfile` — multi-stage, lean runtime image, listen on `$PORT`
- [x] Cloud Run deploy config — `cloudbuild.yaml`, region, memory, concurrency, min instances set to 0
- [x] Secret management — load OpenAI key from Secret Manager, never baked into the image
- [ ] Gated on: `users-tasks.md` cloud prerequisites complete

## Phase 5 — CI & smoke test

- [x] CI pipeline — on push to `main`, run lint+format checks, tests, build image and deploy to Cloud Run
- [x] Smoke test against the live endpoint after deploy (hit `/health`)

## Phase 6 — Tests & lint

- [x] Basic test setup — `pytest` runner, one test hitting the `/chat` endpoint with a mocked OpenAI client
- [x] Lint and format via `ruff` — `ruff check` and `ruff format` wired into CI
- [x] All 5 tests passing: `/health`, `/chat` with mock, validation errors, and 500 error with error envelope

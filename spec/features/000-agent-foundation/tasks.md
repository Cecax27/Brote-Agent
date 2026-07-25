# 000 - Agent Foundation

Phase buckets mapped from the `roadmap.md` checklist. Items requiring manual cloud/account work (not doable in code) are tracked in `users-tasks.md` and referenced here where they gate a phase.

## Phase 0 — Pre-flight & decisions

- [ ] Confirm decisions in `plan.md`: web framework (FastAPI), Python version (3.12), logging (structlog), CI (GitHub Actions), default OpenAI model, Cloud Run region
- [ ] Populate `spec/constitution/tech-stack.md` with the canonical command list, file map, and conventions (currently empty — see `plan.md` Risks)
- [ ] Confirm the `users-tasks.md` cloud prerequisites are satisfied before Phase 4 (GCP project, APIs enabled, Artifact Registry, Secret Manager, OpenAI key, GitHub↔GCP auth)

## Phase 1 — Project bootstrap & config

- [ ] Initialize `uv` project — `pyproject.toml`, `uv.lock`, Python version pin
- [ ] Project layout — `app/` package with `main.py` entrypoint, `agent/` module, `config/` for settings, `tests/`
- [ ] Config and env loading — `pydantic-settings` reading env vars (OpenAI key, port, model name); no secrets in code
- [ ] Local dev workflow documented — `uv run`, local run command, how to point at a test OpenAI key

## Phase 2 — Minimal API & agent loop

- [ ] Minimal web framework — mount a `/health` endpoint that returns 200 (used by Cloud Run)
- [ ] Minimal agent loop — a single `POST /chat` endpoint that receives a message, calls OpenAI with a bare system prompt, returns the reply
- [ ] Placeholder system prompt — just enough persona (calm, Spanish, plant-care focused) to test end-to-end
- [ ] Basic REST API contract documented — routes, request/response JSON shapes, error structure

## Phase 3 — Observability & error handling

- [ ] Structured logging — JSON logs to stdout (Cloud Run captures stdout)
- [ ] Error handling — structured JSON error responses, never leak stack traces to the client

## Phase 4 — Container & Cloud Run

- [ ] `Dockerfile` — multi-stage, lean runtime image, listen on `$PORT`
- [ ] Cloud Run deploy config — `cloudbuild.yaml` or `gcloud run deploy` invocation, region, memory, concurrency, min instances set to 0
- [ ] Secret management — load OpenAI key from Secret Manager (or Secret Manager env var), never baked into the image
- [ ] Gated on: `users-tasks.md` cloud prerequisites complete

## Phase 5 — CI & smoke test

- [ ] CI pipeline — on push to `main`, build image and deploy to Cloud Run
- [ ] Smoke test against the live endpoint after deploy (hit `/health`)

## Phase 6 — Tests & lint

- [ ] Basic test setup — `pytest` runner, one test hitting the `/chat` endpoint with a mocked OpenAI client
- [ ] Lint and format via `ruff` — `ruff check` and `ruff format` wired into CI
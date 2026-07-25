# 000 - Agent Foundation

**Status:** Code Complete — awaiting cloud prerequisites (see users-tasks.md)

## What makes

This feature builds the skeleton of the whole Brote-Agent backend. It delivers a runnable Python service, managed with `uv`, that exposes a minimal REST API consumed later by the React Native client, plus an automated deploy to Google Cloud Run.

Concretely it delivers:

- A `uv`-managed project (`pyproject.toml`, `uv.lock`, pinned Python version).
- A project layout under `app/` with a `main.py` entrypoint, an `agent/` module, a `config/` module for settings, and `tests/`.
- Config and env loading via `pydantic-settings` (OpenAI key, port, model name). No secrets in code.
- A minimal web framework mounting a `GET /health` endpoint returning 200 (used by Cloud Run's health check).
- A documented REST API contract: routes, request/response JSON shapes, and a structured error format.
- A minimal agent loop: a single `POST /chat` endpoint that receives a message, calls OpenAI with a placeholder Spanish plant-care system prompt, and returns the reply.
- Structured JSON logging to stdout (Cloud Run captures stdout).
- Structured JSON error responses that never leak stack traces to the client.
- A multi-stage `Dockerfile` producing a lean runtime image that listens on `$PORT`.
- Cloud Run deploy config (region, memory, concurrency, min instances set to 0) and secret-loading wiring so the OpenAI key comes from Secret Manager and is never baked into the image.
- A CI pipeline that, on push to `main`, runs lint+format checks, runs tests, builds the image, and deploys to Cloud Run.
- A smoke test that hits the live `/health` endpoint after deploy.
- A basic `pytest` setup with at least one test hitting `/chat` against a mocked OpenAI client.
- `ruff check` and `ruff format` wired into CI.
- A documented local dev workflow (`uv run`, local run command, how to point at a test OpenAI key).

## Why

Nothing else in the roadmap can be built without this. It establishes the project layout, the dependency toolchain, the deployment pipeline, and the conventions every later feature (001 onwards) will increment onto. It also proves end-to-end that a message can travel from a client through the API to OpenAI and back, in Brote's calm Spanish persona, on Cloud Run — de-risking the platform before any conversational or Supabase work begins.

It is the only feature that is allowed to bootstrap the project itself before the normal scaffold workflow (`spec.md` / `plan.md` / `tasks.md` first, then code) applies to everything else.

## Acceptance criteria

- `uv run` boots the API locally; `GET /health` returns `200` with a JSON body (e.g. `{"status":"ok"}`).
- `POST /chat` with a valid `{ "message": "..." }` body returns a JSON `{ "reply": "..." }` produced by OpenAI, in Spanish, within a reasonable latency.
- The OpenAI key is never in code or in the image; it is loaded from Secret Manager in Cloud Run and from the local environment (`.env` / export) in dev.
- `uv run pytest` passes; at least one test exercises `/chat` with a mocked OpenAI client (no network).
- `ruff check` passes and `ruff format --check` passes on CI.
- The `Dockerfile` builds a lean image that listens on `$PORT` and serves `/health`.
- On push to `main`, CI builds and deploys to a Cloud Run service with min instances set to 0.
- After deploy, an automated smoke test hits the live `/health` and fails the pipeline on any non-200 response.
- The REST API contract (routes, request/response JSON shapes, error structure) is written down in the repo.
- All logs are JSON to stdout; all client-facing errors are JSON; no stack trace is ever returned to the client.
- A README section documents the local dev workflow: how to install, run, and point at a test OpenAI key.

## Out of reach

Explicitly out of scope for 000; they belong to later features or to the constitution:

- Supabase integration, reads or writes (002, 003).
- End-user authentication (the client passes no token yet; `/chat` is anonymous per-request).
- Image analysis (004).
- Web search (006).
- Streaming intermediate status messages (005).
- Conversation persistence / history. The agent is per-request.
- Refined system-prompt engineering and plant-care scope guardrails beyond a placeholder persona (001).
- Multi-language support — Spanish only.
- Populating `spec/constitution/tech-stack.md`, which is currently empty; see Risks.
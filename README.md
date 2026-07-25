# Brote-Agent

AI agent backend for the Brote plant-care mobile app. A Python service on Google Cloud Run exposing a REST API consumed by a React Native client.

## Local Dev Workflow

### Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) (Python package manager)
- An OpenAI API key

### Setup

```bash
# Install dependencies
uv sync --all-extras

# Copy env template and fill in your API key
cp .env.example .env
# Edit .env with your OPENAI_API_KEY
```

### Run locally

```bash
uv run uvicorn app.main:app --reload --port 8080
```

Or with the project script alias:

```bash
uv run
```

The API will be available at `http://localhost:8080`.

### Run tests

```bash
uv run pytest
```

### Lint and format

```bash
uv run ruff check         # Lint
uv run ruff format        # Format
uv run ruff format --check  # Check formatting (CI)
```

## API

See [`docs/api-contract.md`](docs/api-contract.md) for the full REST API contract.

Quick reference:

- `GET /health` — health check (returns `{"status":"ok"}`)
- `POST /chat` — send a message, get a Spanish plant-care reply
  - Request: `{"message": "Tengo una monstera"}`
  - Response: `{"reply": "..."}`

## Deploy

Push to `main` triggers the CI pipeline (GitHub Actions): lint, test, build Docker image, deploy to Cloud Run, and smoke test.

Manual deploy via Cloud Build:

```bash
gcloud builds submit --config=cloudbuild.yaml \
  --substitutions=_SERVICE_NAME=brote-agent,_REGION=europe-west1,_REPOSITORY=brote-repo
```

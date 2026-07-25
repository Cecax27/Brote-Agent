<# 000 - Agent Foundation — User Tasks

Things only you can do (accounts, billing, IAM, credentials, cloud setup). The code-level work lives in `tasks.md`; these items gate Phases 0 and 4. Check them off as you go.

## Decisions to confirm (Phase 0)

- [ ] **Web framework** — FastAPI + Uvicorn (recommended). Confirm or override.
- [ ] **Python version** — 3.12. Confirm.
- [ ] **Logging library** — `structlog` JSON to stdout. Confirm.
- [ ] **CI provider** — GitHub Actions. Confirm.
- [ ] **Default OpenAI model** — `gpt-4o-mini` for the placeholder persona (cheap for smoke tests). Confirm based on your OpenAI plan / cost appetite.
- [ ] **Cloud Run region** — recommend `europe-west1` (closest to the Spanish-speaking Brote audience). Pick your region.
- [ ] **Cloud Run service name** — e.g. `brote-agent`. Pick one.
- [ ] **Agree to populate `spec/constitution/tech-stack.md`** — it is empty (0 bytes); the foundation feature needs it to exist per AGENTS.md.

## OpenAI setup

- [ ] Have an OpenAI account with billing configured.
- [ ] Create an OpenAI API key for the foundation service (consider a restricted/low-spend key).
- [ ] (Optional) Set an org-level spend cap so manual `/chat` tests can't run away.

## GCP setup

- [ ] Have a GCP project (note the Project ID).
- [ ] Enable APIs: Cloud Run, Cloud Build, Artifact Registry, Secret Manager.
- [ ] Create an Artifact Registry Docker repository for the image (note repo path and region).
- [ ] Create a Secret Manager secret for the OpenAI key (e.g. `openai-api-key`) and set its value to the OpenAI key from above.
- [ ] Grant the **Secret Manager Secret Accessor** role on that secret to the Cloud Run runtime service account (so the service can read the key at runtime).
- [ ] Grant the **Secret Manager Secret Accessor** role on that secret to the Cloud Build service account if the build/deploy pipeline needs it (depending on your `--set-secrets` approach).
- [ ] Enable Cloud Build to deploy to Cloud Run: grant the Cloud Build service account the **Cloud Run Admin** role (and Service Account User on the runtime SA) for `gcloud run deploy`.

## Git / CI auth

- [ ] Decide how GitHub Actions authenticates to GCP:
  - Option A (recommended): Workload Identity Federation (OIDC) — set up a Workload Identity Pool + provider for the GitHub repo, and a GCP service account for the deploy.
  - Option B: a GCP service account JSON key stored as a GitHub Actions secret.
- [ ] Put the required GitHub Actions secrets/config in place (project id, region, service name, Artifact Registry repo, WIF config or SA key).
- [ ] Set branch protection on `main` if you want CI to gate merges.

## Local dev prerequisites

- [ ] Install `uv` locally.
- [ ] Have a local OpenAI API key for dev (can be the same as the Secret Manager secret value; keep it in a gitignored `.env`, never in the repo).
- [ ] Install the Google Cloud CLI (`gcloud`) and run `gcloud auth login` + `gcloud config set project <PROJECT_ID>` (needed for the first deploy/`cloudbuild.yaml` runs from your machine if you deploy manually before CI).

## First-deploy checklist

Run through this before expecting CI to succeed end-to-end:

- [ ] All "Decisions to confirm" items resolved.
- [ ] All OpenAI + GCP + Git/CI items above are done.
- [ ] `spec/constitution/tech-stack.md` populated.
- [ ] `000-agent-foundation` Phases 1–3 of `tasks.md` complete locally (`/health` and `/chat` work in `uv run`).
- [ ] Then proceed to Phase 4 (container + Cloud Run) and let the pipeline cut over to CI.
# Deploying Brote-Agent to Google Cloud Run

This guide covers how to build and deploy the Brote-Agent backend to Google Cloud Run,
both automatically through CI and manually from your machine.

The source of truth for the infrastructure is [`cloudbuild.yaml`](../cloudbuild.yaml)
(build + deploy steps) and [`.github/workflows/ci.yml`](../.github/workflows/ci.yml)
(automated pipeline).

---

## 1. Architecture at a glance

```
GitHub push to main
      │
      ▼
GitHub Actions (ci.yml)
  ├─ lint + format check (ruff)
  ├─ tests (pytest)
  └─ deploy job
        │  authenticates to GCP via Workload Identity Federation
        ▼
  gcloud builds submit --config=cloudbuild.yaml
        │
        ▼
  Cloud Build
  ├─ docker build  →  <region>-docker.pkg.dev/<project>/<repo>/<service>:<sha>
  ├─ docker push
  └─ gcloud run deploy <service> --image=... --set-secrets=...
        │
        ▼
  Cloud Run service (FastAPI + Uvicorn, port 8080)
        │
        ▼
  GitHub Actions smoke test → GET <service-url>/health must return 200
```

Key facts:

| Item | Value |
| --- | --- |
| Service name | `brote-agent` |
| Region | `us-central1` |
| Artifact Registry repo | `brote-repo` |
| Image path | `us-central1-docker.pkg.dev/<PROJECT_ID>/brote-repo/brote-agent` |
| Container | Multi-stage `Dockerfile`, Python 3.12 + `uv`, Uvicorn |
| Port | `8080` |
| Runtime | Cloud Run, `--allow-unauthenticated`, min instances 0, concurrency 80, 512Mi, 1 CPU, request timeout 30s |
| Health check | `GET /health` → `{"status":"ok"}` |

Cloud Run is public at the network level (so the mobile app can reach it) but
protected routes require a Supabase access token: `Authorization: Bearer <supabase_access_token>`.

---

## 2. Prerequisites (one-time GCP setup)

These only need to be done **once per GCP project**. If the service is already
deployed, skip to [Section 4](#4-deploy).

1. **GCP project** with billing enabled. Note the `PROJECT_ID`.

2. **Enable the required APIs:**

   ```bash
   gcloud services enable \
     run.googleapis.com \
     cloudbuild.googleapis.com \
     artifactregistry.googleapis.com \
     secretmanager.googleapis.com
   ```

3. **Create the Artifact Registry Docker repository:**

   ```bash
   gcloud artifacts repositories create brote-repo \
     --repository-format=docker \
     --location=us-central1 \
     --description="Brote-Agent container images"
   ```

4. **Create the runtime secrets in Secret Manager.** At minimum the Gemini key.
   See [Section 3.2](#32-runtime-environment-variables) for the full list.

   ```bash
   # Gemini API key (required)
   printf '%s' 'YOUR_GEMINI_KEY' | gcloud secrets create gemini-api-key --data-file=-

   # Action signing secret (required for write actions to be secure)
   printf '%s' "$(openssl rand -hex 32)" | gcloud secrets create action-signing-secret --data-file=-
   ```

   To add the action-signing secret to a service that already exists, see
   [Section 6](#6-adding-a-new-runtime-secret).

5. **Grant the Cloud Run runtime service account access to the secrets.**
   The runtime service account is the default compute SA
   (`<PROJECT_NUMBER>-compute@developer.gserviceaccount.com`) unless you set a
   custom one. Grant `roles/secretmanager.secretAccessor` on each secret:

   ```bash
   gcloud secrets add-iam-policy-binding gemini-api-key \
     --member="serviceAccount:<RUNTIME_SA_EMAIL>" \
     --role="roles/secretmanager.secretAccessor"
   ```

6. **Allow Cloud Build to deploy to Cloud Run.** The Cloud Build service account
   (`<PROJECT_NUMBER>@cloudbuild.gserviceaccount.com`) needs `roles/run.admin`
   and `roles/iam.serviceAccountUser`:

   ```bash
   gcloud projects add-iam-policy-binding <PROJECT_ID> \
     --member="serviceAccount:<CLOUDBUILD_SA_EMAIL>" \
     --role="roles/run.admin"
   gcloud projects add-iam-policy-binding <PROJECT_ID> \
     --member="serviceAccount:<CLOUDBUILD_SA_EMAIL>" \
     --role="roles/iam.serviceAccountUser"
   ```

7. **GitHub → GCP authentication (Workload Identity Federation).** The CI job
   authenticates without a long-lived key. Create a Workload Identity Pool +
   provider for this GitHub repo and a deploy service account, then set the
   GitHub secrets/variables listed in [Section 3.3](#33-github-actions-secrets--variables).

---

## 3. Configuration reference

### 3.1 Cloud Build substitutions

These are the variables `cloudbuild.yaml` accepts (defaults shown in the file):

| Substitution | Default | Meaning |
| --- | --- | --- |
| `_SERVICE_NAME` | `brote-agent` | Cloud Run service name |
| `_REGION` | `us-central1` | Region for Artifact Registry **and** Cloud Run |
| `_REPOSITORY` | `brote-repo` | Artifact Registry repository name |

`PROJECT_ID` and `BUILD_ID` are provided automatically by Cloud Build.

> Keep `_REGION` consistent with the Artifact Registry repo location. The README's
> old manual example used `europe-west1`, but the deployed default is `us-central1`.

### 3.2 Runtime environment variables

`app/config/settings.py` reads these from the environment. Secrets should come
from Secret Manager via `--set-secrets`, not from plain env vars.

| Variable | Required? | Source | Notes |
| --- | --- | --- | --- |
| `GEMINI_API_KEY` | **Yes** | Secret Manager `gemini-api-key` | Already wired in `cloudbuild.yaml`. Missing it = app fails to start. |
| `SUPABASE_URL` | **Yes** | plain env var | e.g. `https://xxxx.supabase.co`. Auth verification and all data reads need it. |
| `SUPABASE_ANON_KEY` | **Yes** | plain env var / Secret Manager | Used to verify access tokens and as the RLS-scoped client key. |
| `ACTION_SIGNING_SECRET` | **Yes** for write actions | Secret Manager `action-signing-secret` | Signs propose→confirm tokens. If empty, tokens are signed with an empty key — **do not ship to prod without this**. |
| `SUPABASE_SERVICE_ROLE_KEY` | No | — | Declared in settings but currently **unused** by application code. Leave unset. |
| `GEMINI_MODEL` | No | plain env var | Defaults to `gemini-3.5-flash-lite`. |
| `LOG_LEVEL` | No | plain env var | Defaults to `INFO`. |
| `PORT` | No | Cloud Run injects `8080` | Uvicorn listens on 8080 (hardcoded in the Dockerfile CMD). |
| `DYNAMIC_STATES_ENABLED`, `HISTORY_MAX_MESSAGES`, … | No | plain env var | All have defaults in `app/config/settings.py`. |

> **Important — known gap:** `cloudbuild.yaml` currently injects **only**
> `GEMINI_API_KEY`. Since feature 002, the API needs `SUPABASE_URL` and
> `SUPABASE_ANON_KEY`, and write actions need `ACTION_SIGNING_SECRET`. A deploy
> using the config as-is will start, but every authenticated route (`/chat`,
> `/conversations`, `/vision/*`, `/actions/*`) will fail. See
> [Section 5](#5-fix-inject-the-missing-runtime-secrets) to close this gap.

### 3.3 GitHub Actions secrets & variables

Set these in **GitHub → Settings → Secrets and variables → Actions**.

Secrets:

| Name | Value |
| --- | --- |
| `GCP_PROJECT_ID` | GCP project ID |
| `GCP_WIF_PROVIDER` | Full Workload Identity provider resource name |
| `GCP_SA_EMAIL` | Deploy service account email |

Variables:

| Name | Example |
| --- | --- |
| `SERVICE_NAME` | `brote-agent` |
| `REGION` | `us-central1` |
| `ARTIFACT_REPO` | `brote-repo` |

---

## 4. Deploy

### Path A — Automatic (CI, the normal path)

Merge/push to the **`main`** branch. GitHub Actions runs lint + tests, then builds
and deploys, then smoke-tests `/health`. Watch progress under the repo's
**Actions** tab.

> CI only triggers on `main`. Deploying a feature branch requires Path B.

### Path B — Manual via Cloud Build (recommended for branches)

Use this to deploy the current branch without merging to `main`. This runs the
same `cloudbuild.yaml` locally driven by `gcloud`.

```bash
# Ensure you're on the branch you want to ship and it's pushed
git branch --show-current

gcloud config set project <PROJECT_ID>

gcloud builds submit \
  --config=cloudbuild.yaml \
  --substitutions=_SERVICE_NAME=brote-agent,_REGION=us-central1,_REPOSITORY=brote-repo
```

Cloud Build substitutes `$BUILD_ID` with the build's unique id, so the image is
tagged with the build (not the commit). `gcloud builds submit` uploads the current
directory as the build context (respecting `.dockerignore`).

### Path C — Fully manual (Docker + gcloud run deploy)

When you want to build locally or bypass Cloud Build entirely.

```bash
PROJECT_ID=<PROJECT_ID>
REGION=us-central1
REPO=brote-repo
SERVICE=brote-agent
TAG=$(git rev-parse --short HEAD)
IMAGE="$REGION-docker.pkg.dev/$PROJECT_ID/$REPO/$SERVICE:$TAG"

# 1. Authenticate Docker to Artifact Registry
gcloud auth configure-docker "$REGION-docker.pkg.dev"

# 2. Build and push
docker build -t "$IMAGE" .
docker push "$IMAGE"

# 3. Deploy
gcloud run deploy "$SERVICE" \
  --image="$IMAGE" \
  --region="$REGION" \
  --platform=managed \
  --allow-unauthenticated \
  --min-instances=0 \
  --concurrency=80 \
  --memory=512Mi \
  --cpu=1 \
  --timeout=30s \
  --set-secrets=GEMINI_API_KEY=gemini-api-key:latest \
  --set-env-vars=SUPABASE_URL="https://xxxx.supabase.co",SUPABASE_ANON_KEY="eyJ..."
```

---

## 5. Fix: inject the missing runtime secrets

The cleanest fix is to extend `cloudbuild.yaml` so every deploy carries the full
environment. It is recommended to move `ACTION_SIGNING_SECRET` and
`SUPABASE_ANON_KEY` into Secret Manager first, then reference them.

```bash
# Create the secrets (once)
printf '%s' 'eyJ...anon-key...' | gcloud secrets create supabase-anon-key --data-file=-
printf '%s' "$(openssl rand -hex 32)" | gcloud secrets create action-signing-secret --data-file=-

# Grant the runtime SA access
for s in supabase-anon-key action-signing-secret; do
  gcloud secrets add-iam-policy-binding "$s" \
    --member="serviceAccount:<RUNTIME_SA_EMAIL>" \
    --role="roles/secretmanager.secretAccessor"
done
```

Then update the `--set-secrets` line in `cloudbuild.yaml` to:

```yaml
      - "--set-secrets=GEMINI_API_KEY=gemini-api-key:latest,SUPABASE_ANON_KEY=supabase-anon-key:latest,ACTION_SIGNING_SECRET=action-signing-secret:latest"
      - "--set-env-vars=SUPABASE_URL=https://xxxx.supabase.co"
```

`SUPABASE_URL` and `SUPABASE_ANON_KEY` are not high-risk (the anon key ships in the
mobile client), but keeping them out of the repo is still preferred.

---

## 6. Adding a new runtime secret

Applies to any future secret (this is the same pattern used for `gemini-api-key`):

```bash
# 1. Create it
printf '%s' 'SECRET_VALUE' | gcloud secrets create <secret-name> --data-file=-

# 2. Grant the runtime SA access
gcloud secrets add-iam-policy-binding <secret-name> \
  --member="serviceAccount:<RUNTIME_SA_EMAIL>" \
  --role="roles/secretmanager.secretAccessor"

# 3A. Add it to cloudbuild.yaml --set-secrets so CI carries it, or
# 3B. Update the running service directly:
gcloud run services update brote-agent \
  --region=us-central1 \
  --update-secrets=<ENV_VAR_NAME>=<secret-name>:latest
```

---

## 7. Verify the deployment

```bash
# Get the service URL
URL=$(gcloud run services describe brote-agent \
  --region=us-central1 --format="value(status.url)")

# Health check (no auth required)
curl -s "$URL/health"          # → {"status":"ok"}

# Authenticated call (needs a real Supabase access token)
curl -s -X POST "$URL/chat" \
  -H "Authorization: Bearer <supabase_access_token>" \
  -H "Content-Type: application/json" \
  -d '{"message":"Hola Flora, ¿cómo cuido mi monstera?"}'
```

Cloud Run revision status:

```bash
gcloud run revisions list --service=brote-agent --region=us-central1
gcloud run services describe brote-agent \
  --region=us-central1 --format="value(status.latestReadyRevisionName)"
```

Logs (streaming):

```bash
gcloud run services logs tail brote-agent --region=us-central1
```

---

## 8. Rollback

Cloud Run keeps every revision. Route traffic back to a known-good one:

```bash
# List revisions, newest first
gcloud run revisions list --service=brote-agent --region=us-central1

# Send 100% of traffic to a previous revision
gcloud run services update-traffic brote-agent \
  --region=us-central1 \
  --to-revisions=<REVISION_NAME>=100
```

To roll back the source, revert the commit on `main` (Path A) or re-run Path B
from the previous commit.

---

## 9. Troubleshooting

| Symptom | Likely cause / fix |
| --- | --- |
| Deploy fails at `gcloud run deploy` with permission denied | Cloud Build SA missing `roles/run.admin` + `roles/iam.serviceAccountUser` ([Section 2.6](#2-prerequisites-one-time-gcp-setup)). |
| Container starts but crashes immediately | `GEMINI_API_KEY` is required by settings; if missing, the app fails on startup. Check the secret is wired and the runtime SA can access it. |
| `/health` is 200 but `/chat` returns 401/500 | Missing `SUPABASE_URL` / `SUPABASE_ANON_KEY`, or an invalid/expired token. See [Section 5](#5-fix-inject-the-missing-runtime-secrets). |
| Write actions return "invalid token" | `ACTION_SIGNING_SECRET` missing or changed between the propose and confirm steps. |
| Smoke test fails with HTTP 000 | Wrong `SERVICE_NAME`/`REGION` in GitHub variables, or the service URL isn't ready yet. |
| Docker push "denied" | `gcloud auth configure-docker <region>-docker.pkg.dev` not run, or the repo doesn't exist. |
| Changes not taking effect after deploy | CI only deploys from `main`; a feature branch needs Path B. Confirm the revision's image tag matches your commit. |
| SSE stream cuts off around 30s | `cloudbuild.yaml` sets `--timeout=30s`; long streaming responses (feature 006) can be killed. Raise it (e.g. `--timeout=300s`) if needed. |

---

## 10. Known gaps / follow-ups

- **`cloudbuild.yaml` does not inject Supabase config.** It only sets
  `GEMINI_API_KEY`. Authenticated routes will fail on a fresh deploy until
  [Section 5](#5-fix-inject-the-missing-runtime-secrets) is applied.
- **Cloud Run request timeout is 30s**, which is tight for SSE streaming added in
  feature 006. Consider `--timeout=300s`.
- **Dockerfile `CMD` hardcodes `--port 8080`** instead of honoring `$PORT`. Cloud
  Run defaults to 8080 so it works today, but changing `PORT` would desync.
- **`SUPABASE_SERVICE_ROLE_KEY` is declared but unused.** No code reads it; do not
  wire it into prod until a feature actually needs it (it bypasses RLS).
- **`spec/features/000-agent-foundation/users-tasks.md`** still has unchecked IAM
  boxes (Secret Manager accessor grants, GitHub↔GCP auth). Keep that file in sync
  as these are completed.

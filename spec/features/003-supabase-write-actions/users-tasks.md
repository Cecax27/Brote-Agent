# 003 - Supabase Write Actions — User Tasks

Things only you can do (Supabase project, RLS `INSERT` policies, secret management, schema confirmation, app-side coordination). The agent does not own the database; it writes to tables that already exist. Gated items block the matching phases in `tasks.md`.

## Writable surface (this is what 003 writes)

- [x] Confirm the agent may **create** rows in these two tables only, under the caller's RLS-scoped token:
  - `watering_schedules` — new active schedule per `(plant_id, user_id)`; creating one deactivates the user's prior active schedule for that plant
  - `journal_entries` — only with `type="observation"` (the save-a-tip flow); `content` ≤ 2000 chars
- [x] Confirm the agent may **not** write to (V1.0 of 003): `plants.*` (no edits/deletes), `light_measurements`, `ai_conversations`, `ai_messages`. Conversation persistence is a Non-Goal; saving a tip writes a `journal_entries` row, not a chat transcript.

## Row Level Security — INSERT policies (gates Phase 4 & 8 — safety critical)

RLS is the agent's ownership fence for writes (same posture as 002, but `INSERT` instead of `SELECT`). The agent can build things to *use* RLS but cannot *create* the policies.

- [x] RLS **enabled** on `watering_schedules` and `journal_entries` (already on per 002 — confirm it stays on).
- [x] An `INSERT` policy on each writable table of the form `auth.uid() = user_id` **with `WITH CHECK`** so the row's owner must be the caller (prevents a request body from setting a foreign `user_id`).
- [x] An `UPDATE` policy on `watering_schedules` restricting `active` toggles to `auth.uid() = user_id` (needed for the deactivate-then-insert example flow).
- [x] Manually verify: a real access token for user A cannot `INSERT`/`UPDATE` a `watering_schedules` row with `user_id` set to user B (one curl with a hand-crafted body is enough — it must be rejected by RLS).
- [x] Confirm there is **no** service-role write path the agent will use. The agent writes with the user's access token only; the service-role key is banned for user-facing writes (matches 002's read posture).

## Secret management (Cloud Run)

- [ ] Create Secret Manager secret `action-signing-secret` (a strong random value; this is for HMAC-signing propose/confirm tokens, not Supabase auth). Keep it out of the repo.
- [ ] Grant the **Secret Manager Secret Accessor** role on `action-signing-secret` to the Cloud Run runtime service account (same pattern as `gemini-api-key` and `supabase-jwt-secret`).
- [ ] Wire `--set-secrets "ACTION_SIGNING_SECRET=action-signing-secret:latest"` in `cloudbuild.yaml` (or grant the Cloud Build service account the accessor role if inject-at-deploy).
- [ ] Confirm `.env` (local dev) holds `ACTION_SIGNING_SECRET` alongside `SUPABASE_URL` / `SUPABASE_JWT_SECRET` / `GEMINI_API_KEY`; never commit it.

## Schema confirmation (the fields 003 writes)

The agent does not own the schema; it writes your existing columns. Confirm these names match your project (they already appear in the verified schema from 002):

- [ ] `watering_schedules` writable columns: `plant_id`, `user_id` (DB/RLS-set, not supplied by agent), `frequency_days` (int ≥ 1), `last_watered_at` (timestamptz, optional), `next_due_at` (timestamptz), `notify_time` (time, default `09:00`), `active` (bool, default true)
- [ ] `journal_entries` writable columns: `plant_id`, `user_id` (DB/RLS-set), `type` (enum, `observation` for 003), `content` (text, ≤ 2000), `photo_url` (left null in 003 — images land in 004)
- [ ] Confirm `frequency_days >= 1` check constraint on `watering_schedules` is acceptable for the example flow (7-day default proposed by Flora).

## Atomicity — the watering-schedule example flow

- [ ] 003 deactivates the old active schedule then inserts a new one as **two PostgREST calls** (no server-side transaction). A tiny window exists between them. Acceptable? (If you want strict atomicity, the alternative is an app-owned Postgres function (RPC) the agent calls — that is the app's call to add; flag it here so the agent knows whether to call an RPC or do two calls.)

## App-side coordination (so 003's contract matches reality)

- [ ] The React Native client renders the `proposed_action` confirm card using `summary_es` (Spanish line for the user) and sends the unchanged `proposed_action` back to `POST /actions/execute` on confirm. The app must **not** alter `payload` or `plant_id` (any change → `400 INVALID_ACTION` by design).
- [ ] The client handles `400 INVALID_ACTION` and `401` on `/actions/execute` gracefully: `401` (token expired/foreign) → re-propose by re-calling `/chat`; `400` → re-propose (the proposal was tampered/unallowlisted). `502` → retry with backoff.
- [ ] Decide with the app team the confirm-card UX is owned by the app (003 only defines the payload contract).
- [ ] Decide whether `save-a-tip` originates from a long-press on Flora's reply text, a dedicated button, or a free-text "save this" (the app owns the affordance; the agent only returns a proposal when asked).

## Audit visibility

- [ ] The agent emits structured audit events to stdout (Cloud Logging). Confirm the team wants audit **agent-side** (structured logs) and **not** a Supabase audit table in 003 (the agent does not own schema; a durable DB audit trail is a later, app-team-owned decision). If DB audit is required, add an app-owned table + an app-owned write path — out of scope for the agent in 003.

---
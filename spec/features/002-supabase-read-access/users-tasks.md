# 002 - Supabase Read Access — User Tasks

Things only you can do (Supabase project, JWT secret, RLS policies, schema, secrets, test data). The code-level work lives in `tasks.md`; these items gate Phases 0 (decisions), 3 (context builder), and 7 (manual smoke). Check them off as you go. The agent deliberately owns no database, so everything below lives on the Supabase/app side.

## Decisions to confirm (Phase 0)

- [x] **Auth hand-off shape** — `Authorization: Bearer <supabase_access_token>` on `/chat`. Confirm, or propose an alternative the app already uses.
- [x] **Token verification mechanism** — local HS256 JWT decode with the Supabase JWT secret (offline, single round-trip saved), vs. calling Supabase's `/auth/v1/user` endpoint. Recommended: local decode. Confirm.
- [x] **Scoped client strategy** — reads run as the user via their access token so RLS applies (defense-in-depth). Rejected: service-role key + app-level `user_id` filtering (bypasses RLS if a filter is forgotten). Confirm RLS-as-the-fence.
- [x] **`plant_id` on `/chat`** — optional field the app sends when the user is inside a plant's own space; absent → light inventory across all the user's plants. Confirm this matches the app's chat UX.
- [x] **Photo handling in 002** — metadata only (count + last-taken date); image bytes/content analysis is deferred to feature 004. Confirm.
- [x] **Supabase client library** — official `supabase-py` async client. Confirm it fits the load profile.
- [x] **New error code** — `401 UNAUTHORIZED`; no `403` (RLS turns "can't see" into "doesn't exist"). Confirm the 401 message (`"Debes iniciar sesión para continuar."`) is acceptable to show in the app.
- [x] **Context caps defaults** — light ≤ 20 plants; deep ≤ 10 recent entries per history type. Confirm or set based on your data shape.
- [x] **JWT secret naming** — Secret Manager secret `supabase-jwt-secret` (mirrors `gemini-api-key`). Confirm the name.

## Supabase project setup

- [ ] Have a Supabase project (note the **Project URL**, used as `SUPABASE_URL`).
- [ ] Note the **JWT secret** (Settings → API → JWT Settings). This is the HS256 secret used to verify access tokens. Keep it out of the repo — it goes in Secret Manager / `.env`.
- [ ] Confirm the **audience claim** Supabase issues on access tokens (commonly `"authenticated"`). If your GoTrue version sets a different `aud`, tell the agent so `auth_jwt_audience` matches — otherwise valid tokens will 401.
- [ ] Confirm the **issuer** is `f"{SUPABASE_URL}/auth/v1"` (standard GoTrue). If not, note the actual value.

## Schema (Phase 3 is gated on this)

The agent does not own the database; it reads your tables. The context builder needs the real names. Either paste the SQL schema below or confirm the assumed names.

- [ ] Share the list of tables the agent may read in 002, with columns. At minimum, the roadmap implies:
  - `plants` (id, user_id/owner, nickname, species, …)
  - logbook / journal entries
  - watering history (+ watering schedule: last / next)
  - light readings / measurements
  - fertilizations
  - repottings
  - observations / notes
  - photos (metadata: id, plant_id, created_at — note: 002 reads refs only, never bytes)
- [ ] Confirm the **foreign-key shape** that ties history rows to a plant and a user (so the builder's joins/filters are correct).
- [ ] Confirm which fields are **safe to send to Gemini** (e.g. nickname yes; any PII / location-sensitive fields — keep out of the context window).

## Row Level Security (gates Phase 3 & 7 — privacy critical)

RLS is the agent's isolation fence. The agent can build things to *use* RLS but cannot *create* the policies — verify these on the Supabase side.

- [ ] RLS **enabled** on every table 002 reads.
- [ ] A `SELECT` policy on each readable table restricting rows to `auth.uid() = <user_id_column>` (or the equivalent on the owner).
- [ ] There is **no policy** granting broad/service-role read access to these tables for user-jwt calls (or, if a service role exists, it is not the token the agent sends — the agent sends the user access token so `auth.uid()` resolves).
- [ ] Manually verify: a real access token for user A cannot `SELECT` user B's `plants` (one curl against `/rest/v1/plants` with two tokens is enough).

## Secret management (Cloud Run)

- [ ] Create Secret Manager secret `supabase-jwt-secret` set to the Supabase JWT secret.
- [ ] Grant the **Secret Manager Secret Accessor** role on `supabase-jwt-secret` to the Cloud Run runtime service account (same pattern already used for `gemini-api-key`).
- [ ] (If the deploy pipeline injects secrets at deploy time) grant the Cloud Build service account the same accessor role, or wire `--set-secrets "SUPABASE_JWT_SECRET=supabase-jwt-secret:latest"`.
- [ ] Confirm `.env` (local dev) is gitignored and holds `SUPABASE_URL` + `SUPABASE_JWT_SECRET`; never commit it.

## Local dev prerequisites

- [ ] Local `SUPABASE_URL` and `SUPABASE_JWT_SECRET` in a gitignored `.env` alongside `GEMINI_API_KEY`.
- [ ] A way to mint a **valid** test access token for local dev (a real test user you can log in to, or a tool to sign a JWT with the secret + correct `sub`/`aud`/`iss`/`exp` for testing — but note an artificial token won't exercise real RLS, only signature verification).

## Test data (Phase 7 manual smoke)

- [ ] A test Supabase user with a small, realistic garden (e.g. 2–3 plants, a few watering/journal/light entries, one photo referenced).
- [ ] If multi-user isolation smoke is wanted, a second test user with at least one plant.
- [ ] Enough to run the smoke in `tasks.md` Phase 7: a `plant_id` deep call, a no-`plant_id` light call, and an expired-token 401.

## App-side coordination (so 002's contract matches reality)

- [ ] The React Native client sends `Authorization: Bearer <access_token>` on every `/chat` call.
- [ ] The client sends `plant_id` when the chat originates from a plant's own space (matches Brote's "each plant has its own space").
- [ ] The client handles `401 UNAUTHORIZED` gracefully (refresh + retry; the agent will not refresh for it).
- [ ] Decide with the app team whether off-plant chat should be allowed at all (light mode) or always require a `plant_id` — inform the agent's default.

---

Once the **Decisions to confirm**, **Supabase project setup**, and **Schema** sections are done, Phases 0–3 can land. Once **RLS** and **Secret management** are also done, Phase 7 smoke can proceed. The **Test data** section only gates the manual smoke.
# 002 - Supabase Read Access

Phase buckets mapped from the `roadmap.md` 002 checklist (auth hand-off, identity verification, scoped client, context builder, data minimization, scoping verification). Auth + client phases have no Supabase-schema dependency and land first; the context-builder phase is gated on `users-tasks.md` schema confirmation. Manual/external items are flagged.

## Phase 0 — Pre-flight & constitution sync

- [x] Confirm decisions in `plan.md`: auth hand-off (Bearer header), JWT verification (local HS256), scoped client (RLS via access token), `plant_id` request field, photo handling (metadata only), Supabase library, `401` code, context caps
- [x] Add deps to `pyproject.toml`: `supabase` (async client) and `pyjwt`
- [x] Add settings to `app/config/settings.py`: `supabase_url`, `supabase_jwt_secret`, `auth_jwt_audience` (default `"authenticated"`), `context_max_plants` (20), `context_max_recent_entries` (10)
- [x] Update `.env.example`: `SUPABASE_URL`, `SUPABASE_JWT_SECRET`, `AUTH_JWT_AUDIENCE` (optional)
- [x] Extend `spec/constitution/tech-stack.md`: add `app/auth/` and `app/supabase/` to the file map, list new settings/env vars, reframe V0.1 hard limits (`No Supabase`, `No auth`) as V0.1-scoped so V1.0 features can lift them
- [x] Confirm the `users-tasks.md` Supabase/JWT prerequisites are understood (Secret Manager secret, RLS policies) before Phase 3 lands

## Phase 1 — Auth hand-off & JWT verification (no schema dependency)

- [x] Create `app/auth/` package (`__init__.py`)
- [x] `app/auth/tokens.py`: `verify_access_token(token, settings) -> claims` using PyJWT — HS256, audience `authenticated`, issuer `f"{supabase_url}/auth/v1"`, require `exp`/`iss`/`sub`/`aud`; raise `AuthError`
- [x] `app/auth/dependency.py`: `get_authenticated_user(request: Request) -> UserIdentity` — read `Authorization: Bearer <token>`, verify, return `UserIdentity(sub=str)`
- [x] `app/api/errors.py`: add `auth_exception_handler` → `401 {"error":{"code":"UNAUTHORIZED","message":"Debes iniciar sesión para continuar."}}`; never log/return the token
- [x] `app/main.py`: wire `AuthError` handler alongside the existing handlers
- [x] `app/api/routes.py`: `/chat` now takes the auth dependency (returns 401 without a valid token)
- [x] Tests (`tests/test_auth.py`): missing header → 401; malformed token → 401; expired token → 401; bad-signature → 401; valid token → request proceeds
- [x] Existing tests updated for the new required header (fixtures inject a valid token)

## Phase 2 — Scoped Supabase client (RLS) (no schema dependency)

- [x] Create `app/supabase/` package (`__init__.py`)
- [x] `app/supabase/client.py`: `build_user_client(url, access_token) -> AsyncClient` — `create_async_client(url, access_token)` so PostgREST verifies the JWT and `auth.uid()` resolves
- [ ] Confirm PostgREST applies RLS with the user token (probe against a scratch table or `/rest/v1/`); document the verified behavior
- [ ] Test: cross-user read returns zero rows (RLS) — assert the builder's reads go through the user-scoped token, never a service-role key
- [x] Test: a Supabase/network failure on read raises the existing `UpstreamError` → `502 UPSTREAM_ERROR` with no token/secret leaked

## Phase 3 — Context builder (gated on `users-tasks.md` schema confirmation)

- [ ] **Gated on:** user confirms the real Supabase schema (table + column names) in `users-tasks.md`
- [x] `app/supabase/schema.py`: centralize `TABLE_*` / `COL_*` constants for plants, logbook/journal, watering history, watering schedule, light readings, fertilizations, repottings, observations, photos
- [x] `app/supabase/context.py`: `build_plant_context(client, user_id, plant_id) -> ContextBundle`
  - Light mode (no `plant_id`): ≤ `context_max_plants` plants with name/species/last+next watering — "what needs attention today" slice
  - Deep mode (`plant_id` set): one plant + ≤ `context_max_recent_entries` recent entries per history type + photo metadata (count + last-taken date, **not** URLs/bytes)
  - Enforce `.limit()` and date windows everywhere; raise `UpstreamError` on Supabase failures
- [x] `UserIdentity.sub` used for logging/meaning only — never for manual `user_id` filtering (RLS does isolation)
- [x] Tests: light-mode result shape; deep-mode result shape; data-minimization bounds honored (`.limit(N)` asserted via mock call inspection); foreign `plant_id` treated as empty context (RLS deny)
- [x] Tests: context contents never appear in logs (only counts/durations)

## Phase 4 — Wire context into the agent loop

- [x] `app/agent/loop.py`: extend `call_gemini(...)` with `context: str | None`; inject the context block before the user message (or fold into `system_instruction`), keeping the existing `UpstreamError` path intact
- [x] `app/agent/prompts.py`: add a section instructing Flora to use the provided plant context, stay honest, not invent beyond it, and keep every 001 persona rule (Spanish-only, reasoning, concrete next step, calm, off-topic refusal)
- [x] `app/api/routes.py`: `/chat` request gains optional `plant_id: str | None`; build context with the user-scoped client; pass `context` into `call_gemini`
- [x] Tests (`tests/test_chat_context.py`): context block is passed to `call_gemini` when data exists; deep path used when `plant_id` set; light path when absent; reply still Spanish-only + off-topic refusal still works with context present

## Phase 5 — Contract & docs

- [x] `docs/api-contract.md`: document required `Authorization: Bearer` header, optional `plant_id` request field, `401 UNAUTHORIZED` in the error-code table, and a one-line privacy/RLS note
- [x] `README.md`: add `SUPABASE_URL` / `SUPABASE_JWT_SECRET` to the local-dev env list
- [x] `spec/constitution/tech-stack.md`: confirm file map + settings reflect `app/auth/` and `app/supabase/` (edited in Phase 0)

## Phase 6 — Tests (full regression)

- [x] New: auth 401 paths (Phase 1) pass
- [x] New: RLS deny + data-minimization + 502 on Supabase failure (Phases 2–3) pass
- [x] New: context injection, deep vs light (Phase 4) pass
- [x] Regression: `/health`, `/chat` reply, 422, 502 Gemini, 500 internal all still pass
- [x] Regression: 001 off-topic refusal + Spanish-only still pass with context in flight
- [ ] `uv run ruff check` and `uv run ruff format --check` pass

## Phase 7 — Manual smoke (gated on a real Supabase project + seeded test user)

- [ ] **Gated on:** `users-tasks.md` Supabase prerequisites complete (project URL, JWT secret in Secret Manager, RLS policies enabled, seeded test user + plants)
- [ ] A few real `/chat` calls: with a `plant_id` (verify Flora references that plant's real watering/log); without `plant_id` (verify light "what needs attention today"); with an expired token (verify 401)
- [ ] Confirm input-token cost / latency acceptable on the deep path; tune caps if needed
- [ ] Update `spec/constitution/roadmap.md`: mark 002 done
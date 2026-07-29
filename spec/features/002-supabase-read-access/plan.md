# 002 - Supabase Read Access

## Approach

Layer Supabase read access onto the existing stateless `/chat` endpoint — no new routes, no persistence, no streaming. The work is the strip of logic that sits *before* `call_gemini`: prove who the caller is, build a row-level-secured client scoped to that user, pull a minimized slice of their plant data, and hand it to Flora as context. 001 already locked the voice and guardrails; 002 feeds those guardrails real plants instead of generic ones.

Security/privacy is the dominant design axis — not throughput. A buggy read path could expose another user's plants, which violates the **Trustworthy** core value directly. So the architecture is "trust the database to isolate, then verify it does," rather than "trust the agent to filter":

- **Identity** is a Supabase access token the app already has; the agent only verifies it, never obtains it. Local HS256 decode with the JWT secret (offline, fast) — plus an extra safety net because Supabase PostgREST independently re-verifies the same JWT before applying RLS.
- **Isolation** is Row Level Security on the Supabase side, applied because the client is built with the user's access token (`auth.uid() = sub`). Application code never selects rows by `user_id` on its own — that would be a *second*, weaker fence. RLS is the fence; the agent's job is to use it and test that it holds.
- **Minimization** is enforced by bounded `.limit()` queries, date windows, and summarizing photos as counts/dates rather than URLs or bytes.

Sequenced so each phase produces something verifiable, and so the auth + client work (which has **no** schema dependency) can land before the context builder (which does):

1. **Pre-flight & constitution sync** — confirm the decisions below, add Supabase deps to `pyproject.toml`, add settings + `.env.example`, and extend `tech-stack.md`'s file map/settings so the constitution reflects V1.0 reality (the same reconciliation pattern 001 used for the OpenAI→Gemini drift).
2. **Auth hand-off & JWT verification** — `app/auth/` module: read `Authorization: Bearer`, verify the JWT with the secret (HS256, audience `authenticated`, issuer, expiry), extract `sub`; FastAPI dependency yields a `UserIdentity`; `401 UNAUTHORIZED` in the uniform envelope. `/chat` now requires auth. No Supabase schema needed.
3. **Scoped Supabase client (RLS)** — `app/supabase/client.py` builds a per-request async client using the access token as the key, so every read runs under `auth.uid() = sub`. Verify PostgREST applies RLS; test cross-user denial. No schema needed beyond a probe endpoint.
4. **Context builder (gated on user confirming schema)** — `app/supabase/schema.py` centralizes the real table/column names; `app/supabase/context.py` produces a light inventory (all plants, last/next watering) or a deep bundle (one `plant_id`: recent log, watering, light, fertilizations, repottings, observations, photo metadata) via bounded `.limit()` queries. Gated on `users-tasks.md` schema confirmation.
5. **Wire context into the agent loop** — `/chat` accepts optional `plant_id`, builds context, passes a compact Spanish-friendly block into `call_gemini`; `prompts.py` gets a section telling Flora to use the provided plant context, stay honest, not invent beyond it, and keep every 001 rule.
6. **Contract & docs** — update `docs/api-contract.md` (header, optional `plant_id`, `401`, privacy/RLS note); README Supabase env vars.
7. **Tests** — 401 paths, context injection (deep vs light), RLS deny, data-minimization bounds, 502 on Supabase failure, and the 001 regression suite with context in flight. Mock both Gemini and Supabase in CI.
8. **Manual smoke (gated on a real test Supabase user/token)** — a few real `/chat` calls against a seeded project; verify Flora references actual plants; then move 002 to Done in `roadmap.md`.

## Implementation

Files 002 touches (increment over the existing layout; new modules marked `+`):

```
app/
├── auth/                        # +
│   ├── __init__.py
│   ├── tokens.py                # verify_access_token(token, settings) -> claims; AuthError
│   └── dependency.py           # get_authenticated_user(request) -> UserIdentity (reads ''Authorization'')
├── supabase/                    # +
│   ├── __init__.py
│   ├── client.py                # build_user_client(url, access_token) -> AsyncClient (RLS-scoped)
│   ├── schema.py                # TABLE_* / COL_* name constants reconciled with real Supabase schema
│   └── context.py               # build_plant_context(client, user_id, plant_id) -> ContextBundle
├── agent/
│   ├── loop.py                  # call_gemini(..., context: str | None) — inject context block
│   └── prompts.py               # + section: how to use provided plant context (honest, no invention)
├── api/
│   ├── routes.py                # /chat: auth dep + optional plant_id; build context; pass to gemini
│   └── errors.py                # + auth_exception_handler -> 401 UNAUTHORIZED envelope
├── config/
│   └── settings.py              # + supabase_url, supabase_jwt_secret, auth_jwt_audience, context caps
└── main.py                      # wire auth exception handler

docs/
└── api-contract.md              # Authorization header, optional plant_id, 401, privacy/RLS note

tests/
├── conftest.py                  # + valid/invalid JWT helpers, supabase client mock fixture
├── test_auth.py                 # + 401 missing / malformed / expired / bad-signature
└── test_chat_context.py         # + injection, plant_id deep path, RLS deny, minimization, 502

spec/constitution/
├── tech-stack.md                # + app/auth, app/supabase in file map; new settings/env; V0.1 limits scoped
└── roadmap.md                   # mark 002 items Done at the very end

.py subs:
├── pyproject.toml               # + supabase, pyjwt
└── .env.example                 # + SUPABASE_URL, SUPABASE_JWT_SECRET
```

Key flows (delta from 001):

- **`/chat` request** — gains an optional field:
  ```json
  { "message": "string (1–2000)", "plant_id": "string | null (optional)" }
  ```
  and a **required** header `Authorization: Bearer <supabase_access_token>`.
- **`/chat` happy path** — `get_authenticated_user` verifies the JWT → `UserIdentity(sub)`. A scoped Supabase client is built with the access token. `build_plant_context` runs (deep if `plant_id` set, light otherwise). `call_gemini(message, ..., context=context_block)` injects the context before the user message; Flora replies in Spanish with the 001 persona. `200 {"reply":"..."}`.
- **Auth error path** — `AuthError` (raised on missing header, malformed JWT, bad signature, expired, wrong audience/issuer) → handler in `errors.py` → `401 {"error":{"code":"UNAUTHORIZED","message":"Debes iniciar sesión para continuar."}}`. The message never includes the token.
- **Supabase error path** — a `supabase-py`/network error on a read raises a typed `UpstreamError` (reuse the existing class), reusing the existing `502 UPSTREAM_ERROR` handler. Auth still completed first, so no foreign data ever leaks.
- **RLS path** — a `plant_id` that is not the caller's: RLS returns zero rows; the context builder treats "no plant" as empty-context-for-that-topic; Flora says so honestly rather than inventing. Asserted in tests.
- **Data-minimization** — `schema.py` centralizes everything the builder reads; `context.py` calls `.limit(context_max_recent_entries)` and skips fields it doesn't need (e.g. photo URLs/bytes in 002). Tests assert the bound.

Settings added to `app/config/settings.py`:

```python
supabase_url: str
supabase_jwt_secret: str  # secret — Secret Manager in Cloud Run, .env in dev
auth_jwt_audience: str = "authenticated"
context_max_plants: int = 20  # light-mode cap
context_max_recent_entries: int = 10  # deep-mode cap per history type
```

JWT verification uses PyJWT: `jwt.decode(token, secret, algorithms=["HS256"], audience=aud, issuer=f"{url}/auth/v1", options={"require": ["exp", "iss", "sub", "aud"]})`. The exact claims (especially `aud`) are confirmed against the project's Supabase version in `users-tasks.md`.

The Supabase client is built per request (stateless): `create_async_client(supabase_url, access_token)` — using the access token as the key means PostgREST verifies it and `auth.uid()` resolves per call. We verify locally first for clean 401s and to extract `sub` without a round-trip; PostgREST re-verifying is intentional defense-in-depth, not a contradiction.

## Decisions

Recommended defaults, all confirmable before code touches:

- **Auth hand-off.** `Authorization: Bearer <supabase_access_token>` on `/chat`. The agent verifies, never authenticates. Confirm.
- **Token verification.** Local HS256 decode with the Supabase JWT secret, offline — preferred over calling Supabase's `/auth/v1/user` endpoint because it is one fewer network round-trip per request and gives a clean 401 before any data fetch. Confirm.
- **Scoped client strategy.** RLS-scoped reads using the user's access token (defense-in-depth). **Rejected:** service-role key with app-level `user_id` filtering — it bypasses the only fence if a query forgets the filter. Confirm.
- **JWT secret in Secret Manager.** New secret `supabase-jwt-secret` (mirrors the `gemini-api-key` pattern). Never in code/images/logs. Confirm.
- **`plant_id` on `/chat`.** Optional. Matches `mission.md`'s "each plant has its own space where its entire history lives." Light inventory when absent. Confirm.
- **Photo handling in 002.** Metadata only — count + last-taken date, never URLs or bytes. Image content analysis is 004. Confirm.
- **Supabase library.** Official `supabase-py` async client (`create_async_client`). Confirm async support meets the load profile; if async ergonomics are poor, fall back to sync client in a threadpool, but prefer async.
- **New error code.** `401 UNAUTHORIZED`. **No 403:** RLS turns "can't see that row" into "that row doesn't exist," so a distinct 403 adds nothing honest. Confirm.
- **Context depth.** Light = ≤ `context_max_plants` with name/species/last+next watering. Deep = one plant + ≤ `context_max_recent_entries` per history type (log, watering, light, fertilizations, repottings, observations) + photo metadata. No multi-plant deep mode in 002 (Out of reach). Confirm caps.
- **Context injection point.** A compact block prepended to the user `contents` (or folded into `system_instruction`) — the existing `call_gemini` signature gains an optional `context: str | None`. Spanish labels in the block so Flora's reasoning stays Spanish-grounded. Confirm.
- **Reusing `UpstreamError`.** Supabase failures map to the existing `UpstreamError` → `502 UPSTREAM_ERROR`. No new "SUPABASE_ERROR" code (keeps the error-code table small). Confirm.
- **Schema ownership.** Tables/columns live in the app's Supabase project; 002 reads only. Real names centralized in `schema.py`; confirmation gated in `users-tasks.md`. Confirm this is acceptable (vs. the agent owning schema docs), given the mission states the agent has no database of its own.

## Risks

- **Schema unknown (highest).** The context builder needs the real Supabase table/column names, which 002 does not control — they live in the app's project. Mitigation: centralize names in `schema.py`; gate the builder phase behind `users-tasks.md` schema confirmation; ship auth + client phases first (no schema dependency) so the feature is not blocked end-to-end.
- **RLS misconfigured on the Supabase side.** The agent's entire privacy posture assumes RLS policies (`auth.uid() = sub`) exist on every readable table. Mitigation: `users-tasks.md` requires RLS enabled with per-uid policies verified before smoke; a CI test asserts the builder reaches reads *through* the user-scoped token so that, even if an app code path forgot a filter, RLS is the backstop. Still, a misconfigured policy is a Supabase-side responsibility the agent can detect but not fix — flagged as a manual prerequisite.
- **JWT secret handling.** A leaked JWT secret lets an attacker forge tokens. Mitigation: Secret Manager only, never in logs/images; reuse 000's secret conventions. Low likelihood, high impact.
- **Token lifetime / refresh.** The agent is stateless; an expired access token yields 401 and the app must refresh. There is no graceful degradation. Mitigation: documented behavior; the *app* refreshes and retries. This is by design (mission: agent does not handle authentication) but could feel abrupt in the UX — coordinate the 401 message with the app team so the client handles it gracefully.
- **Context bloat / input-token cost.** Deep context across many history types could swell the Gemini input. Mitigation: bounded `.limit()`, date windows, photo metadata (not URLs/bytes), and tuned caps; re-evaluate after smoke against a real, seeded project.
- **Supabase latency adds a round-trip before Gemini.** Each `/chat` now does JWT decode + several Supabase reads + one Gemini call. Mitigation: bounded queries; parallelize independent reads in the builder; keep Cloud Run timeouts honest. Larger latency impact to quantify in smoke.
- **Privacy in logs.** Journal text is personal. Mitigation: log only row counts and durations, never context contents; consistent with the existing "one log per request" convention.
- **`supabase-py` async maturity.** If the async client is unstable, fall back to the sync client in a threadpool. Confirm before committing fully.
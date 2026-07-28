# 003 - Supabase Write Actions

Phase buckets mapped from the `roadmap.md` 003 checklist (writable surface, proposed-action flow, confirm-and-execute endpoint, example watering flow, write-under-identity, save-a-tip flow, audit logging). The registry + token phases have no Supabase-write dependency and land first; the execute + handler phases are gated on `users-tasks.md` RLS `INSERT` policy confirmation. Manual/external items are flagged.

## Phase 0 — Pre-flight & constitution sync

- [ ] Confirm decisions in `plan.md`: writable surface (two verbs), two-step propose→confirm→execute, `confirm_token` (HMAC, single-use, 5 min), in-process nonce store, writes under user token only (RLS), `400 INVALID_ACTION` vs `401`, `502` reuse, structured-output proposals, audit as agent logs, deactivate-then-insert, save-a-tip always `type=observation`
- [ ] Add settings to `app/config/settings.py`: `action_signing_secret` (Secret Manager / `.env`), `action_token_ttl_seconds` (default `300`)
- [ ] Update `.env.example`: `ACTION_SIGNING_SECRET`, `ACTION_TOKEN_TTL_SECONDS` (optional)
- [ ] Extend `spec/constitution/tech-stack.md`: add `app/actions/` to the file map, list the new settings/env vars, reframe the V0.1 "no writes" hard limit as lifted by 003
- [ ] Confirm the `users-tasks.md` RLS `INSERT` prerequisites (policies on `watering_schedules` + `journal_entries`) before Phase 5 lands

## Phase 1 — Action registry & payload models (no Supabase dependency)

- [ ] Create `app/actions/` package (`__init__.py`)
- [ ] `app/actions/models.py`: `CreateWateringSchedulePayload` (`frequency_days >=1`, `last_watered_at`, `next_due_at`, `notify_time` optional), `AddJournalEntryPayload` (`content` 1–2000 chars, `type="observation"` fixed), `ProposedAction` (`action_type`, `plant_id`, `title`, `summary_es`, `payload`, `confirm_token`), `ExecuteRequest`, `ExecuteResponse`, and a `ChatResponse` with `reply` + `proposed_action | null`
- [ ] `app/actions/registry.py`: `ALLOWED_ACTIONS` mapping `action_type -> (table, operation, payload_model, handler_ref)`; `resolve_action(action_type) -> ActionSpec` or `None`; `payload_digest(payload, plant_id) -> str` (`sha256` of the canonical JSON, truncated)
- [ ] Tests (`tests/test_actions_registry.py`): each action resolves; unknown action resolves to None; payload models validate/reject edge cases; `payload_digest` is stable and changes when the payload changes

## Phase 2 — Confirm token (no Supabase dependency)

- [ ] `app/actions/tokens.py`: `issue_confirm_token(action_type, plant_id, payload, user_sub, settings) -> str` (HMAC-SHA256 over `payload_digest|sub|exp|nonce`, base64url, constant-time-safe); `verify_confirm_token(token, action_type, plant_id, payload, user_sub, settings) -> None` raising `AuthError` (401) on bad signature / `sub` / expiry / replayed nonce, `InvalidActionError` (400) on payload-hash mismatch
- [ ] In-process nonce store (module-level dict keyed by nonce → exp; prune on read; documented multi-instance caveat in a docstring)
- [ ] Tests (`tests/test_action_tokens.py`): valid round-trip; tampered signature → 401; `sub` mismatch → 401; expired → 401; replay after consume → 401; payload altered → 400; nonce/time pruning

## Phase 3 — Propose within `/chat`

- [ ] `app/agent/prompts.py`: add a section telling Flora when to propose an action (only for the two verbs, only for a plant present in her context, never spontaneously, never for off-topic), the field shapes she should fill, and that proposing is side-effect-free; keep every 001/002 rule (Spanish-only, reasoning, concrete next step, calm, off-topic refusal)
- [ ] `app/agent/loop.py`: `call_gemini(...)` returns `(reply, proposed_action_raw | None)` via Gemini structured output (`response_schema` describing the union of the two action payloads); on model-unsupported, fall back to a constrained JSON-only follow-up call; never block the reply on a malformed proposal
- [ ] `app/api/routes.py`: `/chat` validates `proposed_action_raw` against the registry's Pydantic model; on valid, mint a `confirm_token` and attach `proposed_action` to the response; on invalid/absent, set `proposed_action` to `null` and still return `reply`
- [ ] Tests (`tests/test_actions_propose.py`): `/chat` returns a `proposed_action` when actionable intent present (watering offer, save-a-tip ask); `proposed_action` is `null` for general advice with no intent; payload matches the allowlist shapes; `plant_id` of the proposal is the request's `plant_id` (deep context only); foreign/missing `plant_id` ⇒ no proposal; reply still Spanish-only + off-topic refusal still works with actions in flight

## Phase 4 — Execute endpoint & error wiring (handlers gated on `users-tasks.md` RLS `INSERT` confirmation)

- [ ] `app/api/errors.py`: add `invalid_action_exception_handler` → `400 {"error":{"code":"INVALID_ACTION","message":"..."}}`; wire it in `app/main.py`
- [ ] `app/actions/routes.py` (or extend `app/api/routes.py`): `POST /actions/execute` — auth dep (reuse 002) → `verify_confirm_token` → `registry.resolve_action` (allowlist) → validate `payload` with the model → `build_user_client` → dispatch to handler → return `201 ExecuteResponse`
- [ ] `app/actions/handlers.py`: `create_watering_schedule(client, plant_id, payload)` — `update active=false where plant_id=.. and active=true` then `insert` new active; returns the new row id; on insert failure, best-effort re-activate the old row + `UpstreamError`. `add_journal_entry(client, plant_id, payload)` — `insert` with `type="observation"`, `content` from payload, **never** set `user_id` (RLS/DB sets it); defensively drop any `user_id` key from the insert dict; returns the new row id
- [ ] Both handlers raise the existing `UpstreamError` → `502` on Supabase/network failure; never log the access token or `content`
- [ ] **Gated on:** `users-tasks.md` confirms RLS `INSERT` policies (`auth.uid() = user_id` with `WITH CHECK`) exist on `watering_schedules` and `journal_entries`

## Phase 5 — Audit logging

- [ ] `app/actions/audit.py`: `log_action_executed(action_type, table, plant_id, action_id, user_sub, status, duration_ms, payload_digest)` → structlog JSON event; for `add_journal_entry` the event **never** includes `content`
- [ ] `app/actions/routes.py`: call `log_action_executed` on success (`status="executed"`) and on `502` failure (`status="upstream_error"`, no `action_id`)
- [ ] Tests: audit event emitted with the right fields on a successful execute; audit event emitted on a 502 with `status="upstream_error"`; `content` never present in a journal audit event (assert against the captured log record)

## Phase 6 — Contract & docs

- [ ] `docs/api-contract.md`: document the optional `proposed_action` on the `/chat` response, the `POST /actions/execute` route (request + `201`/`401`/`400`/`502` responses), the `confirm_token` model (signed, single-use, 5 min), the new `400 INVALID_ACTION` code in the error table, and the writable-surface allowlist with the two V1.0 verbs
- [ ] `README.md`: add `ACTION_SIGNING_SECRET` to the local-dev env list
- [ ] `spec/constitution/tech-stack.md`: confirm file map + settings reflect `app/actions/` and the secret (edited in Phase 0)

## Phase 7 — Tests (full regression)

- [ ] New: registry + token unit tests (Phases 1–2) pass
- [ ] New: `/chat` proposal behaviour (Phase 3) pass
- [ ] New: execute happy paths (each verb), 401 token paths, 400 allowlist/hash, 502 Supabase, watering deactivate-then-insert, save-a-tip (Phase 4) pass
- [ ] New: RLS-write assertion — handler writes use the user access token (assert against the mock client), and `user_id` is never supplied to the insert
- [ ] New: audit fields + no-content-logged (Phase 5) pass
- [ ] Regression: 002 `/health`, `/chat` reply, auth 401 paths, context injection, RLS deny, data-minimization, 502, off-topic refusal, Spanish-only still pass with actions in flight
- [ ] `uv run ruff check` and `uv run ruff format --check` pass

## Phase 8 — Manual smoke (gated on a real Supabase project + write-enabled RLS)

- [ ] **Gated on:** `users-tasks.md` RLS `INSERT` prerequisites on `watering_schedules` and `journal_entries`, an `ACTION_SIGNING_SECRET` in Secret Manager / `.env`, and a seeded test user + plant
- [ ] Real propose→confirm→execute: a `/chat` watering offer → user confirms → `POST /actions/execute` → verify the schedule row exists and the prior active schedule is deactivated (all under the user's RLS-scoped token)
- [ ] Real save-a-tip: ask Flora to save a snippet to a plant's journal → confirm → verify an `observation` `journal_entries` row exists with the snippet as `content`
- [ ] Real 401: execute with an expired `confirm_token`; execute with a token whose `payload` was edited in the client
- [ ] Confirm the audit log line in Cloud Logging has the expected fields and no journal `content`
- [ ] Update `spec/constitution/roadmap.md`: mark 003 done
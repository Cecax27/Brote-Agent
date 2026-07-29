# 003 - Supabase Write Actions

## Approach

Layer a **propose → confirm → execute** flow on top of 002 without disturbing the stateless single-shot shape of `/chat` or its persona. Reads already happen (002); 003 adds a *second*, opt-in half: Flora can *offer* an action in her reply, and a separate endpoint performs it only after the user confirms out-of-band in the app. The agent never writes spontaneously, never writes outside an allowlist, and never writes under any identity but the caller's — RLS is the ownership fence (same posture as 002), and a server-signed `confirm_token` is the provenance fence (new in 003).

The dominant design axis is safety of a mutation, not latency. A read gone wrong leaks a row; a write gone wrong creates a row in the wrong garden, logs a fabricated entry, or lets the app forge an action the AI never proposed. So the architecture is **"three independent fences, any one of which stops a bad write":**

1. **Allowlist** (`app/actions/registry.py`) — only `(create_watering_schedule, add_journal_entry)` are legal `(action_type, table, operation)` triples, each with a Pydantic payload model. Anything else → `400 INVALID_ACTION`. No table name from the request ever reaches SQL directly; the registry maps `action_type` → fixed table + columns.
2. **Provenance** (`confirm_token`) — every action proposed by Flora is signed by the agent (HMAC-SHA256 over `hash(payload+plant_id) | sub | expiry | nonce` with `ACTION_SIGNING_SECRET`). The confirm endpoint re-verifies signature, `sub`, expiry, single-use nonce, and **payload-hash match**. The app cannot fabricate an action (no secret), cannot replay (nonce + single-use), cannot swap the payload (hash mismatch → `400`), and cannot act for another user (`sub` mismatch → `401`). The token is short-lived (default 5 min) to match a conversation confirm, not a session.
3. **Ownership** (RLS, reused from 002) — writes go through the **same** `build_user_client(url, anon_key, user.access_token)` so PostgREST re-verifies the JWT and `auth.uid()` resolves; the row's `user_id` is set by the database/RLS, never by the request body. A `user_id` column in the insert payload is **dropped** before the write, defensively.

The two-step flow keeps `/chat` side-effect-free: proposing costs nothing and writes nothing. This is deliberate — it lets the user close the app after a suggestion with zero data drift, and it keeps the confirm endpoint as the single, audited place where mutations happen. It also keeps 002's privacy contract intact: a `/chat` reply that proposes an action has not written anything, so a "no thanks" leaves the world unchanged.

Sequenced so each phase produces something verifiable, and so the allowlist + token machinery (no schema-write dependency beyond what 002 already confirmed) lands before the Supabase write paths:

1. **Pre-flight & constitution sync** — confirm decisions; add `ACTION_SIGNING_SECRET` + action settings; extend `tech-stack.md`'s file map/settings and reframe the V0.1 "no writes" limit as lifted by 003 (same reconciliation pattern 001/002 used).
2. **Action registry & payload models** — `app/actions/registry.py` with the allowlisted `action_type`s and Pydantic payload models (`CreateWateringSchedulePayload`, `AddJournalEntryPayload`); `app/actions/models.py` for `ProposedAction`, `ExecuteRequest`, `ExecuteResponse`; a `to_payload_digest` helper. No Supabase dependency.
3. **Confirm token** — `app/actions/tokens.py`: `issue_confirm_token(action_type, plant_id, payload, user_sub, settings) -> str` and `verify_confirm_token(token, action_type, plant_id, payload, user_sub, settings) -> None | raises AuthError/InvalidActionError`. HMAC-SHA256, base64url, single-use nonce store (in-memory dict keyed by nonce; Cloud Run instances are short-lived and this is single-use replay protection, not cross-instance coordination — see Risks). No Supabase dependency.
4. **Propose within `/chat`** — extend the `/chat` response with optional `proposed_action`. Flora is prompted (new `prompts.py` section) to elect an action; the action payload is extracted via **Gemini structured output** (`response_mime_type="application/json"`, `response_schema`) so the proposal is schema-validated by Gemini itself, then re-validated by the registry's Pydantic model. If Flora elects no action, `proposed_action` is `null`. `call_gemini` returns `(reply, proposed_action_raw | None)`; the route issues the `confirm_token` only after validating the payload, so tokens are never minted for malformed proposals. `/chat` stays side-effect-free.
5. **Execute endpoint** — `POST /actions/execute` (new route, `app/actions/routes.py` or extend `app/api/routes.py`): auth dependency (reuse 002) → verify token → registry lookup (allowlist) → validate payload Pydantic → `build_user_client` → dispatch to the action handler → return `201`. `400 INVALID_ACTION` for allowlist/hash mismatches; `401` for token issues; `502 UPSTREAM_ERROR` (reuse 002's envelope) for Supabase failures.
6. **Action handlers** — `app/actions/handlers.py`: `create_watering_schedule(client, plant_id, payload)` deactivates the user's prior active schedule for that plant then inserts the new one; `add_journal_entry(client, plant_id, payload)` inserts an `observation` row. Both go through the user-scoped client; both raise `UpstreamError` on Supabase failures; both return the new row id.
7. **Audit logging** — a single `log_action_executed(...)` helper emitting the structured event; the execute route calls it on success and on 502 failure. `content` of journal entries is never logged (only `payload_digest`).
8. **Contract & docs** — extend `docs/api-contract.md` (proposed_action field, `/actions/execute`, `400 INVALID_ACTION`, `confirm_token` model, allowlist); README env vars; `tech-stack.md` file map.
9. **Tests** — propose/confirm/execute matrix, allowlist enforcement, token lifecycle, payload-hash mismatch, RLS-write assertion (write uses access token, not service-role key), watering-schedule deactivate-then-insert, save-a-tip, 502 on Supabase failure, audit fields + no-content-logged, 001/002 regression with actions in flight. Mock Gemini + Supabase in CI.
10. **Manual smoke (gated on a real Supabase user/token + write-enabled RLS policies)** — real propose→confirm→execute against a seeded project; then move 003 to Done in `roadmap.md`.

## Implementation

Files 003 touches (increment over 002's layout; new modules marked `+`):

```
app/
├── actions/                       # +
│   ├── __init__.py
│   ├── registry.py                # ALLOWED_ACTIONS: action_type -> (table, op, Pydantic payload model); resolve_action()
│   ├── models.py                  # ProposedAction, CreateWateringSchedulePayload, AddJournalEntryPayload,
│   │                              #   ExecuteRequest, ExecuteResponse, ChatResponse (reply + proposed_action | null)
│   ├── tokens.py                  # issue_confirm_token / verify_confirm_token; ConfirmTokenError, reuse AuthError
│   ├── handlers.py                # create_watering_schedule(client, plant_id, payload) -> id;
│   │                              #   add_journal_entry(client, plant_id, payload) -> id
│   ├── audit.py                   # log_action_executed(...) -> structured structlog event (no content)
│   └── routes.py                  # POST /actions/execute (auth dep + token verify + registry + handler + audit)
├── agent/
│   ├── loop.py                     # call_gemini returns (reply, proposed_action_raw | None) via
│   │                              #   Gemini response_schema (action schema); reply still Spanish
│   └── prompts.py                  # + section: when to propose an action, the two verbs, the field shapes,
│                                  #   never write spontaneously, never propose for a plant you can't see
├── api/
│   ├── routes.py                   # /chat response gains optional proposed_action; mints confirm_token after
│   │                              #   validating the proposal against the registry's Pydantic model
│   └── errors.py                   # + invalid_action_exception_handler -> 400 INVALID_ACTION envelope
├── supabase/
│   ├── schema.py                   # + any columns 003 writes (already has watering_schedules + journal_entries cols)
│   └── client.py                   # unchanged (reused for writes; user-scoped)
├── config/
│   └── settings.py                 # + action_signing_secret, action_token_ttl_seconds (default 300)
└── main.py                         # wire InvalidActionError handler; mount actions router

docs/
└── api-contract.md                 # proposed_action on /chat; POST /actions/execute; 400 INVALID_ACTION;
                                   #   confirm_token model; writable-surface allowlist

tests/
├── conftest.py                     # + action token helpers; Supabase write mock fixture
├── test_actions_propose.py         # + /chat returns proposed_action when intent present; null when absent;
│                                   #   payload matches allowlist shapes; foreign plant never proposed
├── test_actions_execute.py         # + happy path (each verb); 401 token paths; 400 allowlist/hash; 502 Supabase;
│                                   #   watering deactivate-then-insert; save-a-tip; RLS-write assertion (access token used,
│                                   #   user_id never supplied to insert); audit fields + no content logged
└── test_chat.py / test_chat_context.py   #   002 regressions still green with actions in flight

spec/constitution/
├── tech-stack.md                   # + app/actions/ in file map; ACTION_SIGNING_SECRET + ttl settings; "no writes" lifted
└── roadmap.md                      # mark 003 items Done at the very end

.py subs:
├── pyproject.toml                  # (no new runtime dep; HMAC + base64 are stdlib. Confirm consts.)
└── .env.example                    # + ACTION_SIGNING_SECRET
```

Key flows (delta from 002):

- **`/chat` response** — gains an optional sibling to `reply`:
  ```json
  {
    "reply": "string (Spanish, on-brand)",
    "proposed_action": {
      "action_type": "create_watering_schedule | add_journal_entry",
      "plant_id": "uuid",
      "title": "string (short, ES)",
      "summary_es": "string (ES confirmation line for the app's card)",
      "payload": { "..." },
      "confirm_token": "string (signed, single-use, short ttl)"
    } | null
  }
  ```
  The handler issues `proposed_action` only when Gemini returns a valid action payload that the registry's Pydantic model accepts and whose `plant_id` is the one in the request (deep context only — no proposing for plants Flora can't see, so RLS-driven empty context ⇒ no proposal).
- **`POST /actions/execute` request:**
  ```json
  {
    "action_type": "create_watering_schedule | add_journal_entry",
    "plant_id": "uuid",
    "payload": { "..." },
    "confirm_token": "string"
  }
  ```
  **Headers:** `Authorization: Bearer <supabase_access_token>` (required, same as `/chat`).
- **`POST /actions/execute` happy path** — `get_authenticated_user` → `UserIdentity`. `verify_confirm_token` (signature + `sub` + expiry + nonce + payload hash). `registry.resolve_action(action_type)` → `(table, op, payload_model, handler)`. Validate `payload` with the model. `build_user_client(...)`. Handler performs the write via the user-scoped token → new row id. `log_action_executed`. `201 ExecuteResponse`.
- **Provenance path** — a token whose signature, `sub`, expiry, or nonce fails → `AuthError` → `401`. A token whose bound payload hash ≠ `hash(payload+plant_id)` from the request → `InvalidActionError` → `400 INVALID_ACTION`. An `action_type` not in the registry → `400 INVALID_ACTION`. The nonce is marked consumed on a *successful* execute; a replay → `401`.
- **RLS / ownership path** — handlers call `client.table(...).insert({...})` with the user-scoped client; `user_id` is **not** set in the insert dict (the DB default / RLS sets it). If a hand-crafted request tries to set `user_id`, the handler drops the key defensively. RLS `INSERT` policies on `watering_schedules` and `journal_entries` (verified in `users-tasks.md`) enforce `auth.uid() = user_id`; a missing policy means the insert is rejected by PostgREST → `502 UPSTREAM_ERROR` (the message stays generic; the failure is the safety net working, surfaced as upstream error).
- **Watering-schedule atomicity** — `create_watering_schedule` does `update active=false where plant_id=.. and user_id=auth.uid() and active=true` then `insert new`. If the insert fails after the update, Cloud Run instances are stateless and the user sees a 502 with the *old* schedule deactivated — acknowledged in Risks. Mitigation: order insert-first is not possible (old active must be cleared to avoid two active), so we accept the small window; a follow-up can wrap both in a Postgres function (RPC) the app owns — **out of reach** for 003 unless smoke shows the window bites.
- **Audit path** — `log_action_executed(action_type, table, plant_id, action_id, user_sub, status, duration_ms, payload_digest)` → structlog JSON. For `add_journal_entry`, `payload_digest = sha256(content)[:16]`; the `content` text itself is never logged. Emitted on success (`status="executed"`) and on 502 (`status="upstream_error"`, no `action_id`).

Settings added to `app/config/settings.py`:

```python
action_signing_secret: str  # secret — Secret Manager in Cloud Run, .env in dev
action_token_ttl_seconds: int = 300  # 5 min — matches a conversation confirm, not a session
```

Gemini structured output for proposals: `call_gemini` gains an optional `action_schema` (a JSON Schema describing the union of the two action payloads) and returns `(reply, proposed_action_raw | None)`. The route validates `proposed_action_raw` against the registry's Pydantic model **before** minting the `confirm_token` — tokens are never minted for unparseable or un-allowlisted proposals (in that case `proposed_action` is silently set to `null` and Flora's plain reply still ships, so the user is never blocked by a malformed proposal).

The confirm token is built with `hmac.new(secret, f"{hash(payload+plant_id)}:{sub}:{exp}:{nonce}".encode(), sha256)` and serialised as base64url `f"{nonce}.{exp}.{b64}"`. Verification recomputes and compares in constant time (`hmac.compare_digest`); the nonce is tracked in an in-process set with the expiry timestamp so re-verification after consume fails (see Risks for the multi-instance caveat).

## Decisions

Recommended defaults, all confirmable before code touches:

- **Writable surface (V1.0).** Only two verbs: `create_watering_schedule` (new active schedule, deactivates the prior) and `add_journal_entry` (only `type="observation"` in 003 — watering/fertilizing/etc. log entries are user-driven, not AI-driven). **Rejected:** editing `plants.*`, deleting rows, writing `light_measurements`, writing `ai_messages`/`ai_conversations` (Non-Goal: conversation persistence). Confirm.
- **Two-step propose → confirm → execute, not "write inside `/chat`".** The agent never writes without an out-of-band user confirm in the app. The confirm is a *separate* `POST /actions/execute` call. **Rejected:** writing immediately when the user says "yes do it" inside the chat — that conflates consent with conversation and is unauditable as a discrete event. Confirm.
- **Provenance via a server-signed `confirm_token`.** HMAC-SHA256 with `ACTION_SIGNING_SECRET` over `payload_hash | sub | exp | nonce`. The app cannot forge, replay, swap-target, or cross-user an action. **Rejected:** relying on the app to faithfully echo Flora's proposal — a compromised/buggy client could fabricate any write. **Rejected:** storing proposed actions server-side to look up at execute — that re-introduces server state and conflicts with the stateless posture (and Cloud Run min-instances=0). Confirm.
- **Single-use, short-lived token (5 min).** A conversation confirm happens in seconds; 5 min is generous without inviting a stale proposal to be executed hours later. The nonce is consumed on successful execute. **Rejected:** long-lived action tokens (they drift from the conversation that produced them and weaken the consent link). Confirm.
- **In-process nonce store (not Redis/database).** Cloud Run instances are short-lived and each serves many requests; a nonce observed on instance A is checkable on instance A. A replay on instance B is bounded by the 5-min TTL and the fact that a real user only confirms once — a determined multi-instance replay is a low-likelihood, low-impact vector (one extra journal row / one extra schedule). **Rejected:** adding Redis/Supabase to dedupe nonces — it would import infrastructure V1.0 doesn't otherwise need. Flagged as a risk, not a blocker. Confirm this trade-off is acceptable.
- **Writes under the user's access token only (RLS), same as 002.** Never the service-role key. `user_id` is never supplied by the request; the DB/RLS sets it. **Rejected:** service-role writes "because the user confirmed" — it bypasses the ownership fence and re-introduces the exact risk 002 rejected for reads. Confirm.
- **`400 INVALID_ACTION` (new code) for allowlist and payload-hash violations; `401` for token provenance.** Two distinct failure classes: "you can't do that at all" (allowlist / the app altered the payload) vs "you can't prove you're the one Flora proposed this to" (token). **Rejected:** folding both into one code — it hides the security-relevant distinction in logs. **No 403:** consistent with 002's reasoning (RLS turns "not yours" into "doesn't exist", and an unprovable provenance is a 401). Confirm.
- **Reuse `UpstreamError` → `502` for Supabase write failures.** No new "SUPABASE_WRITE_ERROR" code (keeps the error-code table small, matches 002). Confirm.
- **Gemini structured output for proposals.** The action payload is produced by Gemini with `response_schema`, then re-validated by the registry's Pydantic model on the agent side (defense-in-depth: the model is the source of truth, not the LLM). **Rejected:** a regex/JSON parse of Flora's free text — fragile, non-localised, and breaks the bilingual-ish reasoning Flora does before the action. Confirm. (Note: this adds one structured-output capability to `call_gemini`; if the configured Gemini model does not support `response_schema`, fall back to a constrained follow-up call — see Risks.)
- **`/chat` stays side-effect-free.** Proposing costs nothing and writes nothing. A user who ignores the proposal leaves the database unchanged. Confirm.
- **Audit = structured agent logs, not a Supabase table.** The agent does not own schema (`mission.md`); a DB audit row would be schema ownership. Cloud Logging (Cloud Run stdout) is the durable trail. A future DB-backed audit is the app team's call. Confirm this is acceptable.
- **Deactivate-then-insert for watering schedules (no RPC).** Two PostgREST calls; the small atomicity window is accepted (Risks). A Postgres function owned by the app is the clean fix but is out of reach for 003 unless smoke shows the window bites. Confirm.
- **`save-a-tip` always `type="observation"`.** 003 does not let Flora fabricate a watering/fertilizing log line (that would be inventing history). A tip is an observation. Confirm.

## Risks

- **Gemini structured-output support on the configured model (highest).** If `gemini_model` in settings doesn't support `response_schema`, proposal extraction breaks. Mitigation: feature-detect by attempting `response_schema`; on failure, fall back to a *second*, narrowly-prompted Gemini call constrained to JSON-only. Validate either way through the registry's Pydantic model before minting a token; a malformed proposal → `proposed_action: null` and Flora's plain reply still ships. The user is never blocked.
- **Deactivate-then-insert atomicity window.** If the insert fails after the old schedule is deactivated, the user has no active schedule and sees a 502. Mitigation: keep the two calls adjacent and short; on the insert failing, attempt a best-effort re-activate of the old row and log the recovery; the audit event records `status="upstream_error"` so it's visible. If smoke shows this bites, escalate to an app-owned Postgres function (RPC) — a clean fix but out of reach by default. Low likelihood, user-visible impact.
- **Multi-instance nonce replay.** The in-process nonce set only protects within one Cloud Run instance. A replay on a different instance within the 5-min TTL would succeed. Mitigation: the TTL is short, the user only confirms once, and the impact is one extra row; flagged, not engineered away (no Redis in V1.0). If it ever matters, a single-row Postgres advisory lock table owned by the app is the escape hatch. Low likelihood, low impact.
- **`ACTION_SIGNING_SECRET` handling.** A leaked secret lets an attacker forge action tokens for any user `sub` they know — i.e. propose-and-execute without Flora. Mitigation: Secret Manager only, never in logs/images; mirror 002's `supabase-jwt-secret` pattern; rotate on suspicion. Low likelihood, high impact.
- **RLS `INSERT` policies missing on the Supabase side.** The agent's whole ownership posture assumes RLS `INSERT` policies (`auth.uid() = user_id` with `WITH CHECK`) exist on `watering_schedules` and `journal_entries`. Mitigation: `users-tasks.md` gates write smoke on RLS `INSERT` policies being present and verified; a CI test asserts the insert goes through the user token so even a handler bug can't bypass RLS. Still, a missing policy is a Supabase-side responsibility the agent can surface (insert rejected → 502) but not fix — flagged as a manual prerequisite.
- **App fabricates an action by withholding the confirm step.** Defence is the token's HMAC: the app has no `ACTION_SIGNING_SECRET`, so it cannot mint a token Flora didn't sign. The only actions that execute are ones Flora proposed. The allowlist is the second fence. The hash-binding is the third. Confirm the threat model is covered.
- **Flora proposes for a plant she can't see (foreign `plant_id`).** Mitigation: 002's RLS means a foreign `plant_id` yields empty deep context, so Flora has nothing to ground a proposal on; additionally the prompt instructs her never to propose for a plant not present in the provided context. A test asserts no proposal is attached when context is empty for the `plant_id`. The execute endpoint re-verifies RLS ownership on write, so even a fabricated-`plant_id` proposal would fail to insert. Defence-in-depth.
- **Privacy in audit logs.** Journal `content` is personal. Mitigation: log only `payload_digest` (truncated hash) for `add_journal_entry`; the full content never enters the audit path. Consistent with 002's "only counts/durations, never contents" convention.
- **Token expiry happening between the app showing the confirm card and the user tapping confirm.** A 5-min TTL is generous for a confirm but a distracted user could exceed it. Mitigation: `401` on execute with a clear message; the app can re-propose by re-calling `/chat` with the same message (costs one Gemini call). UX is owned by the app; flagged for coordination.
- **Proposal bloat / cost.** The structured-output call may add tokens to every `/chat` turn. Mitigation: the action schema is small; Gemini returns `proposed_action: null` for the common no-action case cheaply. Re-evaluate the cost delta in smoke.
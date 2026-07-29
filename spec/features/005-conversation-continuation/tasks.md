# 005 - Conversation Continuation

Phase buckets mapped from `roadmap.md` 005 (create-conversation endpoint, store messages, load history into context, list conversations, get messages, auto-title, plant scoping, token budget) plus the verify-the-posture-change axis (`/chat` stops being side-effect-free) and the "no migration" compiler assumption. The pure data-layer and history/title primitives have no Supabase-write ambiguity and land first; the three read/create routes land before the `/chat` rewire (so the store is exercised before `/chat` depends on it); the manual smoke is gated on a real Supabase user (`users-tasks.md`).

## Phase 0 — Pre-flight & constitution sync

- [ ] Confirm decisions in `plan.md`: `/chat` always persists (no opt-out), auto-create on `/chat` + dedicated `POST /conversations`, unknown/foreign id → 404 (never silent re-create), persist-user-before / persist-assistant-after, `ai_conversations.user_id` supplied as `user.sub` (documented exception to 003's "never set user_id"), `ai_messages` has no `user_id`, history loaded before persisting the current user message, history as a labelled text section in the existing context string, local-truncation auto-title (no LLM), title set once, `400 CONVERSATION_PLANT_MISMATCH`, `404 CONVERSATION_NOT_FOUND`, `502` reuse, truncate assistant > 4000, agent-side `updated_at` bump, audit scalar-only, `proposed_action`/`vision_request` not persisted, no new deps/migration
- [ ] Verify `users-tasks.md`: `ai_conversations` / `ai_messages` tables and their RLS policies already exist and match the plan's assumptions (INSERT `ai_conversations` `WITH CHECK (auth.uid() = user_id)`, INSERT `ai_messages` `WITH CHECK EXISTS (... ac.user_id = auth.uid())`, no `user_id` column on `ai_messages`, no `user_id` default on `ai_conversations`, no `updated_at` trigger on either table). **No migration in 005.**
- [ ] Add settings to `app/config/settings.py`: `history_max_messages` (default `20`), `history_max_chars` (default `6000`), `conversation_title_max_chars` (default `48`), `conversations_max_results` (default `50`)
- [ ] Update `.env.example`: `HISTORY_MAX_MESSAGES`, `HISTORY_MAX_CHARS`, `CONVERSATION_TITLE_MAX_CHARS`, `CONVERSATIONS_MAX_RESULTS` (all optional with defaults)
- [ ] Extend `spec/constitution/tech-stack.md`: add `app/conversations/` to the file map, list the new settings/env vars, reframe the V1.0 "No conversation persistence" hard limit as lifted by 005
- [ ] Decide `POST /conversations` status code (`201` recommended) and the `GET /conversations` / `GET .../messages` response envelope shape (object-with-`conversations`/`messages` arrays vs. bare arrays) — lock in `docs/api-contract.md` in Phase 6

## Phase 1 — Conversation data layer (`app/conversations/store.py`; no Gemini)

- [ ] Create `app/conversations/` package (`__init__.py`)
- [ ] `app/conversations/models.py`: `Conversation` (`conversation_id`, `user_id`, `plant_id`, `title`, `created_at`, `updated_at`), `Message` (`role: Literal["user","assistant"]`, `content`, `created_at`, `photo_url`), `CreateConversationRequest` (`plant_id: str | None`, `title: str | None = Field(max_length=200)`), `ConversationSummary` (the list-item shape), `ConversationListResponse`, `ConversationMessagesResponse`, and the `conversation_id` field for the `/chat` request/response
- [ ] `app/conversations/store.py` — all take the user-scoped `client` (RLS fence); all raise `UpstreamError` on Supabase failure; none accept `user_id` from a body (only `create_conversation` takes `user_sub` and sets `user_id = user_sub` internally):
  - `create_conversation(client, user_sub, plant_id=None, title=None) -> Conversation` — insert `ai_conversations` with `user_id = user_sub`; use `title` or omit (DB default `'Conversación con Flora'`)
  - `get_conversation(client, conversation_id) -> Conversation | None` — `select` by id; RLS denies foreign → None
  - `append_message(client, conversation_id, role, content, photo_url=None) -> Message` — insert `ai_messages` (no `user_id` column); truncate `content` to 4000 (with trailing `…`) defensively before insert
  - `fetch_history(client, conversation_id, limit) -> list[Message]` — `select role, content, created_at, photo_url from ai_messages where conversation_id=? order by created_at asc limit ?` (oldest→newest); RLS-scoped
  - `bump_updated_at(client, conversation_id)` — `update ai_conversations set updated_at=now()` under RLS
  - `set_title(client, conversation_id, title)` — RLS-scoped update
  - `set_plant_id_once(client, conversation_id, plant_id)` — RLS-scoped update (only used when the conversation's plant_id is null)
  - `list_conversations(client, limit) -> list[ConversationSummary]` — `select id, title, plant_id, updated_at, created_at from ai_conversations order by updated_at desc limit ?`; RLS-scoped
  - `fetch_messages(client, conversation_id) -> list[Message] | None` — `select conversation_id` first; None if the conversation isn't owned; else `select role, content, created_at, photo_url ... order by created_at asc` (oldest→newest)
- [ ] Tests (`tests/test_conversations_store.py`): `create_conversation` inserts `user_id = user_sub` (assert against the mock client's insert payload) and never a body-supplied `user_id`; `get_conversation` returns the row for an owned id and `None` for a foreign id (RLS empty); `append_message` inserts only `conversation_id`/`role`/`content`/`photo_url` (no `user_id` key) and truncates > 4000 with `…`; `fetch_history` orders oldest→newest and respects `limit`; `bump_updated_at` issues an RLS-scoped update; `list_conversations` orders by `updated_at desc` and is capped; `fetch_messages` returns `None` for a foreign id; every function raises `UpstreamError` on a Supabase exception (mocked → 502)

## Phase 2 — History block & auto-title (pure functions; no Supabase / Gemini)

- [ ] `app/conversations/history.py`:
  - `format_history_block(messages: list[Message]) -> str` — `Historial de la conversación\n` header, then `Usuario: ...\n` / `Flora: ...\n` per turn in chronological order; skip empty `content`; return `""` when `messages` is empty
  - `trim_to_budget(messages, max_messages, max_chars) -> list[Message]` — keep chronological order; first drop any beyond `max_messages` (oldest-first); then, while the combined `content` length exceeds `max_chars`, drop the oldest message and retry; the most recent turn always survives
- [ ] `app/conversations/titles.py`:
  - `derive_title(first_user_message: str, max_chars: int) -> str | None` — strip; if empty → `None` (caller keeps the DB default); else take the longest leading slice ≤ `max_chars` that ends at a whole-word boundary (split on whitespace); if the whole message fits, return it; else append `"…"`; never split a word; Spanish-safe (no character-class assumptions beyond whitespace)
- [ ] Tests (`tests/test_conversations_history.py`): block is empty for `[]`; labels are `Usuario:`/`Flora:`; order is chronological; empty `content` skipped; `trim_to_budget` drops oldest-first to satisfy the message cap; drops oldest-first to satisfy the char cap; the most recent message always survives both caps
- [ ] Tests (`tests/test_conversations_titles.py`): a short message returns whole; a message with no spaces longer than the cap returns the first `max_chars` + `…` (no word boundary — degenerate but bounded); a 120-char message at cap 48 returns ≤ 48 chars ending in `…` split at a space; empty/whitespace → `None`; a message exactly at the cap returns whole with no `…`

## Phase 3 — Read & create routes (`POST /conversations`, `GET /conversations`, `GET .../messages`; no Gemini)

- [ ] `app/api/errors.py`: `conversation_not_found_exception_handler` → `404 {"error":{"code":"CONVERSATION_NOT_FOUND","message":"..."}}` and `conversation_plant_mismatch_exception_handler` → `400 {"error":{"code":"CONVERSATION_PLANT_MISMATCH","message":"..."}}`; wire both in `app/main.py`
- [ ] `app/conversations/audit.py`: `log_conversation_event(*, event, conversation_id, user_sub, count, status, duration_ms)` → structlog JSON; **scalar-only signature** (no `content`/`title`)
- [ ] `app/conversations/routes.py` — all reuse 002's `get_authenticated_user` and `build_user_client`:
  - `POST /conversations` — validate `CreateConversationRequest` (optional `plant_id` uuid, optional `title` ≤ 200) → `create_conversation(client, user.sub, plant_id, title)` → `201 {"conversation_id": ...}`; emit `log_conversation_event(event="create", ...)`. No Gemini.
  - `GET /conversations` — `list_conversations(client, settings.conversations_max_results)` → `200 ConversationListResponse` (ordered `updated_at` desc, capped); emit audit `count` only. No Gemini.
  - `GET /conversations/{conversation_id}/messages` — `fetch_messages(client, conversation_id)` → `None` raises `ConversationNotFoundError` (404); else `200 ConversationMessagesResponse` (oldest→newest; includes `photo_url` field, null in V1.0); emit audit. No Gemini.
- [ ] Mount the conversations router in `app/main.py`
- [ ] Tests (`tests/test_conversations_routes.py`):
  - `POST /conversations` happy path: 201, response has `conversation_id`, insert used `user_id = user.sub`; optional `plant_id`/`title` honoured; missing/invalid `Authorization` → 401 (reuses 002 dep); title > 200 chars → 422; no Gemini call asserted
  - `GET /conversations`: 200 with the caller's conversations ordered by `updated_at` desc and capped; a foreign user's conversations never appear (assert the select is the RLS-scoped client's); empty garden → `200 {"conversations": []}`
  - `GET .../messages`: owned id → 200 oldest→newest; foreign/unknown id → `404 CONVERSATION_NOT_FOUND` with no message list; audit event emitted with scalar fields only (assert no `content`/`title` in the captured record)

## Phase 4 — `/chat` rewire (the posture change: persistence is now the default)

- [ ] `app/api/routes.py` — extend `ChatRequest` with `conversation_id: str | None = None` (validate as uuid when present, else 422); extend `ChatResponse` with a **required** `conversation_id: str`
- [ ] Rewire the `POST /chat` handler to the resolve → load → persist-user → context+history → Gemini → persist-assistant → bump → respond flow:
  1. `client = await build_user_client(...)` (unchanged)
  2. **Resolve:** if `body.conversation_id` is None → `conversation = await create_conversation(client, user.sub, plant_id=body.plant_id, title=None)`; else `conversation = await get_conversation(client, body.conversation_id)` → None raises `ConversationNotFoundError` (404). If `conversation.plant_id is not None and body.plant_id is not None and conversation.plant_id != body.plant_id` → raise `ConversationPlantMismatchError` (400). If `conversation.plant_id is None and body.plant_id is not None` → `set_plant_id_once(client, conversation.conversation_id, body.plant_id)` and update the local `conversation`
  3. **Load history (before persisting the current turn):** `history = await fetch_history(client, conversation.conversation_id, settings.history_max_messages)`; `history = trim_to_budget(history, settings.history_max_messages, settings.history_max_chars)`; `history_block = format_history_block(history)`
  4. **Persist user (before Gemini):** `await append_message(client, conversation.conversation_id, "user", body.message)`
  5. **Build context:** `bundle = await build_plant_context(client, conversation.plant_id, ...)` (key off the **conversation's** plant_id, not `body.plant_id`); `context_str = format_context_for_gemini(bundle, user_name=user.display_name)`; prepend `history_block` to `context_str` (history block before 002 context)
  6. **Gemini (unchanged):** `result = await call_gemini(...)`; reuse `build_proposed_action(result, ...)` (003) and `_build_vision_request(result, ...)` (004) verbatim
  7. **Persist assistant (on Gemini success; skip on 502):** `reply = str(result.get("reply", ""))`; `await append_message(client, conversation.conversation_id, "assistant", reply)`
  8. **Auto-title on first turn:** if the conversation's `title` is still the DB default (`'Conversación con Flora'`) and this was the first user message (history was empty at step 3 and `body.conversation_id` was None), `title = derive_title(body.message, settings.conversation_title_max_chars)`; if not None → `set_title(client, conversation.conversation_id, title)`. Do **not** overwrite an explicit title supplied via `POST /conversations`
  9. **Bump:** `bump_updated_at(client, conversation.conversation_id)`
  10. `return ChatResponse(conversation_id=conversation.conversation_id, reply=reply, proposed_action=proposed_action, vision_request=vision_request)`
- [ ] On a Gemini `UpstreamError` (502) raised at step 6: the user row from step 4 already exists and is **not** rolled back; no assistant row is written; the existing `upstream_error` exception handler returns the 502 envelope. The retry adds a second `user` row (correct, two real events).
- [ ] `app/agent/prompts.py`: add a one-line note that the labelled `Historial de la conversación` block represents recalled prior turns, not the current ask — Flora keeps the 001 persona; no behavioural change beyond remembering. (No persona rewrite.)
- [ ] Tests (`tests/test_chat_conversation.py`):
  - Auto-create: `/chat` without `conversation_id` returns `200` with a `conversation_id`; the insert used `user_id = user.sub`; the next `/chat` with that id loads the first turn as history (assert the mocked Gemini `contents` contains a `Historial de la conversación` block with `Usuario:`/`Flora:` lines in chronological order) and the current message appears exactly once
  - Foreign/unknown `conversation_id` → `404 CONVERSATION_NOT_FOUND`; no Gemini call; no message persisted (assert zero `append_message` calls after the 404)
  - Plant mismatch: a conversation with `plant_id=A` and a `/chat` with `plant_id=B` → `400 CONVERSATION_PLANT_MISMATCH`; no Gemini; no persist
  - Plant scoping by conversation: a conversation with `plant_id=A` resumed with a `/chat` that **omits** `plant_id` still loads 002 deep context for plant A (assert the context fetch used the conversation's plant_id); a null-plant conversation's first plant-bearing `/chat` sets the conversation's `plant_id` (assert `set_plant_id_once` called)
  - History cap: a conversation with > `history_max_messages` turns loads at most `history_max_messages - current`-many prior turns (oldest trimmed); the char budget then trims oldest-first
  - Current message never duplicated: assert the history block passed to Gemini does not contain the current `body.message` as a `Usuario:` line
  - Assistant > 4000 truncate: a mocked Gemini `reply` of 5000 chars → the stored `assistant` `content` is exactly 4000 chars ending in `…`
  - 502 leaves user saved: mock `call_gemini` to raise `UpstreamError` → response is the 502 envelope; assert the `user` `ai_messages` row exists and the `assistant` row does not
  - Retry doesn't double-persist the prior turn's assistant: after a 502, a retry-success adds a second `user` row (correct) followed by one `assistant` row; the first user row is untouched
  - Auto-title derivation: a first message ≤ cap keeps whole title; a >cap message yields a ≤-cap title split at a space ending in `…`; an explicit title from `POST /conversations` is not overwritten on the first turn
  - Title set once: a second `/chat` turn in the same conversation does not call `set_title`
- [ ] Audit assertions in `test_chat_conversation.py`: the `/chat` request log carries `conversation_id` and persistence booleans; no record contains `content` or `title`

## Phase 5 — Error wiring & router mount

- [ ] `app/main.py`: register `ConversationNotFoundError` → 404 handler and `ConversationPlantMismatchError` → 400 handler; include the `app.conversations.routes.router`
- [ ] Confirm the `conversation_id` field on `ChatRequest` is a `UUID` (422 on a non-uuid) to avoid a 404/422 ambiguity for a malformed id
- [ ] Smoke the OpenAPI: `/docs` shows `POST /conversations`, `GET /conversations`, `GET /conversations/{conversation_id}/messages`, and the `conversation_id` fields on `/chat`

## Phase 6 — Contract & docs

- [ ] `docs/api-contract.md`: document the optional `conversation_id` on the `/chat` request and the **required** `conversation_id` on the `/chat` response; document `POST /conversations` (request + `201`/`401`/`422`), `GET /conversations` (`200` list envelope + `401`), `GET /conversations/{conversation_id}/messages` (`200` + `401`/`404`); document the auto-title rule (local truncation of the first user message, set once, explicit titles not overwritten), the history-budget rule (`history_max_messages` + `history_max_chars`, oldest-first trim), and the plant-scoping rule (conversation's `plant_id` is the source of truth; `400` on conflict); add `404 CONVERSATION_NOT_FOUND` and `400 CONVERSATION_PLANT_MISMATCH` to the error-code table
- [ ] `README.md`: add the new env vars (`HISTORY_*`, `CONVERSATION_TITLE_MAX_CHARS`, `CONVERSATIONS_MAX_RESULTS`)
- [ ] `spec/constitution/tech-stack.md`: confirm the file map + settings reflect `app/conversations/` and the lifted "No conversation persistence" limit (edited in Phase 0)

## Phase 7 — Tests (full regression)

- [ ] New: conversation store unit tests (Phase 1) pass
- [ ] New: history block + auto-title pure-function tests (Phase 2) pass
- [ ] New: `POST /conversations` + `GET /conversations` + `GET .../messages` route tests (Phase 3) pass
- [ ] New: `/chat` rewire matrix (Phase 4) passes — auto-create, resumed-with-history, 404, 400 mismatch, plant-scoping-by-conversation, current-message-not-duplicated, 4000-truncate, 502-leaves-user-saved, retry-doesn't-double-persist, title-derivation-once, explicit-title-not-overwritten
- [ ] Regression: 001 `/health` + `/chat` reply + off-topic refusal + Spanish-only; 002 auth 401 + context injection + RLS deny + data-minimization + 502; 003 `/chat` propose + `/actions/execute` happy + token lifecycle + allowlist/hash + watering deactivate-then-insert + save-a-tip + RLS-write assertion; 004 `vision_request` on `/chat` + text-only-`/chat` assertion + vision reply shapes; all still green with persistence in flight (assert `/chat` still sends text-only `parts` to Gemini even when history is injected)
- [ ] `uv run ruff check` and `uv run ruff format --check` pass

## Phase 8 — Manual smoke (gated on a real Supabase user)

- [ ] **Gated on:** `users-tasks.md` confirming the existing `ai_conversations`/`ai_messages` RLS policies (already verified at spec time) and a real seeded user + plant; the four settings at defaults; `ACTION_SIGNING_SECRET` available (003 dependency still in place)
- [ ] Real two-turn `/chat`: message A → note the `conversation_id` → message B with that id → confirm message B's reply visibly references message A (Flora remembers)
- [ ] `GET /conversations` shows the thread with an auto-derived title from message A and an `updated_at` later than `created_at`
- [ ] `GET /conversations/{conversation_id}/messages` replays both turns oldest→newest with the right roles
- [ ] Real `POST /conversations` with a `plant_id` → a `/chat` with that id → confirm 002 deep context loads for that plant even when the second `/chat` omits `plant_id`
- [ ] Real 404: `/chat` with a random/foreign uuid `conversation_id` → `404 CONVERSATION_NOT_FOUND`; `GET /conversations/{foreign_id}/messages` → 404
- [ ] Real 400: `/chat` in a plant=P conversation with `plant_id=Q` → `400 CONVERSATION_PLANT_MISMATCH`
- [ ] Confirm the audit log lines in Cloud Logging carry `conversation_id` + counts and no `content`/`title`
- [ ] Update `spec/constitution/roadmap.md`: mark 005 done
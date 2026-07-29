# 005 - Conversation Continuation

## Approach

Add a **persistence layer** on top of the existing `/chat` without restructuring the request shape, the propose/confirm mutation contract (003), or the text-only gating of `/chat` (004). The dominant design axis is the *one* posture change 005 makes and 003 fought to preserve: **`/chat` stops being side-effect-free** — it now leaves two rows behind. The whole architecture is built to make that change safe, bounded, and unsurprising:

- **No schema work.** The `ai_conversations` / `ai_messages` tables and their RLS policies already exist and are verified (see `users-tasks.md`). 005 is a pure *behaviour* feature over 002's read path and 003's write-identity path. The agent writes through the **same user-scoped** `build_user_client(...)` used by 002/003 — PostgREST re-verifies the caller's JWT, RLS is the ownership fence, and the service-role key is never used for any user-facing operation (reaffirmed, not changed).
- **Two ownership fences, matched to the two tables.**
  1. **`ai_conversations`** — has a `user_id` column and an `INSERT` policy `WITH CHECK (auth.uid() = user_id)`. So the agent **must** supply `user_id = user.sub` on the insert (unlike 003 where `user_id` was *never* set by the agent and relied on the DB default). The value the agent passes must equal the caller or RLS rejects; this is defence-in-depth — the agent takes `user_id` only from the verified `UserIdentity.sub`, never from the request body.
  2. **`ai_messages`** — has **no** `user_id` column; its `INSERT` policy is `WITH CHECK EXISTS (ai_conversations ac WHERE ac.id = conversation_id AND ac.user_id = auth.uid())`. So owning a message is *inferred* through the conversation FK; the agent inserts only `conversation_id` / `role` / `content` / `photo_url` and lets RLS prove the conversation is the caller's. There is no `user_id` to set or drop on this table.
- **`/chat` becomes: resolve → load history → persist user → Gemini → persist assistant → bump.** The ordering is deliberate and is the single most load-bearing decision in 005:
  ```
  resolve conversation (or auto-create; 404 if id is foreign/unknown)
        └ auto-creation supplies user_id = user.sub; title defaults; inherits request plant_id
  load recent ai_messages (configurable N, oldest→newest, EXCLUDING any current-turn row)
  persist the USER ai_messages row        ← survives a later Gemini failure
  build 002 context (keyed off conversation.plant_id, not just request.plant_id)
        + inject history block as "Historial de la conversación" BEFORE 002 context
  call_gemini(...) (unchanged: reply + proposed_action + vision_request)
  persist the ASSISTANT ai_messages row   ← truncate content > 4000 first
  UPDATE ai_conversations SET updated_at = now()  ← no trigger exists
  return ChatResponse(conversation_id, reply, proposed_action, vision_request)
  ```
  Persist-user-**first** means a 502 on Gemini still leaves the user's words saved (so the user retries into a preserved history, not a void); persist-assistant-**after** means a failed turn never produces a phantom assistant message. The current user message is excluded from the loaded history (it is not yet persisted at load time, and even after persist it is the active turn), so it never appears twice in the prompt.
- **History injection is a new *section* of the existing context string, not a new call shape.** 002 already produces a `context_str` injected as `f"{context}\n\nMensaje del usuario: {message}"`. 005 prepends a `Historial de la conversación\nUsuario: ...\nFlora: ...` block to that same string. No change to `call_gemini`'s signature, no change to the 003 structured response, no change to 004's text-only-parts invariant (the history is text, so `/chat` remains provably text-only — asserted). The history block is labelled so Flora treats it as recalled memory, not as something the user just said in this turn.
- **`/chat` keeps its existing response surface and *gains* `conversation_id`**, plus three new routes whose only job is *reading* conversations and *creating* an empty one. The new routes deliberately do **no** Gemini calls (title is local; listing and message retrieval are pure RLS-scoped reads): the cost profile of 005 is "one history fetch per `/chat` + two cheap inserts + one `updated_at` update" — no LLM round-trips added, ever.

Sequenced so each phase produces something verifiable, with the no-Gemini, no-migration primitives (history loader, title derive, RLS-scoped conversation access) landing before the `/chat` rewire:

1. **Pre-flight & constitution sync** — confirm decisions; add the four settings; reconcile `tech-stack.md` and reframe the "No conversation persistence" limit; confirm `users-tasks.md` RLS findings (the policies are present and match this plan's assumptions — already verified at spec time, but the page is the durable record).
2. **Conversation data layer** (`app/conversations/store.py`) — typed, RLS-scoped functions over the user client, no Gemini: `create_conversation(client, user_sub, plant_id?, title?) -> Conversation`, `get_conversation(client, conversation_id) -> Conversation | None`, `append_message(client, conversation_id, role, content, photo_url?)`, `fetch_history(client, conversation_id, limit) -> list[Message]`, `bump_updated_at(client, conversation_id)`, `set_title(client, conversation_id, title)`, `set_plant_id_once(client, conversation_id, plant_id)`, `list_conversations(client, limit) -> list[Conversation]`, `fetch_messages(client, conversation_id) -> list[Message] | None`. All raise `UpstreamError` on Supabase failure. `user_id` is only ever passed from a `user_sub` argument on `create_conversation` — never accepted from callers that got it from a body.
3. **History builder & title derive** (`app/conversations/history.py`, `app/conversations/titles.py`) — pure functions: `format_history_block(messages) -> str` (Spanish labels `Usuario:` / `Flora:`, chronological, drops empty), `trim_to_budget(messages, max_messages, max_chars) -> list[Message]` (oldest-first drop), `derive_title(first_user_message, max_chars) -> str` (last-whole-word ≤ cap, trailing `…` when truncated; empty/whitespace → `None` to keep the DB default). Fully unit-tested without Supabase.
4. **`POST /conversations`, `GET /conversations`, `GET /conversations/{id}/messages`** (`app/conversations/routes.py`) — auth dep (reuse 002) → store functions → responses. No Gemini. `404 CONVERSATION_NOT_FOUND` and `400 CONVERSATION_PLANT_MISMATCH` (the latter only matters for `/chat`, but the error handler is wired here). Confirms the read model and the RLS scoping before `/chat` depends on the same store.
5. **`/chat` rewire** (`app/api/routes.py`) — extend `ChatRequest` with `conversation_id`; extend `ChatResponse` with required `conversation_id`; replace the current "build context then call" with the resolve → load-history → persist-user → (context+history) → Gemini → persist-assistant → bump → respond flow. Auto-create on missing `conversation_id`; `404` on foreign/unknown id; `400` on plant mismatch; on first user message of a default-titled conversation, derive the title and `set_title`. Reuse 003's `build_proposed_action` and 004's `_build_vision_request` verbatim — they consume the existing Gemini `result`, untouched.
6. **Error wiring** — `conversation_not_found_exception_handler` → `404`, `conversation_plant_mismatch_exception_handler` → `400`; wire in `app/main.py` and mount the conversations router.
7. **Audit & logging** — reuse the existing `app/logging` helper; per-request log gains `conversation_id` and `persisted_user`/`persisted_assistant` booleans (counts only — never content/title). New `log_conversation_event(...)` in `app/conversations/audit.py` for create/list/get (scalar-only).
8. **Contract & docs** — `docs/api-contract.md` (the new field, the three routes, the new error codes, the auto-title & history-budget rules), README env vars, `tech-stack.md` confirmation.
9. **Tests (full regression)** — store unit tests (RLS-scoped insert with `user_id=user.sub`, message append, history retrieval, 404 on foreign id), history/title pure-function tests, the three route tests, the `/chat` rewire matrix (auto-create, resumed-with-history, 404, 400 mismatch, plant-scoping-by-conversation, current-message-not-duplicated, 4000-truncate, 502-leaves-user-saved, retry-doesn't-double-persist, title-derivation-on-first-turn, title-set-once), audit no-content, and the full 001/002/003/004 regression. Mock Gemini + Supabase.
10. **Manual smoke (gated on a real Supabase user)** — a real two-turn `/chat` resumes context; `GET /conversations` shows the thread; `GET /conversations/{id}/messages` replays it; a foreign id 404s; then move 005 to Done in `roadmap.md`.

## Implementation

Files 005 touches (increment over 004's layout; new modules marked `+`):

```
app/
├── conversations/                      # +
│   ├── __init__.py
│   ├── models.py                       # Conversation, Message, CreateConversationRequest,
│   │                                  #   ConversationSummary, ConversationMessagesResponse, ChatRequestConversation
│   ├── store.py                        # create_conversation, get_conversation, append_message, fetch_history,
│   │                                  #   bump_updated_at, set_title, set_plant_id_once, list_conversations,
│   │                                  #   fetch_messages — all RLS-scoped via the passed user client
│   ├── history.py                      # format_history_block, trim_to_budget (pure)
│   ├── titles.py                       # derive_title (pure, Spanish-safe word-boundary truncate)
│   ├── audit.py                        # log_conversation_event(...) -> structlog JSON (scalar-only; no content/title)
│   └── routes.py                       # POST /conversations, GET /conversations, GET /conversations/{id}/messages
├── api/
│   └── routes.py                       # /chat: conversation_id on request + required conversation_id on response;
│                                   #   resolve→load→persist-user→context+history→Gemini→persist-assistant→bump
├── agent/
│   └── prompts.py                      # + note: history block is labelled "Historial de la conversación";
│                                   #   Flora treats prior turns as recalled memory, not as the current ask.
│                                   #   No persona change.
├── supabase/
│   └── schema.py                       # + COL_CONVERSATION_ID / COL_ROLE / COL_TITLE already present (verified)
├── config/
│   └── settings.py                     # + history_max_messages, history_max_chars,
│                                   #   conversation_title_max_chars, conversations_max_results
└── main.py                             # wire CONVERSATION_NOT_FOUND + CONVERSATION_PLANT_MISMATCH handlers;
                                    #   mount conversations router

docs/
└── api-contract.md                    # conversation_id on /chat; POST/GET /conversations*; new error codes;
                                    #   auto-title & history-budget rules

tests/
├── conftest.py                         # + conversation store mock fixture; history/title fixtures
├── test_conversations_store.py        # + RLS-scoped insert (user_id=user.sub), append, history retrieval,
│                                   #   foreign-id → None, list scoping, 502 on Supabase
├── test_conversations_history.py      # + format_history_block labels; trim_to_budget oldest-first; char budget
├── test_conversations_titles.py       # + derive_title word-boundary, ellipsis, empty → None
├── test_conversations_routes.py       # + POST /conversations (201, scoped, no Gemini); GET /conversations (list,
│                                   #   RLS-scoped, ordered by updated_at, capped); GET .../messages (owned + 404)
├── test_chat_conversation.py          # + auto-create + returns conversation_id; resumed-with-history (mocked
│                                   #   Gemini contents contain the history block, chronological, current msg once);
│                                   #   foreign/unknown conversation_id → 404; plant mismatch → 400; conversation
│                                   #   plant_id scoping deep context when request omits plant_id; current message
│                                   #   never duplicated; assistant > 4000 truncated before persist; 502 leaves user
│                                   #   saved + no assistant row; retry doesn't double-persist prior turn; title
│                                   #   derived once on first turn; explicit title not overwritten
└── test_chat.py / test_chat_context.py / test_actions_*.py / test_vision_*.py   # 001–004 regression green

spec/constitution/
├── tech-stack.md                    # + app/conversations/ in file map; new settings; "No conversation persistence" lifted
└── roadmap.md                        # mark 005 items Done at the very end

pyproject.toml                        # (no new runtime dep — all stdlib + existing supabase-py)
.env.example                          # + HISTORY_MAX_MESSAGES, HISTORY_MAX_CHARS, CONVERSATION_TITLE_MAX_CHARS,
                                    #   CONVERSATIONS_MAX_RESULTS (all optional with defaults)
```

Key flows (delta from 004):

- **`POST /chat` request** — gains an optional `conversation_id`:
  ```json
  {
    "message": "string (1–2000, required)",
    "plant_id": "string | null (optional)",
    "conversation_id": "string | null (optional)"
  }
  ```
  **Headers:** `Authorization: Bearer <supabase_access_token>` (required, unchanged).
- **`POST /chat` response** — gains a **required** `conversation_id` sibling (003/004 fields unchanged):
  ```json
  {
    "conversation_id": "uuid (always present after 005)",
    "reply": "string (Spanish, on-brand)",
    "proposed_action": { "...(003 shape, unchanged)" } | null,
    "vision_request": { "...(004 shape, unchanged)" } | null
  }
  ```
- **`POST /conversations` request/response (no Gemini):**
  ```json
  // request
  { "plant_id": "uuid | null", "title": "string | null (≤ 200)" }
  // response 201
  { "conversation_id": "uuid" }
  ```
- **`GET /conversations` response (`200`):**
  ```json
  { "conversations": [
    { "conversation_id": "uuid", "title": "string", "plant_id": "uuid | null",
      "updated_at": "iso8601", "created_at": "iso8601" }
  ] }
  ```
  Ordered by `updated_at` desc; capped at `conversations_max_results`.
- **`GET /conversations/{conversation_id}/messages` response (`200`):**
  ```json
  { "conversation_id": "uuid", "messages": [
    { "role": "user | assistant", "content": "string",
      "created_at": "iso8601", "photo_url": "string | null" }
  ] }
  ```
  Oldest→newest. `404 CONVERSATION_NOT_FOUND` when the conversation is absent under the caller's RLS.
- **Context string layout (after 005)** — sent to Gemini as `f"{context}\n\nMensaje del usuario: {message}"` where `context` is now:
  ```
  [Nombre del usuario: …]            ← 002 user name
  Historial de la conversación       ← 005 (only when the conversation has prior turns)
  Usuario: …
  Flora: …
  …
  [Contexto — …]                    ← 002 deep/light plant context
  ```
  The history block is injected by `format_context_for_gemini` (or a thin wrapper) taking the optional history; the current message stays as the trailing `Mensaje del usuario:` line, never inside the history block.
- **Auto-create flow** — when `conversation_id` is null: `create_conversation(client, user_sub, plant_id=body.plant_id, title=None)` → returns id → use as `conversation_id` for the rest of the flow → response carries it. The default `title` is the column's `'Conversación con Flora'`; on this first turn's user message, after persisting it, call `derive_title(message, ...)` and, if non-None, `set_title`. (Title derivation happens *after* the user row exists so "first user message" is unambiguous.)
- **Resume flow** — when `conversation_id` is present: `get_conversation(client, id)` → `None` ⇒ `404`. If `conversation.plant_id` is non-null and `body.plant_id` is non-null and they differ ⇒ `400 CONVERSATION_PLANT_MISMATCH`. If `conversation.plant_id` is null and `body.plant_id` is non-null ⇒ `set_plant_id_once`. 002 deep context keys off `conversation.plant_id` (resolved), not just `body.plant_id`, so a resumed plant thread re-loads its plant even if the app omits `plant_id`.
- **History load** — `fetch_history(client, conversation_id, limit=history_max_messages)` → `list[Message]` ordered oldest→newest **already excluding the current turn** (the current user message is either not yet persisted at load time, or — after persist-user-first — it is the *last* row, which `fetch_history` filters by fetching `limit+1` newest and dropping the newest when its content equals the current message, or more simply: load history **before** persisting the user message, so the current turn is provably absent — the chosen ordering, persisted-user-first happens *after* the load). Trim to `history_max_chars` (oldest-first drop). `format_history_block` → string.

Settings added to `app/config/settings.py`:

```python
history_max_messages: int = 20          # prior turns loaded into context per /chat
history_max_chars: int = 6000           # combined history-block char budget; oldest trimmed first
conversation_title_max_chars: int = 48  # auto-title length cap
conversations_max_results: int = 50      # GET /conversations list cap
```

(No new secrets. No new runtime deps — the supabase-py async client already in use provides the inserts/selects.)

## Decisions

Recommended defaults, all confirmable before code touches:

- **`/chat` now persists; there is no opt-out.** Every `/chat` turn writes the user + assistant rows and bumps `updated_at`. There is no "stateless mode" left — persistence is the point of 005. **Rejected:** keeping a stateless path "for callers that don't want history" — it double-states the contract and forces every consumer to choose; the cost of two cheap inserts is negligible. Confirm.
- **Auto-create on `/chat` when `conversation_id` is absent, plus a dedicated `POST /conversations`.** Two doors to the same table. The `/chat` auto-create is the forgiving path (the simple "just chat" flow still works); `POST /conversations` is for the app that wants to open a fresh named/plant-scoped thread up front. **Rejected:** forcing every conversation to be opened with `POST /conversations` first — it tangles lifecycle with messaging and breaks backward-compatible `/chat`. Confirm.
- **Unknown/foreign `conversation_id` → `404`, never silent re-create.** A foreign id under RLS resolves to "doesn't exist"; returning 404 + zero writes prevents duplicate threads and surfaces client bugs (a typo'd id should not spawn a new conversation). **Rejected:** "create-on-not-found" — it hides bugs and 003's posture of "a `/chat` reply should be auditable against one conversation" is best preserved by a hard 404. Confirm.
- **Persist user message *before* the Gemini call; assistant after, on success.** The user's words are durable even if Gemini 502s; a failed turn produces no phantom assistant message. **Rejected:** persist both after Gemini — a 502 erases the user message, and "can I retry?" becomes "retype it." **Rejected:** persist user after Gemini, assistant after Gemini — same 502 hole for the user row. Confirm the ordering.
- **`ai_conversations.user_id` is supplied by the agent as `user.sub`; `ai_messages` has no `user_id`.** This is forced by the existing RLS policies (verified): `ai_conversations` INSERT needs `user_id = auth.uid()`, `ai_messages` INSERT proves ownership through the conversation FK. The agent takes `user_id` only from the verified `UserIdentity.sub`, never from the body. **Rejected** (for `ai_conversations`) the 003 "never set user_id, let DB default it" rule — that rule held because 003's tables had DB defaults; `ai_conversations.user_id` has **no** default (verified), so the agent must supply it, and RLS still verifies it equals `auth.uid()`. This is a deliberate, documented exception to 003's rule, scoped to this one column. Confirm.
- **History loaded *before* persisting the current user message** (the two are sequenced: load → persist-user → Gemini). The current turn is provably absent from the history block, so it never appears twice in the prompt. **Rejected:** persist-user-then-load-then-filter-current — it adds a fragile content-equality filter and re-introduces the duplication risk. Confirm.
- **History block is a labelled text section in the existing context string; Flora treats it as recalled memory.** No change to `call_gemini`'s signature, no per-turn new call, 004's text-only-parts invariant preserved. **Rejected:** passing history as structured `contents` turns to Gemini — it couples memory to the client SDK's turn format and complicates the text-only proof. **Rejected:** a separate Gemini "memory summarisation" call per turn — it adds cost+latency exactly where 005's value is cheapest to deliver. Confirm the block-in-context approach.
- **Auto-title is local truncation of the first user message, not an LLM call.** Cost and latency discipline (matches 004's ethos); a chat thread title from the first line is already idiomatic. Spanish-safe truncation splits at the last whole word ≤ the cap with a trailing `…`. **Rejected:** a Gemini summarisation per conversation — adds a billable call and a latency hit at the moment of "first chat," the worst time to be slow. LLM titles → backlog. Confirm.
- **Title is set once (on first user message) and not regenerated.** A thread's title reflects how it started, like most chat apps. **Rejected:** re-deriving as the topic drifts — surprising churn in `GET /conversations`, and "title drift" is a known minor annoyance in the chat apps that do it. An explicit user rename is out of reach (no update surface). Confirm.
- **`CONVERSATION_PLANT_MISMATCH` (`400`) when a non-null conversation `plant_id` conflicts with a non-null request `plant_id`.** A thread belongs to at most one plant; silent re-scoping would rewrite a thread's identity. A conversation with a null `plant_id` is scoped by its first plant-bearing turn (via `set_plant_id_once`) and locked thereafter. **Rejected:** allowing per-turn plant_id on a null-plant conversation forever — it makes "which plant is this thread about?" indeterminate and breaks 002 deep-context resumption. Confirm.
- **`404 CONVERSATION_NOT_FOUND` (foreign/unknown id), `400 CONVERSATION_PLANT_MISMATCH`, `502 UPSTREAM_ERROR` (Supabase persist failure, reuse).** Three distinct classes: wrong/foreign id (404, "doesn't exist" per 002/004 convention), scope conflict (400), upstream down (502). No `403` (matches 002 reasoning). Confirm.
- **`assistant` content > 4000 truncated before insert (DB CHECK is 1–4000); `user` content already ≤ 2000 by `/chat` validation.** Defensive truncation with a trailing `…`. **Rejected:** storing the full reply and letting the DB reject → 502 mid-persist (breaks the "history is durable" promise for a long reply). Confirm.
- **No `updated_at` trigger exists; the agent explicitly `UPDATE`s it.** Verified: no trigger on either table. The agent bumps it after persisting the assistant row, so `GET /conversations` ordering reflects activity. **Rejected** (not chosen by 005) relying on a trigger to be added later —— 005 owns the bump because it's the feature that depends on `updated_at` being live. (If the app team later adds a trigger, the redundant update is harmless.) Confirm.
- **Audit = structured agent logs, scalar-only, never `content`/`title`.** Same posture as 003/004. The `log_conversation_event` signature takes no text fields. Conversation content durably lives in the user's own RLS-scoped rows; logs stay content-free. Confirm.
- **`proposed_action` / `vision_request` are not persisted as history text.** Only conversational content (the user message, Flora's reply text) is stored. Action tokens are short-lived (003); vision asks are side-effect-free (004); neither survives into the next turn's loaded history. `ai_messages.photo_url` stays `null` in V1.0. Confirm (keeps history clean and avoids re-arming expired tokens).
- **No new runtime deps; no migration.** All stdlib + existing `supabase-py`; the tables/RLS already exist. 005 is the first feature since 002 that ships without a migration. Confirm (the `users-tasks.md` page is the durable verification).

## Risks

- **`/chat` latency regression from added Supabase round-trips (highest).** Each `/chat` now adds: 1 conversation resolve/select, 1 history select, 1 user insert, 1 assistant insert, 1 `updated_at` update — up to 5 PostgREST calls before/around the single Gemini call. Mitigation: all are cheap, indexed, RLS-scoped queries against the user's own small thread; the resolve+history selects can be issued together or the resolve folded into the history fetch (select the conversation *and* its recent messages in one round-trip via a nested select on `ai_conversations` — `select id, title, plant_id, updated_at, ai_messages(*)` — Supabase supports the relationship). Flagged: measure the p95 in smoke; if the added round-trips bite, fold the resolve+history into one nested select and the user-insert can happen in parallel with the history fetch (they don't depend on each other). Low likelihood, medium impact.
- **Persist-user-first + persist-assistant-after creates a "ghost user message" on Gemini 502.** A failed turn leaves a `user` row with no following `assistant` row; a resumed `GET .../messages` shows the user's unanswered words. Mitigation: this is *desirable* (the user said it; it's their history) and the next successful turn's assistant reply naturally follows it in `created_at` order. Documented in the contract. If the team prefers to clean up orphan user rows on 502, that's an explicit non-decision — defer (it risks data loss for a retry). Low likelihood of user-visible confusion; the app can render the pending state.
- **Retry double-persists the user turn.** If `/chat` 502s and the app retries with the same message, the user row is inserted twice (once on the failed call, once on the retry-success), both with their own `created_at`, with the assistant reply following the *second*. Mitigation: this is correct and expected (the two attempts are two real events); the history block simply shows the user's message twice, which is honest. Documented. No dedup — there is no idempotency key in the contract and adding one widens the surface. Flagged for app-team awareness.
- **Race on concurrent `/chat` in the same conversation.** Two simultaneous turns load the same history, both append, both write — interleaved order in `created_at` but logically fine; Flora answers each with the pre-concurrency history. Mitigation: accepted; advisory-locking a conversation per request is out of reach (no DB functions owned by the agent). Low likelihood (a single user rarely fires concurrent chats in one thread). Flagged.
- **`ai_conversations.user_id` exception to 003's "never set user_id" rule.** A future change that reads `app/actions/handlers.py` and copies its "never set user_id" posture into a new write handler for `ai_conversations` would fail RLS (no DB default). Mitigation: the exception is documented in this plan and in a docstring on `create_conversation`; `users-tasks.md` records the verified column/state. The agent still never takes `user_id` from the body. Low likelihood, caught by RLS at runtime (insert → 502) and by the store tests.
- **History injection pushing `/chat` over the model's context window.** A very long thread's history (even after the message-count cap) plus 002's deep context could exceed the window. Mitigation: `history_max_chars` is an independent char budget applied after the message-count cap; defaults are conservative (20 turns, 6000 chars) and sit well below the configured model's window alongside 002's capped context. If a team runs a small-window model, the settings are the knob. Flagged; no per-call tokenisation (cost/complexity).
- **Title privacy leak in `GET /conversations`.** The title is a truncated snippet of the user's first message — content the user wrote, returned in a list. Mitigation: the list is RLS-scoped to the caller, so the leak is to themselves; logs never include titles; the `GET /conversations` response returning the user's own titles is the intended behaviour. Confirm.
- **`updated_at` drift if the app team later adds a trigger.** If a `BEFORE UPDATE` trigger sets `updated_at = now()` on `ai_messages` insert, the agent's explicit `ai_conversations.updated_at` bump is redundant but harmless (idempotent). Mitigation: none needed; documented in `users-tasks.md` so the app team knows the agent relies on `updated_at` reflecting the last message.
- **Wrong `conversation_id` type from a buggy client (non-uuid).** PostgREST coerces/filter fails → no row → 404. Mitigation: fast-path validate `conversation_id` as a uuid before the Supabase round-trip (pydantic `UUID` field or a regex) → `422` (FastAPI validation), saving a round-trip and a 404/422 ambiguity. Confirm the field type.
- **Off-topic refusal + persistence interaction.** A 001-guardrail off-topic refusal still persists the (refusing) assistant turn and the (off-topic) user turn — the user's off-topic question is saved to their own history. Mitigation: this is correct (it's the user's conversation), and 001's refusal still ships the Spanish `reply`. No change to the guardrail; the regression suite asserts off-topic refusal still fires with persistence on. Confirm.
- **Multi-instance Cloud Run + no cross-instance conversation state.** Not a real risk here (all state is in Postgres, none in instance memory), documented only to close the parallel with 003's in-process nonce caveat: 005 holds **no** instance-local state, so scaling out is free. Confirm.
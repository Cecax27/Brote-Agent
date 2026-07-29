# 008 - Vision Conversation Link

## Approach

Layer the 005 conversation persistence infrastructure onto the 004 vision endpoints. 008 is a *consumer* of 005 — it does not add new store functions, new RLS, new error handlers, or new settings. It adds an optional `conversation_id` parameter to the two vision request paths, wires the same resolve → load-history → persist-user → (vision call) → persist-assistant → bump flow 005 uses for `/chat`, and makes `format_history_block` label photo turns.

The dominant design axis is the **dual mode**: when `conversation_id` is absent, the vision endpoints behave exactly as they did before 008 (004). When present, they thread into a conversation. This is the inverse of `/chat`, where persistence is unconditional — a vision call is an opt-in participant, not a "just chat" flow. The dual mode keeps the 004 contract intact for callers that want stateless analysis, while opening the threading path for the app that wants a colour-coordinated photo + diagnosis + follow-up experience.

- **No schema work, no new store functions.** 005 already built `get_conversation`, `append_message`, `fetch_history`, `bump_updated_at`, `set_plant_id_once`, `trim_to_budget`, `format_history_block`, `ConversationNotFoundError`, `ConversationPlantMismatchError`, and the error handlers. 008 calls them.
- **`append_message` gains a `photo_url` parameter usage.** The 005 store's `append_message(client, conversation_id, role, content, photo_url=None)` already accepts `photo_url`. 008 is the first caller that passes a non-null value — for stored vision turns, the resolved photo's Storage URL.
- **`format_history_block` labels photo turns.** A small change to the 005 history formatter: when a message has a non-null `photo_url`, prefix the user turn's content with `[Foto] `. This is the only 005 function 008 modifies; the change is additive (photo turns are rare in the block, and the label is informational, not behavioural).
- **Vision endpoints gain resolve + persist logic.** The flow for a threaded vision call (the delta from 004 in bold):
  ```
  build_user_client(...)
  if conversation_id:
      conv = get_conversation(client, conversation_id)        ← None ⇒ 404
      plant scoping (400 on mismatch, set_plant_id_once on null-plant)
      history = fetch_history + trim_to_budget
      history_block = format_history_block(history)           ← now labels photo turns
      context_str = (history_block + "\n\n" + context_str) if history_block else context_str
  resolve photo (stored) / validate image (upload)            ← 004 unchanged
  if conversation_id:
      append_message(client, conv_id, "user", message, photo_url=resolved.url or None)
  result = analyze_image_with_gemini(...)                      ← 004 unchanged
  if conversation_id:
      append_message(client, conv_id, "assistant", reply)      ← truncate > 4000
      bump_updated_at(client, conv_id)
  return VisionAnalyzeResponse(..., conversation_id=conv_id if conversation_id else None)
  ```
  The two `if conversation_id:` blocks are the entire 008 delta on the route handlers. Everything else — image resolution, validation, resize, Gemini call, `proposed_action` building — is untouched.
- **No auto-create on `/vision/*`.** Unlike `/chat` (which uses `create_conversation` when `conversation_id` is null), vision endpoints *trust* the client to open the conversation first. A null `conversation_id` means "I want a stateless analysis." This avoids the surprise of empty threads and keeps the 004 tests' "stateless vision" assertions fully intact.
- **`VisionAnalyzeResponse` gains an optional `conversation_id: str | None = None`.** The field is `null` for stateless calls, carries the request's `conversation_id` for threaded calls. Unlike `/chat`'s required `conversation_id` in `ChatResponse`, a vision response lets the field be absent — the client distinguishes "stateless" from "threaded" by its own request, so the response field is informational (echoing back what was threaded).

Sequenced so each phase produces something verifiable:

1. **Pre-flight & constitution sync** — confirm decisions; update `docs/api-contract.md` with the new optional `conversation_id` on `/vision/*`; confirm `tech-stack.md` notes the vision endpoints now participate in persistence.
2. **`format_history_block` photo-turn labelling** (`app/conversations/history.py`) — the only 005 function 008 touches. Add `[Foto] ` prefix for user turns with non-null `photo_url`. Pure function; unit-test without Supabase or Gemini. This lands before the vision rewires so the formatter is exercised before the routes depend on it.
3. **`/vision/analyze-stored` rewire** (`app/vision/routes.py`) — add `conversation_id` to `VisionAnalyzeRequest` (optional UUID); add resolve + load-history + persist-user + persist-assistant + bump flow guarded by `if conversation_id:`; pass `photo_url` (the resolved Storage URL) on the user row; add `conversation_id` to `VisionAnalyzeResponse`.
4. **`/vision/analyze-upload` rewire** (`app/vision/routes.py`) — same flow, but `photo_url` is always `null` on the user row (inline image is transient). Add `conversation_id` as a multipart form field.
5. **Audit & logging** — `log_vision_call` gains `conversation_id: str | None`; the field is present in the log record when threaded, absent/`null` when stateless.
6. **Contract & docs** — `docs/api-contract.md` (the new optional field, the dual-mode rule, the photo-turn label, the 404/400 reuse); README if needed.
7. **Tests (full regression)** — vision-conversation tests (threaded persist + photo_url on stored, threaded persist + null photo_url on upload, stateless unchanged/004 regression, 404, 400, plant scoping, history injection with `[Foto]` label, 502 leaves user saved, truncation, audit scalar-only); full 001–007 regression.
8. **Manual smoke (gated on a real Supabase user)** — real photo → threaded vision → follow-up `/chat` in the same conversation → assert Flora references the diagnosis.

## Implementation

Files 008 touches (increment over 005's layout; modified modules marked `*`):

```
app/
├── conversations/
│   └── history.py                  # * — format_history_block labels photo turns ([Foto] prefix)
├── vision/
│   ├── models.py                    # * — VisionAnalyzeRequest gains conversation_id: UUID | None;
│   │                                #     VisionAnalyzeResponse gains conversation_id: str | None = None
│   ├── routes.py                    # * — both endpoints: resolve + load-history + persist + bump flow
│   │                                #     guarded by `if conversation_id:`
│   └── audit.py                     # * — log_vision_call gains conversation_id: str | None
docs/
└── api-contract.md                  # * — optional conversation_id on /vision/*; dual-mode rule;
                                     #     photo-turn label; 404/400 reuse from 005
tests/
├── test_conversations_history.py    # * — format_history_block labels photo turns
├── test_vision_conversation.py      # + — new: threaded vision persist, photo_url, 404, 400,
│                                   #     stateless unchanged, history injection, 502, truncation, audit
├── test_vision_stored.py            # * (or existing) — regression: stateless path unchanged
└── test_vision_upload.py            # * (or existing) — regression: stateless path unchanged
spec/constitution/
├── tech-stack.md                    # * — note /vision/* now participates in persistence when threaded
└── roadmap.md                       # * — add 008 entry, mark items as planned/done
```

Key flows (delta from 005 / 004):

- **`POST /vision/analyze-stored` request** — gains an optional `conversation_id`:
  ```json
  {
    "message": "string (1–2000, required)",
    "plant_id": "uuid | null (optional)",
    "image_ref": { "...004 shape, unchanged" },
    "conversation_id": "uuid | null (optional)"
  }
  ```
  **Headers:** `Authorization: Bearer <supabase_access_token>` (required, unchanged).
- **`POST /vision/analyze-stored` response** — gains an optional `conversation_id`:
  ```json
  {
    "conversation_id": "uuid | null (null when stateless, echoes request when threaded)",
    "reply": "string",
    "vision": { "...004 shape, unchanged" },
    "proposed_action": { "...003 shape, unchanged" } | null
  }
  ```
- **`POST /vision/analyze-upload` request** (`multipart/form-data`) — gains `conversation_id` as an optional text part:
  | Part | Type | Required | Constraint |
  |------|------|----------|-----------|
  | `image` | file | yes | JPEG/PNG/WebP, ≤ 8 MiB |
  | `message` | string | yes | 1–2000 chars |
  | `plant_id` | string | no | plants the diagnosis in context |
  | `conversation_id` | string | no | uuid; when present, threads the turn |
- **`POST /vision/analyze-upload` response** — same `conversation_id` addition as `analyze-stored`.
- **Threaded vision flow** — when `conversation_id` is present:
  1. `get_conversation(client, conversation_id)` → `None` ⇒ `404 CONVERSATION_NOT_FOUND`.
  2. Plant scoping: if `conversation.plant_id` is not null and the request's `plant_id` (or `image_ref.plant_id` for `plant_latest`) is not null and differs ⇒ `400 CONVERSATION_PLANT_MISMATCH`. If `conversation.plant_id` is null and the request's plant is not null ⇒ `set_plant_id_once`.
  3. Load history (via 005's `fetch_history` + `trim_to_budget`); `history_block = format_history_block(history)` (now labels `[Foto]` turns).
  4. Prepend `history_block` to the 002 context string (same as 005's `/chat`).
  5. Resolve/validate/resize the image — 004 unchanged.
  6. **Persist user** (before Gemini): `append_message(client, conv_id, "user", message, photo_url=resolved.url)`. For `analyze-stored`, `photo_url` is the resolved Storage URL; for `analyze-upload`, `photo_url=None` (transient image).
  7. `analyze_image_with_gemini(...)` — 004 unchanged.
  8. **Persist assistant** (on success): `append_message(client, conv_id, "assistant", reply)` (store truncates > 4000).
  9. **Bump**: `bump_updated_at(client, conv_id)`.
  10. Return `VisionAnalyzeResponse(..., conversation_id=conv_id)`.
- **Stateless vision flow** — when `conversation_id` is absent: every `if conversation_id:` block is skipped. The endpoint behaves exactly as 004. `VisionAnalyzeResponse.conversation_id` is `null`.

No new settings, no new env vars, no new runtime deps.

## Decisions

Recommended defaults, all confirmable before code touches:

- **Dual mode: threaded when `conversation_id` is present, stateless when absent.** The 004 contract is preserved for callers that want stateless analysis; threading is opt-in. **Rejected:** forcing all vision calls to thread (requires auto-creation, spams empty threads, breaks the 004 regression). **Rejected:** removing the stateless path (the 004 tests' "stateless vision" assertions become invalid). Confirm.
- **No auto-create on `/vision/*`.** Vision is an opt-in conversation participant. The app opens the conversation first (`POST /conversations` or `/chat`). **Rejected:** silently creating a thread for a stateless call — surprise + empty threads. Confirm. (This is the single largest divergence from 005's `/chat` auto-create; it exists because a vision call without a thread ID is a one-off, not a "just chatting" flow.)
- **`photo_url` populated on the user row for stored vision turns; `null` for inline uploads.** The stored URL lets a resumed thread show "[Foto]" in history; the inline image has no URL (it's transient). **Rejected:** persisting the inline upload to Storage to get a URL — entangles with Storage ownership and cleanup; out of reach. Confirm.
- **History block labels photo turns as `[Foto] {content}`, not [El usuario compartió una foto].** The label is terse and informative; Flora treats it as a recalled memory of the user sending an image this turn. The full diagnosis is in the assistant `reply` on the next line. **Rejected:** a verbose label — it clutters the history block and competes with the actual content. Confirm.
- **Structured `vision` analysis is not persisted.** Only the conversational `reply` is stored in `ai_messages`. The `vision` object is a per-turn extra returned to the client. **Rejected:** storing the `vision` JSON as a separate column or in `content` — `content` has a `CHECK (1–4000)` and the `vision` JSON is not conversational text; it would also bloat the history block. Confirm.
- **`proposed_action` from a vision turn is not persisted as history text.** Same as 005 — the token is short-lived. The `reply` text ("Te voy a proponer…") survives. Confirm.
- **No auto-title on vision turns.** 005 titles from the first user message. A vision-only first turn keeps the default title. **Rejected:** titling from the vision `message` ("¿Qué le pasa a mi Monstera?") — it's a poor title (it's a question, not a statement), and the diagnosis is what the user cares about. LLM titling belongs to the backlog. Confirm.
- **`ConversationNotFoundError` (404) and `ConversationPlantMismatchError` (400) are reused from 005.** No new error codes. The handlers are already wired in `app/main.py`. Confirm.
- **History loading on threaded vision turns reuses 005's `history_max_messages` / `history_max_chars`.** No new knobs. The vision context window is the same budget as `/chat`'s. Confirm. (If the vision model has a smaller context window, the settings are the knob — same as 005's documented risk.)
- **Persist user before Gemini, assistant after — same as 005.** The user's question ("¿qué le pasa a mi Monstera?") survives a 502; a failed turn produces no phantom assistant diagnosis. Confirm.
- **Assistant `reply` > 4000 truncated — same as 005.** The store's `_truncate_content` handles it. Confirm.
- **`log_vision_call` gains `conversation_id` as a scalar field.** Never logs content, image bytes, or vision analysis. Confirm.
- **No new runtime deps; no migration.** 008 is a pure behaviour change on the vision endpoints, layered on the 005 store. Confirm.

## Risks

- **`/vision/analyze-stored` latency regression from added Supabase round-trips (highest).** A threaded vision call adds: 1 conversation resolve, 1 history select, 1 user insert (with `photo_url`), 1 assistant insert, 1 `updated_at` update — up to 5 PostgREST calls around the existing image fetch + vision Gemini call. Mitigation: all are cheap, indexed, RLS-scoped; the resolve + history can be folded into one nested select (same flagged optimisation as 005). Flagged: measure p95 in smoke. Low likelihood, medium impact.
- **Inline-upload `photo_url` being `null` creates an incomplete history turn.** A resumed `/chat` showing "[Foto] ¿Qué le pasa?" with no URL means Flora knows a photo was sent but can't show it. Mitigation: the assistant `reply` (the diagnosis) is in the next history line; the user gets Flora's textual memory. The `[Foto]` label is the signal, not the image. Documented. Confirm.
  - **Alternative considered:** persisting the inline upload to Storage to get a URL. Rejected — it widens the Storage ownership surface (who owns auto-created photos? cleanup?) and breaks the 004 "inline uploads are never persisted" contract. Backlog.
- **History block `[Foto]` label + 005's `format_history_block` change.** Modifying a 005 function (one line) risks a 005 regression. Mitigation: the change is additive (prefix a label when `photo_url` is non-null); 005's `format_history_block` tests still pass (photo turns didn't exist in 005, so all 005 tests have `photo_url=None` and see no change). Flagged; covered by 005 regression in Phase 7.
- **`conversation_id` on a multipart form (`analyze-upload`) is fragile.** Form fields are strings; a non-uuid value should 422 (Pydantic `UUID` type), not 500. Mitigation: Pydantic parses `conversation_id: UUID | None` on the form model; a non-uuid is 422 before the handler. Confirm the form-field type.
- **Vision 502 on a threaded call leaves a "ghost user message" with no diagnosis.** Same as 005's `/chat` 502 — the user's question is saved, the diagnosis is not. The user retries into a preserved question. Mitigation: this is desirable (the user said it). Documented. Low likelihood of user-visible confusion. Confirm.
- **Race on concurrent threaded vision + chat in the same conversation.** Same as 005 — two simultaneous turns load the same history, both append. Interleaved `created_at` order but logically fine. Mitigation: accepted; advisory-locking is out of reach. Low likelihood. Flagged.
- **Photo-turn label in history desynchronised from the actual image.** The `photo_url` may be deleted from Storage between the vision turn and a resumed `/chat` (the row's `photo_url` field points to a deleted object). The `[Foto]` label is still in history, but the image is gone. Mitigation: Flora answers from her textual memory (the diagnosis), not from the image; the label is informational, not a trigger to re-fetch. The client can choose to render a broken-image placeholder. Documented. Low likelihood. Flagged.
- **`conversation_id` leaking into the 004 stateless tests.** The 004 vision tests don't mock the conversation store. 008 adds `conversation_id` as an *optional* field, so 004 tests that don't send it stay stateless and never touch the store. But the `mock_conversation_store` fixture pattern from 005 is needed for the new threaded tests. Mitigation: the 004 tests are untouched (they omit `conversation_id`); the new tests mock the store. Confirm the fixture isolation.
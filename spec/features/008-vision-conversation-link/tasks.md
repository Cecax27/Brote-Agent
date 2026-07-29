# 008 - Vision Conversation Link

## Phase 0 — Pre-flight & constitution sync

- [ ] Confirm decisions in `plan.md`: dual mode (threaded when `conversation_id` present, stateless when absent), no auto-create on `/vision/*`, `photo_url` populated for stored turns / `null` for inline, `[Foto]` label in history, structured `vision` not persisted, no auto-title, 404/400 reuse from 005, persist-user-before / persist-assistant-after, 4000 truncation, audit scalar-only, no new deps/migration
- [ ] Update `docs/api-contract.md`: add optional `conversation_id` to `/vision/analyze-stored` request and `/vision/analyze-upload` form fields; add optional `conversation_id` to `VisionAnalyzeResponse`; document the dual-mode rule (stateless when absent, threaded when present); document the `[Foto]` photo-turn label in history; note 404/400 error reuse from 005
- [ ] Update `spec/constitution/tech-stack.md`: note that `/vision/*` now participates in conversation persistence when `conversation_id` is supplied (reuses `app/conversations/` infrastructure — no new module)
- [ ] Add `008-vision-conversation-link` entry to `spec/constitution/roadmap.md`

## Phase 1 — `format_history_block` photo-turn labelling (pure function)

- [ ] `app/conversations/history.py` — extend `format_history_block`: when a message has a non-null `photo_url`, prefix the user turn's content with `[Foto] ` (e.g., `Usuario: [Foto] ¿Qué le pasa a mi planta?`). Assistant turns are unchanged. The prefix is informational — Flora treats it as a recalled memory of the user sending an image.
- [ ] Tests (`tests/test_conversations_history.py`): `format_history_block` with a user message that has `photo_url` set → the `Usuario:` line starts with `[Foto] `; assistant turn with `photo_url` → no prefix (assistant photo turns are rare but the rule is "user turns only"); a mix of photo and non-photo turns labels only the photo turns; 005 regression (all `photo_url=None`) unchanged

## Phase 2 — `/vision/analyze-stored` rewire (threaded mode)

- [ ] `app/vision/models.py` — `VisionAnalyzeRequest` gains `conversation_id: UUID | None = None`; `VisionAnalyzeResponse` gains `conversation_id: str | None = None`
- [ ] `app/vision/routes.py` (`analyze_stored`) — add the threaded flow guarded by `if body.conversation_id:`:
  1. `get_conversation(client, str(body.conversation_id))` → `None` ⇒ `ConversationNotFoundError` (404). No image fetch, no Gemini.
  2. Plant scoping: resolve the effective plant (`body.plant_id` or `ref.plant_id` for `plant_latest`). If `conversation.plant_id` is not null and effective plant is not null and differs ⇒ `ConversationPlantMismatchError` (400). If `conversation.plant_id` is null and effective plant is not null ⇒ `set_plant_id_once`.
  3. `effective_plant_id = conversation.plant_id` (conversation's, not just request's — same rule as 005).
  4. Load history: `fetch_history` + `trim_to_budget` + `format_history_block` (now labels `[Foto]` turns).
  5. Prepend `history_block` to 002 context string.
  6. Resolve/validate/resize image — 004 flow unchanged.
  7. **Persist user** (before Gemini): `append_message(client, conv_id, "user", body.message, photo_url=resolved.url)`. The `resolved.url` is the Storage URL of the stored photo.
  8. `analyze_image_with_gemini(...)` — 004 unchanged.
  9. **Persist assistant** (on success): `append_message(client, conv_id, "assistant", reply)` (store truncates > 4000).
  10. **Bump**: `bump_updated_at(client, conv_id)`.
  11. Return `VisionAnalyzeResponse(..., conversation_id=conv_id)`.
- [ ] When `body.conversation_id` is `None`: skip all the above `if` blocks; the endpoint is the 004 stateless path; `VisionAnalyzeResponse.conversation_id` is `None`.
- [ ] Audit: `log_vision_call` gains `conversation_id: str | None`; pass `conversation_id` when threaded, `None` when stateless.

## Phase 3 — `/vision/analyze-upload` rewire (threaded mode)

- [ ] `app/vision/routes.py` (`analyze_upload`) — add `conversation_id: UUID | None = Form(default=None)` as a multipart text part.
- [ ] Same threaded flow as `analyze_stored`, but:
  - `photo_url` on the user row is **always `None`** (inline image is transient — no Storage URL).
  - The effective plant for scoping is `plant_id` (the form field) or `conversation.plant_id`.
- [ ] When `conversation_id` is `None`: stateless 004 path; `VisionAnalyzeResponse.conversation_id` is `None`.
- [ ] Audit: pass `conversation_id` to `log_vision_call`.

## Phase 4 — Audit & logging

- [ ] `app/vision/audit.py` — `log_vision_call` signature gains `conversation_id: str | None = None`; the field is present in the structlog record (scalar, no content). Existing callers pass `None` when stateless; threaded callers pass the `conversation_id`.
- [ ] Update both route handlers to pass `conversation_id` to `log_vision_call`.
- [ ] Test: the log record for a threaded call includes `conversation_id`; a stateless call has `conversation_id=None`; no record contains `reply` / `content` / vision analysis / `photo_url` (only the scalar).

## Phase 5 — Contract & docs

- [ ] `docs/api-contract.md`: document the optional `conversation_id` on `/vision/analyze-stored` request (JSON body) and `/vision/analyze-upload` (multipart form); document the optional `conversation_id` on `VisionAnalyzeResponse`; document the dual-mode rule (stateless when absent, threaded when present, no auto-create); document the `[Foto]` photo-turn label in the history block; note 404 `CONVERSATION_NOT_FOUND` and 400 `CONVERSATION_PLANT_MISMATCH` on `/vision/*` when threaded (reuse from 005)
- [ ] `spec/constitution/tech-stack.md`: note the vision endpoints now participate in conversation persistence when threaded
- [ ] `spec/constitution/roadmap.md`: add the 008 entry with the tasks above (mark all as `[ ]`)

## Phase 6 — Tests (full regression)

- [ ] New (`tests/test_vision_conversation.py`):
  - `analyze-stored` threaded: persists user row with `photo_url=resolved.url` and assistant row (`reply`); `bump_updated_at` called; response `conversation_id` echoes request; both rows use user-scoped client (assert via mock)
  - `analyze-upload` threaded: persists user row with `photo_url=None` and assistant row; `bump_updated_at` called; response `conversation_id` echoes request
  - Stateless (`conversation_id` absent): no `append_message`, no `bump_updated_at`, no `get_conversation`; response `conversation_id` is `null`; full 004 behaviour unchanged (the 004 tests still pass without the conversation store mock)
  - Foreign/unknown `conversation_id` → `404 CONVERSATION_NOT_FOUND`; no image fetch; no Gemini; no persist (assert zero `append_message` calls)
  - Non-uuid `conversation_id` → `422`
  - Plant mismatch: conversation with `plant_id=A`, vision request with `plant_id=B` → `400 CONVERSATION_PLANT_MISMATCH`; no Gemini; no persist
  - Plant scoping by conversation: conversation with `plant_id=A`, vision request omitting `plant_id` → deep context loads for plant A (assert `build_plant_context` called with `"A"`)
  - Null-plant conversation scoped by first plant-bearing vision call: `set_plant_id_once` called
  - History injection: a conversation with prior turns → the mocked Gemini `contents` include a `Historial de la conversación` block before the 002 context; a prior photo turn is labelled `[Foto]`
  - 502 leaves user saved: mock `analyze_image_with_gemini` to raise `UpstreamError` → 502; user row exists, assistant row does not (assert one `append_message` call, role="user")
  - Assistant > 4000: the full reply is passed to `append_message`; the store truncates (assert in store tests, here assert the call received the full content)
  - Audit: threaded call log record has `conversation_id`; stateless call has `conversation_id=None`; no record has `content`/`reply`/vision analysis/`photo_url` text
- [ ] Modified (`tests/test_conversations_history.py`): `format_history_block` photo-turn label assertions (user turns with `photo_url` get `[Foto] ` prefix; `photo_url=None` turns unchanged; 005 regression green)
- [ ] Regression: `tests/test_vision_stored.py` (or existing equivalent) — 004 stateless path unchanged (no `conversation_id` sent); `tests/test_vision_upload.py` — same; full 001–007 suite green
- [ ] `uv run ruff check` and `uv run ruff format --check` pass

## Phase 7 — Manual smoke (gated on a real Supabase user)

- [ ] **Gated on:** a real seeded user + plant + at least one journal entry with a `photo_url`; the 005 conversation infrastructure live (settings at defaults; `ACTION_SIGNING_SECRET` available)
- [ ] `POST /conversations` with a `plant_id` → get `conversation_id` → `POST /vision/analyze-stored` with that `conversation_id` and an immune `image_ref` referencing the journal entry's photo → confirm the response carries the `conversation_id` and the diagnosis
- [ ] `GET /conversations/{conversation_id}/messages` → confirm the user row has `photo_url` set to the photo's Storage URL and the assistant row has `photo_url=null`
- [ ] `POST /chat` with the same `conversation_id` and message "¿y la foto que te envié, qué opino sobre el sol?" → confirm Flora's reply visibly references the diagnosis (she remembers from the persisted `reply`)
- [ ] Stateless: `POST /vision/analyze-stored` without `conversation_id` → confirm `conversation_id` is `null` in the response; `GET /conversations` shows no new thread
- [ ] 404: `POST /vision/analyze-stored` with a foreign `conversation_id` → `404 CONVERSATION_NOT_FOUND`
- [ ] 400: `POST /vision/analyze-stored` in a plant=P conversation with `plant_id=Q` → `400 CONVERSATION_PLANT_MISMATCH`
- [ ] Confirm the audit log lines carry `conversation_id` (when threaded) and no content/photo/vision text
- [ ] Update `spec/constitution/roadmap.md`: mark 008 done
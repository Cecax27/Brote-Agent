# 004 - Image Analysis

Phase buckets mapped from `roadmap.md` 004 (image upload contract, vision model integration, plant health diagnosis, plant identification, calibration guidance, photo size/cost limits) plus the user's two explicit intake paths and the cost-gating rule. The image-processing primitives and vision core have no Supabase-write dependency and land first; the routes and the `/chat` `vision_request` extension land after; the manual smoke is gated on a real Supabase user with a journal photo and a bucket-visibility decision (`users-tasks.md`).

## Phase 0 — Pre-flight & constitution sync

- [ ] Confirm decisions in `plan.md`: two intake paths (separate endpoints, not fused), vision in `app/vision/` not `call_gemini`, `/chat` provably text-only, AI-initiated ask via `vision_request` + user-authorised grant, public-bucket retrieval in V1.0, one image per request, resize-before-send with Pillow, `httpx` declared runtime, MIME allowlist `{jpeg,png,webp}` with Pillow as source of truth, `400 INVALID_IMAGE` / `404 IMAGE_NOT_FOUND` / `502` reuse, separate `gemini_vision_model`, vision temperature 0.4, calibration via `needs_more_info`, `kind="declined"` value, no persistence on inline path (asserted), audit as agent logs, `proposed_action` reused verbatim
- [ ] Add runtime deps to `pyproject.toml`: `pillow>=10.4`, `httpx>=0.27`; run `uv lock` + `uv sync`; confirm no break to existing CI
- [ ] Add settings to `app/config/settings.py`: `gemini_vision_model` (default placeholder), `gemini_vision_temperature=0.4`, `vision_max_image_bytes`, `vision_max_download_bytes`, `vision_max_dimension`, `vision_jpeg_quality`, `vision_allowed_mime`
- [ ] Update `.env.example`: `GEMINI_VISION_MODEL`, `VISION_MAX_IMAGE_BYTES`, `VISION_MAX_DIMENSION`, `VISION_JPEG_QUALITY` (all optional with defaults)
- [ ] Extend `spec/constitution/tech-stack.md`: add `app/vision/` to the file map, list the new settings/env vars and new deps, reframe the V1.0 "No image analysis" hard limit as lifted by 004
- [ ] Confirm the `users-tasks.md` items before Phase 5/6 land: public-vs-private `plant-photos` bucket decision, the chosen `gemini_vision_model`, MIME/caps tuning, an off-topic `kind="declined"` value if adopted

## Phase 1 — Image processing primitives (no Supabase / Gemini dependency)

- [ ] Create `app/vision/` package (`__init__.py`)
- [ ] `app/vision/images.py`:
  - `sniff_allowed_mime(raw: bytes) -> str | None` — open with Pillow (decodes + infers format); return the MIME iff it's in `vision_allowed_mime`, else `None`
  - `validate_image_bytes(raw: bytes, settings) -> None` — raise `InvalidImageError` if `len(raw) > vision_max_image_bytes`, or if Pillow can't `verify()` / decode, or if MIME is not allowed
  - `resize_image(raw: bytes, settings) -> bytes` — flatten to RGB (drop alpha/palette), downscale so the longest side is ≤ `vision_max_dimension` (never upscale), re-encode JPEG at `vision_jpeg_quality`, return the new bytes; original bytes are caller-released
- [ ] `app/vision/models.py`: `ImageRef` (`kind: Literal["journal_entry","plant_latest"]`, `journal_entry_id: str | None`, `plant_id: str | None`), `VisionRequest` (`reason_es`, `suggested_ref: ImageRef`), `VisionSpeciesCandidate` (`name`, `confidence`), `VisionAnalysis` (`kind: Literal["health","identify","mixed","declined"]`, `diagnosis: str | None`, `possible_species: list[VisionSpeciesCandidate]`, `confidence`, `needs_more_info: {question_es: str | None}`), `VisionAnalyzeResponse` (`reply`, `vision`, `proposed_action: ProposedActionResponse | None`)
- [ ] Tests (`tests/test_vision_images.py`): allowed-MIME accept (jpeg/png/webp); disallowed MIME → `InvalidImageError`; undecodable → `InvalidImageError`; oversized → `InvalidImageError`; resize caps longest side ≤ `vision_max_dimension`; never upscales a tiny image; JPEG quality produces smaller bytes; RGBA → RGB flatten (no alpha channel in output); palette → RGB

## Phase 2 — Stored-photo retrieval (RLS-scoped DB lookup + public-bucket GET)

- [ ] `app/vision/retrieval.py`:
  - `resolve_journal_photo(client, journal_entry_id) -> ResolvedPhoto | None` — `select photo_url from journal_entries where id=?` via the RLS user client; `None` if no row or `photo_url` is null
  - `resolve_plant_latest_photo(client, plant_id) -> ResolvedPhoto | None` — `select photo_url from plants where id=?` first; if null, `select photo_url from journal_entries where plant_id=? and photo_url is not null order by created_at desc limit 1`; `None` if nothing
  - `fetch_photo_bytes(url: str, settings) -> bytes` — `httpx.AsyncClient` GET against the public bucket, stream with a `vision_max_download_bytes` ceiling; `UpstreamError` on oversize / network error / non-200; never log the URL
- [ ] `ResolvedPhoto` dataclass (`url`, `mime_hint`)
- [ ] Tests (`tests/test_vision_retrieval.py`): happy → bytes returned; cross-user `journal_entry_id` (RLS empty) → `None`; own row with null `photo_url` → `None`; `plant_latest` with missing plant → `None`; `plant_latest` falls back to latest journal photo when `plants.photo_url` is null; Supabase read failure → `UpstreamError` (502); download oversize → `UpstreamError`; download non-200 → `UpstreamError`; URL never appears in emitted logs

## Phase 3 — Vision core (Gemini multimodal + structured output)

- [ ] `app/vision/core.py`: `analyze_image_with_gemini(image_bytes, mime_type, message, context_str, settings) -> VisionAnalysis` — build `types.Part.from_bytes(data=image_bytes, mime_type=mime_type)` (use `"image/jpeg"` after resize) + text part (vision sub-prompt + context + user message), call `gemini_vision_model` with `gemini_vision_temperature`, `response_mime_type="application/json"`, `response_schema` describing `{reply, proposed_action?, vision}`; on Gemini exception → `UpstreamError`; validate the parsed dict against `VisionAnalysis` Pydantic (defense-in-depth: the model is the source of truth, not Gemini)
- [ ] `app/agent/prompts.py`: add the vision sub-prompt — Flora sees the image but keeps the 001 persona (Spanish, calm, honest, reasoning, concrete next step); produces `vision` with `kind` chosen from `health`/`identify`/`mixed`/`declined`; expresses `confidence` honestly (`alta`/`media`/`baja`); when context is insufficient sets `confidence="baja"` and a Spanish `needs_more_info.question_es` rather than guessing; off-topic non-plant images → `kind="declined"` with a friendly Spanish decline and no diagnosis; `possible_species` only ranked candidates with explicit confidence; never invent species/diseases
- [ ] Tests (`tests/test_vision_reply_shapes.py`): diagnosis shape (`kind="health"`, `diagnosis`, `confidence`); identification shape (`kind="identify"`, ranked `possible_species`, `confidence`); mixed health+identify; `needs_more_info` when context-starved; off-topic non-plant fixture → `kind="declined"` + declining Spanish `reply`; Gemini failure → `UpstreamError` (502); structured-output feature-fail fallback documented (per `plan.md`)

## Phase 4 — `/chat` `vision_request` (the AI-initiated ask-for-authorization)

- [ ] `app/agent/prompts.py`: add a section telling Flora she may **ask** the user (in Spanish) to share a photo when one would genuinely help — the ask is free (text-only, no image send), it is optional, she never claims to have seen a photo she hasn't, and `suggested_ref.kind` is `journal_entry` (with an id from her context) or `plant_latest` (with a `plant_id` from her context). Frame `reason_es` as a friendly question ("¿Me dejas ver la foto de tu Monstera? …").
- [ ] Extend `ACTION_RESPONSE_SCHEMA` in `app/api/routes.py` with a nullable `vision_request` (`{ reason_es, suggested_ref: {kind, journal_entry_id?, plant_id?} }`); `required` stays `["reply"]`
- [ ] `app/api/routes.py`: `_build_vision_request(result, plant_id, deep_plant_ids) -> VisionRequest | None` — validate `suggested_ref.kind` is allowlisted; if `kind="journal_entry"`, require `journal_entry_id` ∈ the deep context's journal ids (RLS-resolved); if `kind="plant_latest"`, require `plant_id` == request `plant_id` (or the single deep plant's id); drop to `None` on any mismatch (asking is a courtesy, never an error). Mint **no** `confirm_token` — `vision_request` is not an action.
- [ ] `ChatResponse` gains `vision_request: VisionRequest | None = None`
- [ ] Tests (`tests/test_vision_chat_request.py`): `/chat` returns a `vision_request` when a photo would help; `vision_request` is `null` when not; `suggested_ref.kind` outside the allowlist → dropped to `null`; foreign `plant_id` in `suggested_ref` → dropped; proposed `journal_entry_id` not in the user's context → dropped; **mocked Gemini `contents`/`parts` are text-only on every `/chat` turn** (assert: no image `Part` is ever sent on `/chat`); 001/002/003 regression assertions (Spanish-only, off-topic refusal, propose/confirm shapes) still green with `vision_request` in the schema

## Phase 5 — `POST /vision/analyze-stored` endpoint

- [ ] `app/api/errors.py`: `invalid_image_exception_handler` → `400 {"error":{"code":"INVALID_IMAGE","message":"..."}}` and `image_not_found_exception_handler` → `404 {"error":{"code":"IMAGE_NOT_FOUND","message":"..."}}`; wire both in `app/main.py`
- [ ] `app/vision/routes.py`: `POST /vision/analyze-stored` — auth dep (reuse 002) → `build_user_client` → resolve `image_ref` via Phase 2 → on `None` raise `ImageNotFoundError` (404) → `fetch_photo_bytes` → `validate_image_bytes` → `resize_image` → optional `build_plant_context` when `plant_id` is given → `analyze_image_with_gemini` → build `proposed_action` if present (reuse 003's `_build_proposed_action` lifted to a shared helper) → log audit event → `200 VisionAnalyzeResponse`
- [ ] Unknown `image_ref.kind` → `InvalidActionError`/`InvalidImageError` (400, decide which per `plan.md`); Gemini/Storage failure → `UpstreamError` (502) + audit `status="upstream_error"`
- [ ] Tests (`tests/test_vision_stored_endpoint.py`): happy path for `kind="journal_entry"` and `kind="plant_latest"`; cross-user `journal_entry_id` → 404; null `photo_url` → 404; missing plant → 404; unknown `kind` → 400; no `Authorization` → 401; rests a `proposed_action` minting an `add_journal_entry` `confirm_token` from a diagnosis (reuses 003 token); audit fields + no URL/bytes logged; 502 on Gemini failure; 502 on download failure

## Phase 6 — `POST /vision/analyze-upload` endpoint (no persistence)

- [ ] `app/vision/routes.py`: `POST /vision/analyze-upload` — auth dep → read `UploadFile` into `bytes` with `vision_max_image_bytes + 1` ceiling (overflow → `InvalidImageError` 400) → `validate_image_bytes` → `resize_image` → optional `build_plant_context` when `plant_id` is given (only if provided; no write client) → `analyze_image_with_gemini` → build `proposed_action` → log audit → `200 VisionAnalyzeResponse`
- [ ] Enforce exactly one `image` part and a `message` 1–2000 (`422` otherwise); enforce MIME allowlist (Phase 1 validator); release original bytes after resize
- [ ] **Persistence assertion:** the handler path must **never** call a Supabase `.insert`/`.upload`/Storage write, and must never write to disk. Tests assert this against mocked clients + a `tmp_path` watcher.
- [ ] Tests (`tests/test_vision_stored_endpoint.py` or a dedicated `tests/test_vision_upload_endpoint.py`): multipart happy path (jpeg, png, webp); oversized → 400; bad MIME (declared `image/jpeg` but undecodable, or a real disallowed type) → 400; zero or >1 image part → 422; missing `message` → 422; **zero Supabase inserts/uploads asserted**; no filesystem write asserted; resized bytes reach the mocked Gemini `parts` and `max(width,height) <= vision_max_dimension` holds on the decoded bytes; `proposed_action` reuse; audit fields + no-bytes-logged; 502 on Gemini failure

## Phase 7 — Audit & logging

- [ ] `app/vision/audit.py`: `log_vision_call(*, endpoint, source, plant_id, user_sub, mime_type, original_bytes, resized_bytes, max_dimension, gemini_model, vision_kind, confidence, status, duration_ms, proposed_action_type)` → structlog JSON. **Signature takes only scalars** — no image/URL field can exist. For `inline` source, `plant_id` may be `None`.
- [ ] Both routes call `log_vision_call` on success (`status="ok"`) and on 502 (`status="upstream_error"`, `vision_kind`/`confidence` may be `None`)
- [ ] Tests: audit event emitted with the right fields on a successful stored call; on a successful inline call; on a 502; **no audit record contains image bytes, the resolved Storage URL, or any journal text** (assert against captured log records on the `needs_more_info`/`declined`/happy paths)

## Phase 8 — Contract & docs

- [ ] `docs/api-contract.md`: document the optional `vision_request` on `/chat` (shape + the gating rule: "images are analysed only on an explicit `/vision/*` call; `/chat` never sends image bytes"); document `POST /vision/analyze-stored` (JSON request + `200`/`401`/`400`/`404`/`502`); document `POST /vision/analyze-upload` (multipart shape + `200`/`401`/`400`/`422`/`502`); document `VisionAnalyzeResponse` (the `vision` sub-object with `kind`, `diagnosis`, `possible_species`, `confidence`, `needs_more_info`); document the image constraints (allowed MIME, `vision_max_image_bytes`, max one image per request); add `400 INVALID_IMAGE` and `404 IMAGE_NOT_FOUND` to the error-code table
- [ ] `README.md`: add the new env vars (`GEMINI_VISION_MODEL`, `VISION_*`)
- [ ] `spec/constitution/tech-stack.md`: confirm the file map + settings reflect `app/vision/`, the new deps, and the lifted "No image analysis" limit (edited in Phase 0)

## Phase 9 — Tests (full regression)

- [ ] New: image validator + resize unit tests (Phase 1) pass
- [ ] New: retrieval unit tests (Phase 2) pass
- [ ] New: vision reply shape tests (Phase 3) pass
- [ ] New: `/chat` `vision_request` behaviour + text-only assertion (Phase 4) pass
- [ ] New: `/vision/analyze-stored` happy/error/audit (Phase 5) pass
- [ ] New: `/vision/analyze-upload` happy/error/no-persistence/audit (Phase 6) pass
- [ ] New: audit fields + no-bytes-logged (Phase 7) pass
- [ ] Regression: 001 `/health` + `/chat` reply + off-topic refusal + Spanish-only; 002 auth 401 paths + context injection + RLS deny + data-minimization + 502; 003 `/chat` propose + `/actions/execute` happy + token lifecycle + allowlist/hash + watering deactivate-then-insert + save-a-tip + RLS-write assertion; all still green with vision in flight
- [ ] `uv run ruff check` and `uv run ruff format --check` pass

## Phase 10 — Manual smoke (gated on `users-tasks.md`)

- [ ] **Gated on:** a real Supabase user with at least one `journal_entries.photo_url` and one `plants.photo_url`; the public-vs-private `plant-photos` bucket decision confirmed; the chosen `gemini_vision_model` confirmed and billable; Pillow + httpx pinned versions installed
- [ ] Real `POST /vision/analyze-stored` with a `journal_entry` ref the user owns → verify a Spanish diagnosis/identification in the response; verify **no** new Storage object was created and **no** new `journal_entries` row was created by the agent
- [ ] Real `POST /vision/analyze-stored` with a foreign user's `journal_entry.id` → verify `404 IMAGE_NOT_FOUND` (RLS deny path)
- [ ] Real `POST /vision/analyze-upload` with a fresh photo + `plant_id` → verify a Spanish reply; verify **no** new Storage object, no new journal row, no new plant row, and no local disk file was created
- [ ] Real `POST /vision/analyze-upload` with an oversized or non-plant image → verify `400 INVALID_IMAGE` / a friendly Spanish decline respectively
- [ ] Verify the audit log line in Cloud Logging has the expected fields and no image bytes, no URL, no journal `content`
- [ ] Update `spec/constitution/roadmap.md`: mark 004 items Done
# 004 - Image Analysis — User Tasks

Things only you can do (Supabase project, storage bucket config, model selection, caps tuning, test images). The code-level work lives in `tasks.md`; these items gate Phases 0 (decisions), 2 (retrieval), 5–6 (endpoints), and 10 (manual smoke). The agent deliberately owns no database or storage bucket, so everything below lives on the Supabase/app side. Mirrors the `002/.../users-tasks.md` pattern.

## Decisions to confirm (Phase 0)

- [ ] **Two intake paths, separate endpoints.** Retrieve-from-Supabase (`POST /vision/analyze-stored`, JSON, ref-to-photo) and receive-without-storing (`POST /vision/analyze-upload`, multipart, bytes-in-bytes-out). Confirm this split is right vs. a fused "either a ref or a file" endpoint (recommended: split — cleaner trust postures + audit fields).
- [ ] **`/chat` stays text-only; vision happens only on explicit `/vision/*` calls.** This is the user's central cost-gating requirement. A Flora "ask" lives as a `vision_request` field on the `/chat` reply (free, no image send); the app triggers a `/vision/*` call only after the user authorizes. Confirm.
- [ ] **AI-initiated ask, user-authorised grant.** No server-side "auto-grant after N seconds" / "auto-grant if photo small"; the user's tap in the app is the only grant. Confirm.
- [ ] **Public-bucket retrieval in V1.0.** The agent fetches the resolved public URL by HTTP GET; ownership is proven by the **DB lookup under RLS**, not the bucket. Confirm this is acceptable now (or request a private-bucket + signed-URL design instead — see below).
- [ ] **One image per request.** No album / before-after comparison in V1.0. Confirm.
- [ ] **Resize-before-send with Pillow; re-encode JPEG at `vision_jpeg_quality`.** Alpha/palette flattened to RGB. Confirm Pillow is an acceptable new runtime dependency (it pulls some native image codecs; keeps the image small).
- [ ] **MIME allowlist `{image/jpeg, image/png, image/webp}`**, decoded with Pillow (source of truth) rather than trusting declared `content_type`. Confirm with the React Native picker's output formats.
- [ ] **Separate `gemini_vision_model` setting** (decoupled from the text model). Confirm the split is right.
- [ ] **Lower vision temperature (0.4)** for calm, non-hallucinatory diagnoses. Confirm or set differently.
- [ ] **Calibration via `needs_more_info`, not a mandatory pre-question step.** Flora asks a Spanish clarifying question when context is insufficient instead of forcing a multi-turn calibration form. Confirm this keeps V1.0 feeling like a friend, not a form.
- [ ] **Off-topic non-plant images: decline, don't classify.** Add an explicit `vision.kind="declined"` value (recommended) so the contract is unambiguous; Flora's `reply` declines in Spanish and steers back to plants. Confirm the `kind` value set: `health | identify | mixed | declined`.
- [ ] **No persistence on the inline path.** `/vision/analyze-upload` writes nothing to Supabase, nothing to disk. Saving the uploaded image (if desired) is the client's job, done outside the agent. Confirm.
- [ ] **Audit = structured agent logs, not a Supabase table.** Vision audit events go to Cloud Logging via structlog (sizes/model/confidence/duration). Confirm, consistent with 003.

## Supabase Storage (gates Phase 2 + 5 + 10)

- [ ] Confirm the storage bucket name. Current evidence: `plant-photos` (URLs are `…/storage/v1/object/public/plant-photos/<user_id>/<plant_id>/<ts>.jpeg`).
- [ ] Confirm the bucket's visibility is **public** for V1.0 (this is what the agent will assume for HTTP GET retrieval).
  - If you want this private instead (recommended for the long-term privacy of each plant's visual history), the follow-up design is: a Storage RLS policy (`auth.uid() = owner`) + the agent mints a **Signed URL** under the user's access token and GETs that. That swap is isolated to `app/vision/retrieval.py` and is flagged as a 004-paved follow-up; confirm whether 004 ships with public retrieval or waits for private + signed URLs.
- [ ] Confirm the URL pattern is stable (the agent only needs to GET the URLs it reads from `journal_entries.photo_url` and `plants.photo_url`; it does not parse the path).
- [ ] Confirm the bucket has **no** policy that would silently 429 / 503 a per-request GET under expected load.
- [ ] If the bucket visibility decision changes after 004 ships, file it as the follow-up that updates `app/vision/retrieval.py:fetch_photo_bytes` (signed-URL mint + GET) — no other 004 code needs to move.

## Gemini vision model (gates Phase 0 + 3 + 10)

- [ ] Select the actual `gemini_vision_model` the agent should call (the default placeholder is `gemini-2.0-flash`). Confirm it:
  - accepts a multimodal request (image `Part` + text) with `response_schema` (structured output); if not, confirm the fallback (a constrained JSON-only follow-up per `plan.md` Risk) is acceptable.
  - is billable within the project's Gemini plan for the expected call volume.
- [ ] Confirm pricing-per-vision-call is acceptable given that **every** vision call is gated behind an explicit `/vision/*` request (no auto-injection). Provide a rough cost ceiling you can live with so `vision_max_image_bytes` / `vision_max_dimension` can be tuned in `tasks.md` Phase 0.

## Image caps & formats (gates Phase 0 + 1 + 10)

- [ ] Confirm `vision_max_image_bytes` raw cap before resize (default `8_000_000` ~ 8 MiB). Set based on the mobile app's photo resolution.
- [ ] Confirm `vision_max_download_bytes` ceiling on the public-bucket GET stream (default `10_000_000`).
- [ ] Confirm `vision_max_dimension` longest side after resize (default `1024`). Higher → better diagnosis but costlier.
- [ ] Confirm `vision_jpeg_quality` re-encode quality (default `85`).
- [ ] Confirm the MIME allowlist covers everything the picker emits enthusiastically (no HEIC/HEIF in V1.0 unless the picker actually produces them — if so, add `image/heif` and confirm Pillow can decode it, or require the picker to transcode to JPEG/PNG).

## Schema (already known from 002/003 — confirm unchanged)

- [ ] `journal_entries.photo_url` (text, nullable) holds a public Storage URL; `journal_entries.type` enum includes `observation`.
- [ ] `plants.photo_url` (text, nullable) holds a public Storage URL.
- [ ] No new tables, no new columns, no new RLS policies are added by 004 (the agent does not own schema). RLS `SELECT` on `journal_entries` and `plants` (already in place for 002) is reused for `analyze-stored` resolution.

## Test images (gates Phase 10 manual smoke)

- [ ] A test Supabase user with at least one `journal_entries` row whose `photo_url` is non-null (ideally a real plant photo with a visible symptom for a satisfying smoke diagnosis).
- [ ] One `plants` row for the test user with a non-null `photo_url` (for the `plant_latest` happy path).
- [ ] A second test user with at least one journal photo, so the cross-user `404 IMAGE_NOT_FOUND` smoke can run.
- [ ] A local fixture set for unit tests: a small JPEG of a plant, a small JPEG of a non-plant object (e.g. a coffee mug) for the `kind="declined"` path, an oversized JPEG, an undecodable-bytes blob, and a PNG with alpha channel (for the RGBA→RGB flatten test). Provide to the agent or confirm the agent may synthesise these in `tests/` via Pillow.

## App-side coordination (so 004's contract matches reality)

- [ ] The React Native client, on a `/chat` reply with a non-null `vision_request`, shows Flora's `reason_es` plus a confirm affordance ("Share the photo with Flora"); on the user's tap, the client calls `POST /vision/analyze-stored` with the `suggested_ref` from the `/chat` reply.
- [ ] When the user directly snaps/picks a photo to ask Flora about it (no prior `vision_request`), the client calls `POST /vision/analyze-upload` with the bytes + `message` + optional `plant_id`.
- [ ] The client never expects the agent to upload the inline image — if the user wants to *keep* a photo, the client uploads to `plant-photos` itself and references the new URL via `journal_entries` separately.
- [ ] The client surfaces `vision.confidence` and `vision.needs_more_info.question_es` in a clear (non-alarmist) way; a `baja` confidence is shown as "Flora isn't sure yet — can you tell her …", not as a diagnostic verdict.
- [ ] The client handles `400 INVALID_IMAGE` / `404 IMAGE_NOT_FOUND` / `502 UPSTREAM_ERROR` gracefully (a friendly Spanish line + retry), consistent with 002/003's error UX.

---

Once **Decisions to confirm**, **Supabase Storage**, and **Gemini vision model** are done, Phases 0–3 can land. Once **Image caps & formats** and **Schema** are confirmed, Phases 5–6 are unblocked. **Test images** (and the bucket-visibility decision) only gate the Phase 10 manual smoke.
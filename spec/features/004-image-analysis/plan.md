# 004 - Image Analysis

## Approach

Add a **vision** capability that is structurally incapable of wasting credits or analyzing without consent. The dominant design axis the user named is **cost gating**: an image may only reach Gemini on an **explicit** `/vision/*` call from the app, never automatically. So the architecture is **"three separable surfaces, with the image bytes living on only one of them":**

1. **`/chat` (text-only, untouched at the bytes level).** Still injects 002 context — which already surfaces photo *metadata* (`photo_count`) and nothing more. No `photo_url`, no Storage URL, no bytes ever reach the Gemini call on `/chat`. Flora's reply gains one optional sibling: `vision_request` (an **ask for authorization**, not an analysis). Asking costs the same text-only Gemini call `/chat` always makes. This is the AI-initiated gating path.
2. **`/vision/analyze-stored` (JSON).** The user (or Flora's ask, escalated by the app) wants Flora to look at a photo already in their journal. The agent resolves the `photo_url` via the user's RLS-scoped Supabase client (`journal_entries` row by id, or `plants`/latest `journal_entries` for `plant_latest`), so a cross-user or absent ref resolves to **no row** under RLS → `404 IMAGE_NOT_FOUND`. It then downloads the bytes from the existing **public** `plant-photos` Storage bucket by HTTP GET of the resolved URL. The lookup — not the URL — is what proves ownership: RLS already denied the row, so the URL is provably the caller's.
3. **`/vision/analyze-upload` (multipart, no persistence).** A user hands Flora a photo to look at without it ever being stored. The agent reads the part into memory (capped), validates MIME + decodability with Pillow, resizes, calls Gemini, and drops every reference. There is no Supabase write, no Storage upload, no disk write — confirmed in tests by asserting zero `.insert`/`.upload`/filesystem calls.

Both vision paths share a **single vision core** (`app/vision/core.py`): validate → cap → resize → build Gemini `Part` + prompt (grounded in 002 deep context when `plant_id` is supplied) → call a vision-capable model with structured output → return `(reply, vision, proposed_action_raw)`. The route then reuses 003's `_build_proposed_action` to mint a `confirm_token` if Flora elected an action. So 004 touches the existing `/chat` route only to add the `vision_request` plumbing; the heavy lifting lives in a new `app/vision/` package, parallel to `app/actions/`.

Two design tightropes:
- **Public bucket vs. the user framing retrieval as "through Supabase".** The `plant-photos` bucket is currently **public** (URLs are `…/storage/v1/object/public/plant-photos/<user_id>/<plant_id>/<ts>.jpeg`), so the bytes fetch is a plain HTTP GET — no Storage signed URL, no service-role key. The privacy fence is the **DB lookup under the user's access token** (RLS), not the bucket. This is acceptable for V1.0 because the bucket's visibility is an app-team decision the agent doesn't own; the agent's responsibility is to **never widen** what it fetches beyond rows the user already owns, and to **never log** the URL (a public bucket is still a private locator for a plant's history). If the bucket is later made private, the only change is swapping the GET for a signed-URL retrieve via the user's access token — flagged in Risks, scoped as a follow-up.
- **Cost determinism.** Every byte that reaches Gemini has been validated, capped by raw size (`vision_max_image_bytes`), resized to ≤ `vision_max_dimension`, and re-encoded at `vision_jpeg_quality`. One image per request. A dedicated `gemini_vision_model` setting lets the team pick a vision-capable model without disturbing the cheaper text model `/chat` uses. Vision calls emit a structured audit event with sizes/model/confidence so cost is observable per call. No image is ever sent on a `/chat` turn — proved in tests by inspecting mocked Gemini `parts`.

Sequenced so each phase produces something verifiable, with the image-processing primitives (no Supabase/Gemini dependency) and the vision core landing before the routes:

1. **Pre-flight & constitution sync** — confirm decisions (endpoint split, public-bucket retrieval, vision model, caps, one-image-per-request, calibration/needs-more-info stance, off-topic non-plant refusal); add deps (`pillow`, declare `httpx` runtime) and settings; reconcile `tech-stack.md` and reframe the "No image analysis" limit.
2. **Image processing primitives** (`app/vision/images.py`) — `validate_image_bytes(raw, settings)`, `resize_image(raw, settings) -> bytes` (Pillow, RGB-flatten, max-dimension cap, JPEG quality, return new bytes), MIME sniff (Pillow decode is the source of truth; declared `content_type` is advisory). Pure, fully unit-tested without Gemini.
3. **Stored-photo retrieval** (`app/vision/retrieval.py`) — `resolve_journal_photo(client, journal_entry_id)`, `resolve_plant_latest_photo(client, plant_id)`. Both return a `ResolvedPhoto { url, mime_hint }` or `None` under the user's RLS-scoped client; `None` ⇒ `404 IMAGE_NOT_FOUND`. `fetch_photo_bytes(url, client) -> bytes` does the HTTP GET from the public bucket via httpx, with a ceiling (`vision_max_download_bytes`) and streaming-abort on oversize.
4. **Vision core** (`app/vision/core.py`) — `analyze_image_with_gemini(image_bytes, mime_type, message, context_str, settings) -> VisionAnalysis`. Calls `gemini_vision_model` with the image `Part` + Flora-scope prompt + 002 context + structured output schema `{reply, proposed_action?, vision}`. Reuses the existing `call_gemini` style but with multimodal parts; on Gemini failure raises `UpstreamError` (→ `502`).
5. **`/chat` `vision_request`** — extend `ACTION_RESPONSE_SCHEMA` with nullable `vision_request`; prompts add a section telling Flora she may **ask** for a photo (free, text-only) but never claim to have seen one; route's `_build_vision_request` validates `suggested_ref.kind`, drops foreign-`plant_id` asks, mints no token (asking is not an action). `/chat` stays text-only — proved by inspecting mocked Gemini parts.
6. **`/vision/analyze-stored` endpoint** (`app/vision/routes.py`) — auth dep → resolve ref under RLS (reuse `build_user_client`) → fetch bytes → resize → vision core → build `proposed_action` if present (reuse 003 helper) → `200` or `404`/`400`/`502`. Emits audit event.
7. **`/vision/analyze-upload` endpoint** (same router) — auth dep → read `UploadFile` into memory capped → validate → resize → vision core (with optional 002 context when `plant_id` given) → build `proposed_action` → `200` or `400`/`502`. **No Supabase client is constructed for write paths** — only `build_plant_context` if `plant_id` is provided; asserts in tests that no `.insert`/`.upload`/filesystem call happens.
8. **Audit & logging** (`app/vision/audit.py`) — `log_vision_call(...)` emitting the structured event; never the URL, bytes, or extracted text.
9. **Contract & docs** — `docs/api-contract.md` (the two routes, the multipart shape, `VisionAnalyzeResponse`, image constraints, the gating rule, new error codes `400 INVALID_IMAGE` / `404 IMAGE_NOT_FOUND`); README env vars (none new, only the `vision_*` / `gemini_vision_model` settings); `tech-stack.md` file map + settings.
10. **Tests (full regression)** — image/resize unit tests, retrieval (RLS deny → 404, null `photo_url` → 404, plant-missing → 404, Supabase fail → 502), upload (no-persistence assertion), `/chat` ask (`vision_request` present/absent, foreign plant dropped, text-only asserted), vision reply shapes (diagnosis/identify/needs-more-info/off-topic), `proposed_action` reuse, audit fields + no-bytes-logged, full 001/002/003 regression. Mock Gemini + Supabase + httpx in CI.
11. **Manual smoke (gated on a real Supabase user with a journal photo + a private bucket decision)** — real `/vision/analyze-stored` against a seeded photo; real `/vision/analyze-upload` with a fresh image; confirm zero new Storage rows and zero new `journal_entries` rows after the upload path; then move 004 to Done in `roadmap.md`.

## Implementation

Files 004 touches (increment over 003's layout; new modules marked `+`):

```
app/
├── vision/                          # +
│   ├── __init__.py
│   ├── images.py                    # validate_image_bytes, resize_image, sniff_allowed_mime
│   ├── retrieval.py                 # resolve_journal_photo, resolve_plant_latest_photo,
│   │                                #   fetch_photo_bytes (httpx GET from public bucket, capped)
│   ├── core.py                       # analyze_image_with_gemini -> VisionAnalysis (vision model,
│   │                                #   multimodal Parts, structured output {reply, proposed_action?, vision})
│   ├── audit.py                     # log_vision_call(...) -> structlog JSON (sizes/model/confidence; no URL/bytes)
│   ├── models.py                    # ImageRef (journal_entry | plant_latest), VisionRequest, VisionAnalysis,
│   │                                #   VisionAnalyzeResponse (reply + vision + proposed_action | null)
│   └── routes.py                     # POST /vision/analyze-stored, POST /vision/analyze-upload
├── agent/
│   ├── loop.py                      # call_gemini stays text-only; vision lives in app/vision/core.py
│   └── prompts.py                    # + section: Flora may ASK for a photo (vision_request), never claim
│                                   #   to have seen one; + vision sub-prompt (diagnosis vs identify, confidence,
│                                   #   calibration/needs-more-info, off-topic non-plant refusal)
├── api/
│   └── routes.py                     # /chat response gains optional vision_request; mints NO token for it;
│                                   #   ACTION_RESPONSE_SCHEMA gains nullable vision_request
├── config/
│   └── settings.py                  # + gemini_vision_model, vision_max_image_bytes, vision_max_dimension,
│                                   #   vision_jpeg_quality, vision_max_download_bytes, vision_allowed_mime (list)
└── main.py                          # wire vision router; INVALID_IMAGE + IMAGE_NOT_FOUND exception handlers

docs/
└── api-contract.md                  # vision_request on /chat; POST /vision/analyze-stored;
                                    #   POST /vision/analyze-upload (multipart); VisionAnalyzeResponse;
                                    #   image constraints; gating rule; 400 INVALID_IMAGE, 404 IMAGE_NOT_FOUND

tests/
├── conftest.py                      # + httpx mock for storage fetch; pillow fixtures (plant + non-plant
│                                   #   images); supabase write mock assertion helpers
├── test_vision_images.py            # + validator/resize unit tests (MIME accept/reject, oversized, decode-fail,
│                                   #   dimensional cap, JPEG quality, palette/alpha → RGB)
├── test_vision_retrieval.py         # + RLS-resolve → bytes; cross-user journal_entry → 404; null photo_url → 404;
│                                   #   plant_latest missing → 404; Supabase fail → 502; download oversize → 502/400
├── test_vision_chat_request.py      # + /chat vision_request present when a photo would help; null when not;
│                                   #   suggested_ref.kind validated; foreign plant_id dropped;
│                                   #   mocked Gemini parts are text-only on every /chat turn
├── test_vision_stored_endpoint.py   # + happy path (each ref kind); 404 paths; 400 unknown kind; 502 Gemini;
│                                   #   proposed_action minted via 003 machinery on a diagnosis; audit fields
├── test_vision_upload_endpoint.py   # + multipart happy; oversized → 400; bad MIME → 400; one-file-only (422);
│                                   #   NO Supabase insert/upload asserted; NO filesystem write asserted;
│                                   #   resize-then-send asserted against mocked Gemini parts; audit fields
├── test_vision_reply_shapes.py      # + diagnosis shape + confidence; identification ranked + confidence;
│                                   #   needs_more_info when context insufficient; off-topic non-plant decline;
│                                   #   proposed_action reuse; audit no-bytes-logged
└── test_chat.py / test_chat_context.py / test_actions_*.py   # 001/002/003 regression still green

spec/constitution/
├── tech-stack.md                    # + app/vision/ in file map; vision_* + gemini_vision_model settings;
│                                   #   new deps (pillow, httpx); "No image analysis" lifted
└── roadmap.md                       # mark 004 items Done at the very end

pyproject.toml                       # + pillow>=10.4 (runtime), httpx>=0.27 (runtime, declared explicitly)
.env.example                         # + GEMINI_VISION_MODEL, VISION_MAX_IMAGE_BYTES, VISION_MAX_DIMENSION,
                                    #   VISION_JPEG_QUALITY (all optional with defaults)
```

Key flows (delta from 003):

- **`/chat` response — gains an optional `vision_request` sibling to `reply`/`proposed_action`:**
  ```json
  {
    "reply": "string (Spanish, on-brand)",
    "proposed_action": { "...(unchanged from 003)" } | null,
    "vision_request": {
      "reason_es": "string (Spanish question asking to see a photo)",
      "suggested_ref": {
        "kind": "journal_entry | plant_latest",
        "journal_entry_id": "uuid (when kind=journal_entry)",
        "plant_id": "uuid (when kind=plant_latest)"
      }
    } | null
  }
  ```
  The handler issues `vision_request` only when Gemini returns a valid `suggested_ref` whose kind is allowlisted and whose `plant_id` (when `kind=plant_latest`) matches the request's `plant_id` or, when absent on the request, is the plant present in Flora's context. A foreign/invalid ask is dropped to `null` rather than surfaced — asking is a courtesy, never a hard error.
- **`POST /vision/analyze-stored` request (JSON):**
  ```json
  {
    "message": "string (1–2000 chars, the user's question about the photo)",
    "plant_id": "uuid | null (optional, for 002 deep context grounding)",
    "image_ref": {
      "kind": "journal_entry | plant_latest",
      "journal_entry_id": "uuid (when kind=journal_entry)",
      "plant_id": "uuid (when kind=plant_latest; defaults to the request's plant_id)"
    }
  }
  ```
  **Headers:** `Authorization: Bearer <supabase_access_token>` (required, same as `/chat`).
- **`POST /vision/analyze-upload` request (multipart/form-data):**
  - `image` — one file part (`image/jpeg`, `image/png`, or `image/webp`), size ≤ `vision_max_image_bytes`.
  - `message` — string (1–2000 chars).
  - `plant_id` — optional string (added to the form for context grounding).
  **Headers:** `Authorization: Bearer <supabase_access_token>` (required).
- **`POST /vision/analyze-stored` / `POST /vision/analyze-upload` response** (`200 VisionAnalyzeResponse`):
  ```json
  {
    "reply": "string (Spanish, on-brand)",
    "vision": {
      "kind": "health | identify | mixed",
      "diagnosis": "string | null (Spanish, when kind=health or mixed)",
      "possible_species": [
        { "name": "string", "confidence": "alta | media | baja" }
      ],
      "confidence": "alta | media | baja",
      "needs_more_info": { "question_es": "string | null" }
    },
    "proposed_action": { "...(003 shape, with confirm_token)" } | null
  }
  ```
  - `vision.kind="mixed"` covers the cases where Flora both diagnoses and tentatively identifies, **and** the off-topic-decline case (with `diagnosis=null`, no `possible_species`, and a `reply` that declines in Spanish — the team confirms whether to add an explicit `kind="declined"` value in Decisions).
  - `vision.needs_more_info.question_es` is non-null when `confidence="baja"` and Flora is asking a clarifying question rather than guessing — the calibration-guidance mapping.
- **Vision → `proposed_action` reuse** — the vision core returns `proposed_action_raw` in the same structured shape 003's `/chat` expects; the vision route calls the **existing** `_build_proposed_action(result, plant_id, user.sub, settings)` (lifted to a shared helper if needed) so tokens, payloads, and the 003 allowlist are reused verbatim. A diagnosis proposing "save this tip to your Monstera's journal" produces an `add_journal_entry` proposal with the *diagnosis text* as `content` — never `photo_url`. Saving the image itself is out of reach (the app uploads to Storage; the agent never does).
- **Retrieval path (stored)** — `build_user_client(url, anon_key, access_token)` (reused from 002) → `resolve_journal_photo(client, id)` runs `select photo_url from journal_entries where id=?` (RLS denies cross-user → empty) → returns the URL or `None`. `None` (foreign `id`, or own row with `photo_url IS NULL`) → `404 IMAGE_NOT_FOUND`. `fetch_photo_bytes(url)` does `httpx.AsyncClient.get(url)` against the public bucket, streams with a `vision_max_download_bytes` ceiling (abort + `502 UPSTREAM_ERROR` on oversize), returns bytes. The URL is then dropped from logs/memory before the resize step.
- **Inline-upload path** — `UploadFile.read(vision_max_image_bytes + 1)`; len > cap → `400 INVALID_IMAGE`. `validate_image_bytes` uses `Pillow.Image.open(BytesIO(raw))` + `.verify()`; if it raises, or the inferred format isn't in `vision_allowed_mime`, → `400 INVALID_IMAGE`. `resize_image` re-opens, converts to `RGB`, resizes (longest side ≤ `vision_max_dimension`, only downscale, never upscale), saves to `BytesIO` as JPEG with `vision_jpeg_quality`. Original bytes are released; only the resized bytes travel to Gemini. The route **never** calls `build_user_client` for writes; it may call it for `build_plant_context` if `plant_id` is provided, then drops it.
- **Vision Gemini call** — `app/vision/core.py:analyze_image_with_gemini(...)` builds a `types.Part.from_bytes(data=resized, mime_type="image/jpeg")` + a text part containing the vision sub-prompt + 002 context (when `plant_id`) + the user's `message`, configured with `gemini_vision_model`, `temperature` (a lower default for vision, e.g. 0.4 — calm but not hallucinatory), `response_mime_type="application/json"` + a `response_schema` describing `{reply, proposed_action?, vision}`. On Gemini exception → `UpstreamError` → `502`. The structured result is validated by Pydantic models in `app/vision/models.py` (defense-in-depth; Gemini's schema is not the source of truth on the agent side).

Settings added to `app/config/settings.py`:

```python
gemini_vision_model: str = (
    "gemini-2.0-flash"  # vision-capable model; team confirms (see users-tasks.md)
)
gemini_vision_temperature: float = 0.4  # lower than text; calm, not hallucinatory
vision_max_image_bytes: int = 8_000_000  # raw upload/download cap before resize (~8 MiB)
vision_max_download_bytes: int = 10_000_000  # ceiling on the public-bucket GET stream
vision_max_dimension: int = 1024  # longest side after resize
vision_jpeg_quality: int = 85  # re-encode quality
vision_allowed_mime: list[str] = ["image/jpeg", "image/png", "image/webp"]
```

(No new secrets. Storage uses the public bucket — no service-role, no Storage signed-URL secret. Supabase access still goes through the user's `Bearer` token as in 002/003.)

## Decisions

Recommended defaults, all confirmable before code touches:

- **Two intake paths, not one fused one.** Retrieving from Supabase (`analyze-stored`) and receiving ad-hoc (`analyze-upload`) are deliberately separate endpoints: different request shapes (JSON vs multipart), different trust postures (RLS-resolved URL vs untrusted inline bytes), and different audit fields. A fused "either a ref or a file" endpoint would muddy the contract and the test matrix. Confirm.
- **Vision lives in `app/vision/`, not inside `call_gemini`.** The text `/chat` loop (`app/agent/loop.py`) stays text-only and untouched at the parts level; a new `app/vision/core.py` owns multimodal calls. **Rejected:** overloading `call_gemini` with an optional `image`/`parts` param — it would invite a future caller to attach an image to a `/chat` turn, undoing the gating rule. Confirm.
- **`/chat` is provably text-only.** A `vision_request` from Flora is a *request to analyse later*, not a hidden image send. A unit test inspects the mocked Gemini call's `contents`/`parts` on every `/chat` turn and asserts only text is present. **Rejected:** "let Flora decide turn-by-turn whether to attach the journal's latest photo" — that is the auto-injection the user explicitly disallowed. Confirm.
- **AI-initiated ask via `vision_request`, user-authorised grant via the app.** When Flora wants a photo, she asks (free, text); the app surfaces the ask; only the user's *explicit* authorisation triggers a `/vision/*` call. **Rejected:** a server-side "auto-grant after N seconds" or "auto-grant if the photo is small" — both reintroduce unauthorised vision spend. Confirm.
- **Public-bucket retrieval in V1.0.** The `plant-photos` bucket is currently public; the agent fetches the resolved URL by HTTP GET. Ownership is proven by the **DB lookup under RLS**, not by the bucket. **Rejected:** minting Storage signed URLs now preemptively — it's complexity only useful if the bucket is later locked down, and the public-bucket privacy posture is the app team's call to revise (flagged in `users-tasks.md`). Confirm. Flag the signed-URL follow-up as a Risk.
- **One image per request.** V1.0 supports exactly one image per `/vision/*` call. **Rejected:** album/before-after comparison — defer to a later feature once usage justifies the cost. Confirm.
- **Resize-before-send (agent-side), with `pillow`.** The roadmap explicitly calls for resize/optimise to control cost + latency; Pillow is the canonical Python imaging lib. Re-encode to JPEG at `vision_jpeg_quality` so non-JPEG inputs (PNG/WebP with alpha) are flattened to RGB and quality-capped. **Rejected:** letting Gemini downscale server-side only — it does — but pre-capping is the cost knob the roadmap wants and it bounds what reaches the wire. Confirm Pillow as a new runtime dep.
- **`httpx` declared as a runtime dep.** FastAPI/Starlette pull httpx transitively for the test client, and supabase-py uses httpx; we declare it explicitly because the agent now depends on it directly for the Storage GET. Confirm.
- **MIME allowlist of `{jpeg, png, webp}`.** The three MIMEs the mobile app's picker will produce. Bytes are decoded with Pillow (source of truth) rather than trusting `content_type`. **Rejected:** trusting declared `content_type` alone (`image/jpeg` headers on a `.exe` body). Confirm.
- **`400 INVALID_IMAGE` for validator rejects; `404 IMAGE_NOT_FOUND` for RLS-denied/absent stored refs; `502 UPSTREAM_ERROR` for Gemini and Storage-download failures (reuse).** Distinct failure classes: the request body's image is unprocessable (`400`), the ref points at nothing the user owns (`404`, consistent with 002's "RLS turns 'not yours' into 'doesn't exist'"), upstream AI/Storage is down (`502`). No `403` (matches 002 reasoning). Confirm.
- **`gemini_vision_model` separate from `gemini_model`.** Vision-capable models and text-cheap models differ; decoupling lets the team upgrade one without the other. Default `gemini-2.0-flash` is a placeholder; **the team confirms the actual vision-capable model** in `users-tasks.md`. Confirm the split is right.
- **Lower vision temperature (0.4).** Diagnosis benefits from less sampliness than chit-chat; 0.4 keeps Flora's calm voice without inventing symptoms. Confirm or set differently.
- **Calibration via `needs_more_info`, not via a hard pre-question step.** When the photo + context are insufficient, Flora returns `confidence="baja"` plus a clarifying `question_es` and waits, instead of forcing a multi-turn "answer my three questions before I look" flow. Matches `mission.md`'s honesty rule and keeps vision single-shot. **Rejected:** a mandatory calibration sub-flow before every vision call — it would make V1.0 feel like a form, against the relaxing-UX principle. Confirm.
- **Off-topic non-plant images: decline, don't classify.** Flora declines politely in Spanish and steers back to plants; she does not produce a "this is a cat" classification. The vision sub-prompt enforces scope. **Open question (confirm):** is `vision.kind="mixed"` with a declining `reply` enough, or should we add an explicit `kind="declined"` value to make the contract unambiguous? Recommendation: add `kind="declined"` for clarity.
- **No persistence on the inline path, asserted in tests.** The upload endpoint never constructs a write client; tests assert zero `.insert`/`.upload`/filesystem calls. Saving the uploaded image is the app's job, done outside the agent (the agent does not own Storage). Confirm.
- **Audit = structured agent logs, not a Supabase table.** Same decision as 003. Vision audit events (sizes/model/confidence/duration) go to Cloud Logging via structlog. Confirm this is acceptable.
- **`proposed_action` reuse verbatim.** A diagnosis electing an action goes through the *exact* 003 path (allowlist, Pydantic validation, `confirm_token`, `POST /actions/execute`). No new writable surface, no new verbs. Confirm.

## Risks

- **Public bucket is world-readable (highest existing-app risk surfaced by 004).** Any URL resolved to a row the user *owns* is also fetchable by anyone who guesses it. This is an app-team privacy decision the agent cannot change. Mitigation in 004: never log URLs, never echo URLs in responses, never widen the fetch beyond RLS-resolved rows. Flag to the app team in `users-tasks.md`: the long-term fix is a **private bucket + Signed URLs minted under the user's access token** (Storage RLS); a 005+ follow-up swaps the GET for a signed-URL retrieve. The agent's role now is to *not make it worse*.
- **Bucket goes private later → 004 breaks.** A swap to a private bucket turns the public GET into a `403`. Mitigation: the retriever is isolated (`app/vision/retrieval.py`); the swap is a single function — `fetch_photo_bytes` becomes "mint a signed URL via the Supabase Storage API under the user's token, then GET". Flagged as a small follow-up, not a blocker.
- **Vision hallucinated diagnosis (high).** An LLM can confabulate a confident disease from pixels + leading user text. Mitigation: confidence field, calibration via `needs_more_info`, lower temperature, explicit "say `confidence=baja` and ask, rather than guess" guidance, and the 001 honesty rule embedded in the vision sub-prompt. Asserted by a test that mocks a context-starved scenario and expects `needs_more_info` rather than a fabricated diagnosis. Residual: a user may still act on a `media`-confidence diagnosis; the app's confirm card owns the disclaimer UX.
- **Cost runaway on the inline path.** A user could spam `/vision/analyze-upload`. Mitigation: vision is gated behind explicit UI action, one image per request, capped bytes, audited per call; a per-user rate limit is *not* in V1.0 (deferred — there is no per-user rate state today; see Backlog). Flagged for the team.
- **Decoding an adversarial image.** Pillow has had CVEs around malformed images. Mitigation: read into memory with a hard cap (`vision_max_image_bytes + 1`), `Image.verify()` before `Image.open()`, pinned Pillow version in `pyproject.toml`, no exec of any embedded payload (we only decode + resize). A crash is contained to the request and becomes `500 INTERNAL_ERROR` (or `400 INVALID_IMAGE` if Pillow raises a recognised format error). Keep Pillow pinned to a current patch release.
- **Multipart body size exhaustion.** A client could stream a huge part past `vision_max_image_bytes` before FastAPI rejects it. Mitigation: read with an explicit `+1` byte ceiling and reject on overflow; do not rely on FastAPI's default body limits alone; set `VISION_MAX_IMAGE_BYTES` conservatively (8 MiB). Confirm the cap with the team given the mobile app's photo resolution.
- **`vision_request` leaking which photos a plant has.** The `suggested_ref.journal_entry_id` returned by `/chat` is an id the user just saw in their own journal, so the leak is to themselves; still, `/chat` must only ever propose IDs from the user's own context (RLS-resolved). A test asserts no `vision_request` proposes an id that wasn't in 002's deep context set. Low likelihood, defence-in-depth.
- **Gemini vision model's structured-output support.** The chosen `gemini_vision_model` must support `response_schema` with image parts. Mitigation: feature-detect (same fallback pattern as 003) or pick a known-supporting model in `users-tasks.md`; on failure, return `502` rather than a malformed reply.
- **Identification confidence overclaim.** Photos often can't ID a species to rank; a terse `possible_species` list with a single high-confidence candidate can mislead. Mitigation: prompt requires ranked candidates with explicit confidence tiers, and a model statement that photo-only ID is tentative; `needs_more_info` can ask for a clearer leaf/flower shot. Confirm the candidates shape with the team.
- **Audit log accidentally shipping bytes.** A future logger refactor could dump a base64 image by mistake. Mitigation: the `log_vision_call` helper takes only scalar fields (sizes, mime, confidence) — there is no image field in its signature, so bytes can't be logged through it. A test asserts no audit record contains image data.
- **`/chat` regression from the schema change.** Adding nullable `vision_request` to `ACTION_RESPONSE_SCHEMA` changes what Gemini is asked to produce on every `/chat` turn. Mitigation: the field is nullable and the prompt explicitly says it's optional and usually `null`; regression tests cover the no-action no-vision common case; cost delta is re-evaluated in smoke.
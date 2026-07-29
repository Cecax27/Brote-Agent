# Routes and request/response shapes

## `GET /health`

Cloud Run health check endpoint.

**Request:** no body.

**Response `200`:**

```json
{
  "status": "ok"
}
```

---

## `POST /chat`

Main conversation endpoint. Sends a user message to the AI and returns its Spanish reply, optionally with a proposed action the user can confirm.

**Headers:**
- `Authorization: Bearer <supabase_access_token>` (required)
  The agent verifies the token locally and uses it to scope Supabase reads to the caller's own data via Row Level Security.

**Request:**

```json
{
  "message": "string (required, 1–2000 characters)",
  "plant_id": "string | null (optional)",
  "conversation_id": "uuid | null (optional)"
}
```

- `plant_id`: when set, Flora gets deep context for that specific plant (recent journal entries, watering history, light readings, etc.) so her reply is personalized. When absent, she gets a light inventory of all the user's plants — enough to prioritize "what needs attention today."
- `conversation_id`: when set, the message belongs to that ongoing conversation — the agent loads recent history into the context window so Flora remembers what was said. When absent, the agent **auto-creates** a new conversation and returns its `conversation_id` in the response (the forgiving "just chat" path).

**Response `200`:**

```json
{
  "conversation_id": "uuid (always present; the id of the conversation this message belongs to)",
  "reply": "string",
  "proposed_action": {
    "action_type": "create_watering_schedule | add_journal_entry",
    "plant_id": "uuid",
    "title": "string (short, Spanish)",
    "summary_es": "string (Spanish confirmation line for the app's card)",
    "payload": { "... (varies by action_type)" },
    "confirm_token": "string (HMAC-signed, single-use, 5-min TTL)"
  } | null,
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

- `proposed_action`: present only when Flora detects actionable intent and the user's request matches the writable surface. The app should display the `summary_es` in a confirmation card and send the entire object unchanged to `/actions/execute` on confirm. The `confirm_token` is a server-signed, single-use token binding the exact payload to the authenticated user; altering any field invalidates it.
- When `proposed_action` is `null` (most responses), there is nothing to confirm.
- `vision_request`: present only when Flora decides seeing a photo would genuinely improve her answer. This is an **ask for authorization**, not an analysis — no image bytes have been sent to the AI on this `/chat` turn. The app should display `reason_es` with a confirm affordance; on user authorization, the app calls `/vision/analyze-stored` with the `suggested_ref` from this object. When `null`, Flora doesn't need a photo.

### Writable surface (V1.0)

| `action_type`             | Table                | Payload fields                                                                 |
|---------------------------|----------------------|--------------------------------------------------------------------------------|
| `create_watering_schedule` | `watering_schedules` | `frequency_days` (int ≥1), `next_due_at` (ISO8601), `last_watered_at` (ISO8601, optional), `notify_time` (HH:MM:SS, optional) |
| `add_journal_entry`        | `journal_entries`    | `content` (1–2000 chars)                                                       |

The `save-a-tip` flow uses `add_journal_entry` with `content` set to the snippet the user wants to preserve. The inserted row has `type="observation"`.

No other tables or operations are writable by the agent in V1.0.

### `confirm_token` model

The token is an HMAC-SHA256 over `(payload digest | user sub | expiry | nonce)`, signed with a server-side secret the app never sees. It is:
- **Single-use**: consumed on successful `/actions/execute`.
- **Short-lived**: 5 minutes from issuance.
- **Tamper-evident**: any change to `payload`, `plant_id`, or `action_type` invalidates it.
- **User-bound**: the token only works for the authenticated user it was issued to.

The app must send the token *exactly* as received; altering any field in the `proposed_action` before calling `/actions/execute` will produce a `400` or `401` response.

---

## `POST /actions/execute`

Confirm and execute an action Flora proposed. Writes to Supabase under the caller's identity via Row Level Security.

**Headers:**
- `Authorization: Bearer <supabase_access_token>` (required)

**Request:**

```json
{
  "action_type": "create_watering_schedule | add_journal_entry",
  "plant_id": "uuid",
  "payload": { "... (must match the proposed payload exactly)" },
  "confirm_token": "string (from the /chat proposed_action)"
}
```

All fields must match the `proposed_action` object returned by `/chat` exactly. Any change invalidates the `confirm_token`.

**Response `201`:**

```json
{
  "action_id": "uuid (the created row's id)",
  "action_type": "string",
  "status": "executed"
}
```

| HTTP status | `code`            | Meaning                                                                 |
|-------------|-------------------|-------------------------------------------------------------------------|
| 201         | —                 | Action executed successfully.                                           |
| 400         | `INVALID_ACTION`  | Unsupported `action_type`, or `confirm_token` payload-hash mismatch     |
| 401         | `UNAUTHORIZED`    | Missing/expired/tampered/foreign-user token                             |
| 422         | `VALIDATION_ERROR`| Invalid or missing request body                                         |
| 502         | `UPSTREAM_ERROR`  | Supabase write failed                                                   |

### Audit logging

Every executed write emits a structured JSON log event to stdout (captured by Cloud Run logging) with: `action_type`, `table`, `plant_id`, `action_id`, `user`, `status`, `duration_ms`, `payload_digest`. Journal entry `content` text is **never** logged — only a truncated SHA-256 digest.

---

### History budget rule

Before each `/chat` turn, the agent loads at most `history_max_messages` (default 20) prior turns of the active conversation, oldest→newest. The combined history text block is further capped at `history_max_chars` (default 6000) — when exceeded, the oldest turns are trimmed first so the most recent context always fits. Both knobs are configurable via settings.

### Auto-title rule

When a conversation is created without an explicit `title` (auto-create on `/chat` or `POST /conversations` with no title), the first user message is used to derive a short Spanish title: truncated at the last whole word ≤ `conversation_title_max_chars` (default 48), with a trailing `…` only when truncation occurred. The title is set exactly once — later turns do not regenerate it. An explicit title provided via `POST /conversations` is never overwritten.

### Plant-scoping rule

A conversation is optionally linked to a single `plant_id`:
- On creation: set from `POST /conversations` or the first plant-bearing `/chat`.
- Once a conversation has a non-null `plant_id`, a subsequent `/chat` carrying a *different* non-null `plant_id` returns `400 CONVERSATION_PLANT_MISMATCH` — a conversation belongs to at most one plant.
- When a conversation has a `plant_id`, Flora loads 002 deep context for **that** plant on every turn, even if the app omits `plant_id` from the request.
- A conversation with a null `plant_id` is scoped on its first plant-bearing `/chat` and locked thereafter.

### Persistence model

Every `/chat` turn writes two `ai_messages` rows (user + assistant) through the user-scoped Supabase client with RLS ownership. The user message is persisted **before** the Gemini call so it survives a 502 failure. On Gemini success the assistant reply is persisted and `ai_conversations.updated_at` is bumped. `proposed_action` payloads and `vision_request` asks are **not** persisted as history text — they are per-turn, ephemeral extras. The `ai_messages.content` column has a database `CHECK (char_length BETWEEN 1 AND 4000)`; assistant replies are defensively truncated to 4000 chars before insert.

---

## `POST /conversations`

Create a new conversation. Optionally scope it to a plant and provide a title.

**Headers:**
- `Authorization: Bearer <supabase_access_token>` (required)

**Request:**

```json
{
  "plant_id": "uuid | null (optional)",
  "title": "string | null (optional, ≤ 200 chars)"
}
```

**Response `201`:**

```json
{
  "conversation_id": "uuid"
}
```

The created conversation's `user_id` is set to the authenticated user (`user.sub` from the verified token). If `title` is omitted, the conversation gets the default title `"Conversación con Flora"` — it will be auto-titled from the first user message on the next `/chat`.

---

## `GET /conversations`

List the authenticated user's conversations.

**Headers:**
- `Authorization: Bearer <supabase_access_token>` (required)

**Response `200`:**

```json
{
  "conversations": [
    {
      "conversation_id": "uuid",
      "title": "string",
      "plant_id": "uuid | null",
      "updated_at": "iso8601",
      "created_at": "iso8601"
    }
  ]
}
```

- Ordered by `updated_at` descending (most recently active first).
- Capped at `conversations_max_results` (default 50).
- RLS-scoped: only returns the caller's own conversations. An empty garden returns `200 {"conversations": []}`.

---

## `GET /conversations/{conversation_id}/messages`

Get the full message list for a conversation.

**Headers:**
- `Authorization: Bearer <supabase_access_token>` (required)

**Response `200`:**

```json
{
  "conversation_id": "uuid",
  "messages": [
    {
      "role": "user | assistant",
      "content": "string",
      "created_at": "iso8601",
      "photo_url": "string | null"
    }
  ]
}
```

- Oldest→newest order.
- `photo_url` is always `null` in V1.0 (the agent writes only text turns).
- A `conversation_id` the caller doesn't own (RLS denies) returns `404 CONVERSATION_NOT_FOUND`.

---

## Error envelope

All error responses follow this structure:

```json
{
  "error": {
    "code": "string",
    "message": "string"
  }
}
```

### Error codes

| HTTP status | `code`            | Meaning                                      |
|-------------|-------------------|----------------------------------------------|
| 400         | `INVALID_ACTION`  | Action not in the writable-surface allowlist |
| 401         | `UNAUTHORIZED`    | Missing, malformed, expired, or invalid token |
| 422         | `VALIDATION_ERROR`| Invalid or missing request body               |
| 502         | `UPSTREAM_ERROR`  | Gemini or Supabase API returned an error      |
| 500         | `INTERNAL_ERROR`  | Unexpected server error                       |

### Privacy / RLS note

Every Supabase read runs as the authenticated user via their access token. Row Level Security on the database side enforces that queries only return rows belonging to that user. The agent never filters by `user_id` manually and never logs context contents (only counts and durations).

### Image analysis gating rule

**Images are never sent to the AI model on `/chat` calls.** The `/chat` response may contain an optional `vision_request` (an *ask for authorization*, not an analysis). Vision analysis only happens on an explicit call to one of the `/vision/*` endpoints. This rule prevents silent credit consumption: every image that reaches the AI has been explicitly authorized by the user.

---

## `POST /vision/analyze-stored`

Analyze a stored photo from the user's Supabase plant journal or plant profile. The agent resolves the image reference under the user's RLS-scoped access token, downloads the photo from the existing `plant-photos` Storage bucket, resizes it, and passes it to the vision-capable AI model.

**Headers:**
- `Authorization: Bearer <supabase_access_token>` (required)

**Request:**

```json
{
  "message": "string (1–2000 chars, the user's question about the photo)",
  "plant_id": "uuid | null (optional, grounds the diagnosis in the plant's history)",
  "image_ref": {
    "kind": "journal_entry | plant_latest",
    "journal_entry_id": "uuid (when kind=journal_entry)",
    "plant_id": "uuid (when kind=plant_latest; falls back to top-level plant_id if absent)"
  }
}
```

- `image_ref.kind = "journal_entry"`: analyse the photo attached to a specific journal entry. Must include `journal_entry_id`. The agent looks up the row's `photo_url` via RLS — a foreign or absent row produces `404 IMAGE_NOT_FOUND`.
- `image_ref.kind = "plant_latest"`: analyse the latest photo of a plant. The agent checks `plants.photo_url` first, then falls back to the most recent `journal_entries` row with a non-null `photo_url`. RLS applies.

**Response `200`:**

```json
{
  "reply": "string (Spanish, on-brand)",
  "vision": {
    "kind": "health | identify | mixed | declined",
    "diagnosis": "string | null",
    "possible_species": [
      { "name": "string", "confidence": "alta | media | baja" }
    ],
    "confidence": "alta | media | baja | null",
    "needs_more_info": {
      "question_es": "string | null"
    } | null
  },
  "proposed_action": { "...(003 shape)" } | null
}
```

- `vision.kind="declined"` when the image is clearly not plant-related. No diagnosis or species candidates are produced; `reply` declines politely in Spanish.
- `vision.kind="health"` + `vision.diagnosis` when the user asks about plant health.
- `vision.kind="identify"` + `vision.possible_species` when the user asks for species ID.
- `vision.kind="mixed"` when both health and ID are requested.
- `vision.needs_more_info.question_es` is non-null when `confidence="baja"` — Flora asks for missing context instead of guessing.

| HTTP status | `code`            | Meaning                                                           |
|-------------|-------------------|-------------------------------------------------------------------|
| 200         | —                 | Analysis completed                                                |
| 400         | `INVALID_IMAGE`   | Unknown `image_ref.kind`, or the photo is undecodable / too large |
| 401         | `UNAUTHORIZED`    | Missing/malformed/expired token                                   |
| 404         | `IMAGE_NOT_FOUND` | `image_ref` resolved to no row under RLS, or `photo_url` is null  |
| 422         | `VALIDATION_ERROR`| Invalid/missing request body                                      |
| 502         | `UPSTREAM_ERROR`  | Gemini, Supabase, or Storage download failure                     |

---

## `POST /vision/analyze-upload`

Analyze an image sent directly in the request without storing it anywhere. The image is read into memory, validated, resized, analysed by the vision AI, and discarded — no Supabase write, no Storage upload, no disk write.

**Headers:**
- `Authorization: Bearer <supabase_access_token>` (required)

**Request:** `multipart/form-data`

| Part        | Type          | Required | Constraint                    |
|-------------|---------------|----------|-------------------------------|
| `image`     | file          | yes      | JPEG, PNG, or WebP; ≤ 8 MiB   |
| `message`   | string        | yes      | 1–2000 characters             |
| `plant_id`  | string        | no       | grounds the diagnosis in context |

Exactly one `image` part is allowed per request.

**Response `200`:** same `VisionAnalyzeResponse` shape as `/vision/analyze-stored` (above).

| HTTP status | `code`            | Meaning                                               |
|-------------|-------------------|-------------------------------------------------------|
| 200         | —                 | Analysis completed. Image was not persisted.          |
| 400         | `INVALID_IMAGE`   | Undecodable, wrong MIME, or oversized                 |
| 401         | `UNAUTHORIZED`    | Missing/malformed/expired token                       |
| 422         | `VALIDATION_ERROR`| Missing image/message, or >1 image part               |
| 502         | `UPSTREAM_ERROR`  | Gemini API failure                                    |

### Image constraints

| Setting                | Default     | Meaning                                |
|------------------------|-------------|----------------------------------------|
| Allowed MIME           | jpeg,png,webp | Decoded with Pillow (source of truth) |
| Max raw bytes (upload) | 8 MiB       | Before resize                          |
| Max raw bytes (download) | 10 MiB    | Public-bucket fetch ceiling            |
| Max dimension (resize) | 1024 px     | Longest side after downscale           |
| JPEG quality (resize)  | 85          | Re-encode quality                      |
| Images per request     | 1           | One image per `/vision/*` call         |

All images are resized **before** reaching the AI model. The original bytes are discarded. Inline uploads are never persisted.

---

## Error codes (updated)

| HTTP status | `code`            | Meaning                                      |
|-------------|-------------------|----------------------------------------------|
| 400         | `INVALID_ACTION`                | Action not in the writable-surface allowlist |
| 400         | `INVALID_IMAGE`                 | Image is unprocessable, wrong format, or too large |
| 400         | `CONVERSATION_PLANT_MISMATCH`   | Conversation already belongs to a different plant |
| 401         | `UNAUTHORIZED`                  | Missing, malformed, expired, or invalid token |
| 404         | `IMAGE_NOT_FOUND`               | Stored image reference not found under RLS |
| 404         | `CONVERSATION_NOT_FOUND`        | Conversation does not exist or belongs to another user |
| 422         | `VALIDATION_ERROR`              | Invalid or missing request body |
| 502         | `UPSTREAM_ERROR`                | Gemini or Supabase API returned an error |
| 500         | `INTERNAL_ERROR`                | Unexpected server error |

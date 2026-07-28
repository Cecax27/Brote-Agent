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
  "plant_id": "string | null (optional)"
}
```

- `plant_id`: when set, Flora gets deep context for that specific plant (recent journal entries, watering history, light readings, etc.) so her reply is personalized. When absent, she gets a light inventory of all the user's plants — enough to prioritize "what needs attention today."

**Response `200`:**

```json
{
  "reply": "string",
  "proposed_action": {
    "action_type": "create_watering_schedule | add_journal_entry",
    "plant_id": "uuid",
    "title": "string (short, Spanish)",
    "summary_es": "string (Spanish confirmation line for the app's card)",
    "payload": { "... (varies by action_type)" },
    "confirm_token": "string (HMAC-signed, single-use, 5-min TTL)"
  } | null
}
```

- `proposed_action`: present only when Flora detects actionable intent and the user's request matches the writable surface. The app should display the `summary_es` in a confirmation card and send the entire object unchanged to `/actions/execute` on confirm. The `confirm_token` is a server-signed, single-use token binding the exact payload to the authenticated user; altering any field invalidates it.
- When `proposed_action` is `null` (most responses), there is nothing to confirm.

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

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

Main conversation endpoint. Sends a user message to the AI and returns its Spanish reply.

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
  "reply": "string"
}
```

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
| 401         | `UNAUTHORIZED`     | Missing, malformed, expired, or invalid token |
| 422         | `VALIDATION_ERROR` | Invalid or missing request body               |
| 502         | `UPSTREAM_ERROR`   | Gemini or Supabase API returned an error      |
| 500         | `INTERNAL_ERROR`   | Unexpected server error                       |

### Privacy / RLS note

Every Supabase read runs as the authenticated user via their access token. Row Level Security on the database side enforces that queries only return rows belonging to that user. The agent never filters by `user_id` manually and never logs context contents (only counts and durations).

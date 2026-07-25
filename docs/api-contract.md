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

**Request:**

```json
{
  "message": "string (required, 1–2000 characters)"
}
```

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

| HTTP status | `code`            | Meaning                        |
|-------------|-------------------|--------------------------------|
| 422         | `VALIDATION_ERROR` | Invalid or missing request body |
| 502         | `UPSTREAM_ERROR`   | Gemini API returned an error   |
| 500         | `INTERNAL_ERROR`   | Unexpected server error         |

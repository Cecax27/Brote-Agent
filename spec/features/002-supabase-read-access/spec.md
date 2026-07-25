# 002 - Supabase Read Access

**Status:** Planning

## What makes

This feature lets Flora read the user's own plants and their history, closing the biggest gap left by 001: replies stop being generic and become contextualized. It does not add new endpoints — `/chat` stays the single conversational surface, stateless and single-shot — but it adds everything that has to happen *before* `call_gemini` so the model sees real plant data.

Concretely it delivers:

- **Auth hand-off.** The mobile app passes the Supabase access token in the `Authorization: Bearer <access_token>` header on every `/chat` call. The agent does not log in, does not refresh tokens, and does not handle passwords — it only verifies an identity the client already obtained (the agent "does NOT handle authentication" per `mission.md`).
- **Identity verification.** The agent validates the Supabase JWT locally using the Supabase JWT secret (HS256, audience `authenticated`, issuer check, expiry enforced) and extracts the user `sub`. An invalid/expired/missing token returns `401 UNAUTHORIZED` in the standard error envelope.
- **A scoped Supabase client.** Every read is performed as the authenticated user using their access token, so Row Level Security on the Supabase side is what isolates rows (`auth.uid() = sub`). The agent relies on RLS as defense-in-depth; application code never sorts other users' data out manually.
- **A context builder.** A bounded, minimized view of the user's data is gathered and injected into Gemini's context window. When `/chat` carries an optional `plant_id` (the plant the user is currently viewing in the app — matches Brote's "each plant has its own space"), Flora gets deep context for that one plant; otherwise she gets a light inventory across all the user's plants (enough for "what needs attention today"). The builder pulls plants, logbook/journal entries, watering history & schedule, light readings, fertilizations, repottings, observations, and photo *metadata* — never image bytes.
- **Data minimization.** Reads are capped (max N plants in light context; max M recent entries per history type in deep context) and photo references are summarized as counts + dates, not URLs, so the input-token budget and the user's privacy are both respected.
- **Privacy by construction.** Cross-user access is structurally prevented: RLS returns no rows for foreign data, and the agent's own tests assert scoping on every read path. Context contents are never logged (only counts/durations).
- **An honest error surface.** Supabase API failures map to the existing `502 UPSTREAM_ERROR` envelope; auth failures become a new `401 UNAUTHORIZED` code. Both reuse the uniform `{"error":{"code","message"}}` shape; no secret or token ever appears in a log or response.
- **Contract & docs.** `docs/api-contract.md` documents the `Authorization` header requirement, the optional `plant_id`, the `401` code, and the privacy note.
- **Tests** for the new behavior: missing/malformed/expired/bad-signature → 401; context is injected (deep vs light based on `plant_id`); RLS denial returns empty context (no cross-user leak); data-minimization bounds are honored; a Supabase failure → 502; and the 001 regressions still pass (off-topic refusal, Spanish-only) now that context is in flight.
- **A reconciled constitution.** `spec/constitution/tech-stack.md` is extended (Supabase + auth added to the file map, settings, env vars) and its V0.1 hard limits are reframed as V0.1-scoped — lifting Supabase and auth for V1.0 — matching the same reconciliation pattern 001 used for OpenAI→Gemini.

## Why

001 shipped Flora's voice and guardrails, but explicitly left replies generic: the `spec.md` "Out of reach" section says the **"context over generality"** principle is only *fully met* once 002 lands. `mission.md` states the agent's job is "context-aware AI" that "knows each plant's full history," and the roadmap's 002 checklist (auth hand-off, identity verification, scoped client, context builder, data minimization, scoping verification) is precisely the path from "high-quality generic advice" to "Flora talking about *your* Monstera, your last watering, your balcony light."

It is also the first feature that touches anything outside the agent's own process: a third-party dependency (`supabase-py`), real user identity, and someone else's database schema. That is why security/privacy is the dominant criterion here, not throughput — a malformed read path could expose another user's plants, which violates the trust core value directly.

## Acceptance criteria

- A `/chat` call with a valid Supabase access token and a `plant_id` returns a Spanish reply that references that plant's actual data (species, recent watering, etc.), explains the reasoning, stays calm/non-judgmental, and ends with a concrete next step — the 001 persona applied to real context.
- A `/chat` call with a valid token and **no** `plant_id` returns a Spanish reply that can prioritize across the user's plants ("lo que necesita atención hoy"), using the light inventory.
- A `/chat` call **without** an `Authorization` header returns `401 {"error":{"code":"UNAUTHORIZED","message":"..."}}`.
- A `/chat` call with a **malformed** token (not a real JWT), an **expired** token, or a token with a **bad signature** returns `401 UNAUTHORIZED`.
- A `/chat` call with a `plant_id` that belongs to another user returns a reply consistent with "no plant found" / empty context for that topic — the agent never fabricates foreign data, and no foreign row is fetched (RLS verified).
- Reads are bounded: the context builder requests at most `context_max_plants` plants in light mode and at most the configured recent-entry cap per history type in deep mode (verified by `.limit()` assertions / mock call inspection).
- Context contents (journal text, plant names) are never written to logs — only row counts and durations.
- A Supabase API failure (network / 5xx / non-JSON) on a read returns `502 UPSTREAM_ERROR`; the message never contains the access token or JWT secret, and Gemini still never receives foreign data because no data was returned.
- `docs/api-contract.md` documents the `Authorization` header requirement, the optional `plant_id` request field, the `401 UNAUTHORIZED` code, and the privacy/RLS note.
- `spec/constitution/tech-stack.md` lists the new `app/auth/` and `app/supabase/` modules, the new settings (`supabase_url`, `supabase_jwt_secret`, `auth_jwt_audience`, context caps), and the new env vars; the V0.1 hard limits are explicitly marked as V0.1-scoped (Supabase and auth are now allowed in V1.0).
- `uv run pytest` passes, including new auth, context-injection, RLS-deny, data-minimization, and 502 tests; the existing `/health`, `/chat`, 422, 502, 500, off-topic, and Spanish-only tests still pass.
- `uv run ruff check` and `uv run ruff format --check` pass.

## Out of reach

Explicitly out of scope for 002; they belong to later features or the constitution:

- **Image content analysis (004).** 002 fetches only photo *metadata* (existence, count, last-taken date). Sentencing an image's bytes to Gemini vision is feature 004, so Flora cannot diagnose a leaf from a photo yet.
- **Supabase writes (003).** No confirm-and-execute flow, no watering-schedule creation, no "save this tip to the journal." 002 is read-only.
- **Web search (006).** No external lookups; Flora reasons only over the user's data plus general plant-care knowledge.
- **Streaming / dynamic statuses (005).** `/chat` stays single-shot. The context fetch happens inline before the single Gemini call, not as a streamed intermediate status.
- **Conversation persistence** (Non-Goal, restated). Context is assembled per request from Supabase; nothing about the chat itself is stored.
- **Proactive nudges** (Backlog). The light context supports a "what needs attention today" *reply*, but agent-initiated push reminders are a backlog item.
- **Refresh-token handling.** An expired access token returns `401`; the app refreshes and retries. The agent never refreshes on the client's behalf (mission: "the agent does NOT handle authentication" — it verifies).
- **A multi-plant "deep" mode.** Deep context is for exactly one `plant_id`. Bounded deep context across several plants at once is deferred until usage shapes it.
- **Schema ownership.** The Supabase tables/columns live in the app's project; 002 reads them but does not define or migrate them. Confirming the real schema is a manual prerequisite (see `users-tasks.md`) that gates the context-builder phase.
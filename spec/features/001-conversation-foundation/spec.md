# 001 - Conversation Foundation

**Status:** Planning

## What makes

This feature turns the placeholder chat from V0.1 into Brote's real conversational voice. It does not add new endpoints or persistence — `/chat` stays stateless and single-shot. What it adds is everything that makes a reply feel like it came from Brote and not a generic model.

Concretely it delivers:

- A **production system prompt** that encodes the full Brote personality from `mission.md`: relaxed, cheerful, optimistic, close to nature; speaks like a plant-loving friend; loves sharing plant curiosities; a sense of humor that never turns help into a joke; never judges or guilt-trips (never makes the user feel bad for forgetting to water); celebrates every new leaf; always briefly explains the reasoning behind a recommendation; admits uncertainty clearly and never invents answers; always ends with a concrete, actionable next step; and replies only in Spanish.
- A **plant-care scope guardrail**: the AI gracefully refuses off-topic requests in Spanish and steers the user back to plant care, handled within the single Gemini call (no separate model round-trip) so credits aren't wasted on a second classifier.
- **Spanish-only enforcement** as a hard prompt-level requirement, verifiable in tests.
- **Finalized Gemini generation config** as settings (temperature, max output tokens, safety), so the calm-friendly tone is a deliberate, tunable choice rather than a hardcoded constant.
- **Honest upstream error handling**: a Gemini API failure is surfaced as a distinct `502 UPSTREAM_ERROR` in the standard error envelope, separate from genuine internal bugs (`500 INTERNAL_ERROR`). No key or traceback ever leaks.
- An **updated API contract** in `docs/api-contract.md` reflecting the finalized `/chat` behavior and the full error-code table.
- **Tests** for the new behavior: off-topic graceful refusal, Spanish-only output for a non-Spanish prompt, persona conformance (reply contains a concrete next step; admits uncertainty when information is missing), and `502` on upstream Gemini failure.
- A **reconciled constitution**: `spec/constitution/tech-stack.md` and `spec/constitution/roadmap.md` still reference OpenAI but the running service uses Google Gemini; this feature updates those references so the constitution is internally consistent before feature code lands.

## Why

V0.1 proved the pipe works — a message reaches Gemini and a Spanish string comes back — but the reply is produced by a placeholder persona and has no guardrails. The roadmap's own 001 checklist (scope guardrail, prompt engineering, Spanish-only, contract finalization) is exactly the gap between "the pipe works" and "this feels like talking to Brote." Every later feature (002 Supabase reads, 004 images, 005 dynamic statuses, 006 web search) feeds context INTO this reply, so the voice and guardrails must be locked first.

It is also the moment to fix the OpenAI-to-Gemini staleness in the constitution, because the workflow requires every feature plan to respect `tech-stack.md`, and right now `tech-stack.md` contradicts the deployed service.

## Acceptance criteria

- A real `/chat` call with a plant-care question returns a Spanish reply that ends with a concrete next step, briefly explains its reasoning, and stays calm and non-judgmental — matching `mission.md`'s personality.
- An off-topic `/chat` request (e.g. "write me a Python function", "¿quién ganó el mundial de 1998?") is refused gracefully in Spanish and steered back to plant care, without an error response (HTTP 200 with a polite refusal `reply`).
- A `/chat` request written in English still returns a Spanish reply.
- When the user's message lacks the information needed for a confident answer, the reply says so clearly rather than inventing one.
- A Gemini API failure returns `502` with `{"error":{"code":"UPSTREAM_ERROR","message":"..."}}`; the message never contains the API key or a stack trace. Genuine internal bugs still return `500 INTERNAL_ERROR`.
- `gemini_temperature` and `gemini_max_output_tokens` are configurable via settings with documented defaults (temperature ~0.7, max_output_tokens 1024).
- `docs/api-contract.md` documents the finalized `/chat` contract and the full error-code table (`VALIDATION_ERROR` 422, `UPSTREAM_ERROR` 502, `INTERNAL_ERROR` 500).
- `spec/constitution/tech-stack.md` and `spec/constitution/roadmap.md` no longer reference OpenAI as the provider; they reflect Google Gemini (model, env var `GEMINI_API_KEY`, secret `gemini-api-key`).
- `uv run pytest` passes, including new tests for off-topic refusal, Spanish-only output, persona conformance, and `502` upstream error.
- `uv run ruff check` and `uv run ruff format --check` pass.

## Out of reach

Explicitly out of scope for 001; they belong to later features or the constitution:

- Conversation persistence / history — the agent stays per-request (Non-Goal).
- Streaming or intermediate "Revisando…" status messages (005).
- Supabase reads (002) — so the AI has **no per-user plant context** in 001. Replies are high-quality but generic plant-care advice, not personalized to the user's actual plants. This is an honest limitation acknowledged until 002 lands; the "context over generality" principle is only fully met after 002.
- Supabase writes (003) — no proposed-action / confirm-and-execute flow yet.
- Auth — `/chat` remains anonymous; no user identity, no tokens.
- Image analysis (004) and web search (006).
- A programmatic off-topic pre-filter (a separate cheap classifier call before the main call). 001 uses a prompt-based guardrail only; a pre-filter is a possible later optimization if the prompt guardrail proves too leaky.
- Multi-language support — Spanish only.
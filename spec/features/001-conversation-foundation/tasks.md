# 001 - Conversation Foundation

Phase buckets mapped from the `roadmap.md` 001 checklist. Several roadmap items (chat API contract, Gemini client, request validation, Cloud Run config) are already satisfied by V0.1; this feature fills the remaining gaps and reconciles the constitution. Items needing real Gemini keys are flagged manual.

## Phase 0 — Pre-flight & constitution reconciliation

- [x] Confirm decisions in `plan.md`: provider (Gemini), model (`gemini-3.5-flash-lite`), temperature (0.7), max output tokens (1024), guardrail mechanism (prompt-based single-call), upstream error mapping (502)
- [x] Reconcile `spec/constitution/tech-stack.md` to Gemini: env var `GEMINI_API_KEY`, model default `gemini-3.5-flash-lite`, file map (`call_gemini`), hard limits (Gemini), conventions
- [x] Reconcile `spec/constitution/roadmap.md` 001 checklist wording: "OpenAI client setup" → Gemini, "OpenAI SDK" → `google-genai`
- [ ] Confirm the `users-tasks.md` Gemini/GCP prerequisites are satisfied before the manual smoke phase (secret `gemini-api-key`, etc.)

## Phase 1 — System prompt engineering

- [x] Replace `app/agent/prompts.py` `SYSTEM_PROMPT` with the full Flora persona from `mission.md`: relaxed/cheerful/optimistic, plant-loving-friend voice, shares curiosities, humor without joking about help, never judges or guilt-trips, celebrates new leaves, explains reasoning briefly, admits uncertainty, never invents, always ends with a concrete next step, Spanish-only
- [x] Add plant-care scope guardrail to the prompt: refuse off-topic requests gracefully in Spanish and steer back to plant care (returns a normal 200 reply, not an error)
- [x] Strengthen the Spanish-only instruction and verify it handles non-Spanish user input

## Phase 2 — Generation config as settings

- [x] Add `gemini_temperature` (default 0.7) and `gemini_max_output_tokens` (default 1024) to `app/config/settings.py`
- [x] Have `app/agent/loop.py` read these from `Settings` instead of hardcoded constants
- [ ] Consider Gemini safety settings defaults; document the choice

## Phase 3 — Honest upstream errors

- [x] Introduce a typed upstream error (e.g. `UpstreamError`) raised from `call_gemini` on `google-genai` API failures
- [x] Add a handler in `app/api/errors.py` mapping it to `502 {"error":{"code":"UPSTREAM_ERROR",...}}`; never log/return the key or trace
- [x] Keep the generic handler for `500 INTERNAL_ERROR`
- [x] Wire the new handler in `app/main.py` alongside the existing exception handlers

## Phase 4 — Contract & docs

- [x] Update `docs/api-contract.md`: finalize `/chat` behavior and add the full error-code table (422 `VALIDATION_ERROR`, 502 `UPSTREAM_ERROR`, 500 `INTERNAL_ERROR`)
- [ ] Update README if it still references OpenAI (local dev pointing at a Gemini key)
- [x] Note in the contract that 001 is single-shot (no streaming — feature 005)

## Phase 5 — Tests

- [x] Test: upstream Gemini API failure → `502 UPSTREAM_ERROR` with no key or trace in the response
- [x] Test: unexpected internal exception still returns `500 INTERNAL_ERROR`
- [x] Existing tests pass: `/health`, `/chat` reply, validation errors (422)
- [x] `uv run ruff check` and `uv run ruff format --check` pass
- [ ] Manual: off-topic refusal, Spanish-only output, persona conformance (gated on real Gemini key in Phase 6)

## Phase 6 — Manual smoke (real calls, gated on Gemini key)

- [ ] Gated on: `users-tasks.md` Gemini/GCP prerequisites complete
- [ ] A few real `/chat` calls: a plant-care question, an off-topic prompt, an English prompt — sanity-check the Flora voice, the refusal, and Spanish-only
- [ ] Update `constitution/roadmap.md`: mark 001 done
# 001 - Conversation Foundation

## Approach

Lock Flora's conversational voice and guardrails onto the existing stateless `/chat` endpoint — no new routes, no persistence, no streaming. The work is small because V0.1 already laid the pipe (FastAPI → `google-genai` → Gemini → Spanish reply). 001 is mostly content (the system prompt), one behavioral guardrail (off-topic refusal), one error-honesty fix (502 vs 500), and a constitution reconciliation.

Sequenced so each phase produces something verifiable:

1. **Pre-flight & constitution reconciliation** — fix the OpenAI-to-Gemini staleness in `tech-stack.md` and `roadmap.md` so the plan respects the constitution before code changes. Confirm model/temperature/token defaults.
2. **System prompt engineering** — replace the placeholder `SYSTEM_PROMPT` with the full Brote persona from `mission.md` (personality, tone, reasoning, uncertainty, concrete next step, Spanish-only) plus the plant-care scope guardrail.
3. **Generation config as settings** — lift `temperature` / `max_output_tokens` out of `loop.py` hardcoded constants into `Settings`, with documented defaults and Gemini safety settings.
4. **Honest upstream errors** — distinguish a Gemini API failure (`502 UPSTREAM_ERROR`) from an internal bug (`500 INTERNAL_ERROR`), both in the uniform envelope, no key/trace leak.
5. **Contract & docs** — update `docs/api-contract.md` with the finalized `/chat` behavior and full error-code table; touch the README if it still names OpenAI.
6. **Tests** — off-topic refusal, Spanish-only output, persona conformance, `502` upstream; keep the Gemini client mocked in CI.
7. **Manual smoke** — a handful of real `/chat` calls with plant-care, off-topic, and non-Spanish prompts to sanity-check the voice; keep it small (real calls spend Gemini credits).

## Implementation

Files 001 touches (all already exist from V0.1; this is an increment, not scaffolding):

```
app/
├── agent/
│   ├── prompts.py        # SYSTEM_PROMPT → full Brote persona + scope guardrail (the bulk of the work)
│   └── loop.py           # call_gemini(): read temp/max_tokens from settings; raise typed upstream error
├── api/
│   ├── routes.py         # /chat: map upstream error → 502; keep 200/422/500 paths
│   └── errors.py         # add upstream handler → 502 UPSTREAM_ERROR envelope
├── config/
│   └── settings.py       # add gemini_temperature, gemini_max_output_tokens (+ optional safety) with defaults
docs/
└── api-contract.md       # finalize /chat contract + error-code table (422/502/500)
spec/constitution/
├── tech-stack.md         # OpenAI → Gemini reconciliation (data models, file map, conventions, env var)
└── roadmap.md            # OpenAI → Gemini wording in the 001 checklist
tests/
└── test_chat.py          # + off-topic refusal, Spanish-only, persona conformance, 502 upstream
```

Key flows (delta from V0.1):

- **`/chat`** — unchanged contract: `POST {"message":"..."}` → `200 {"reply":"..."}`. The only runtime change is how failures are classified.
- **Upstream error path** — `call_gemini` catches the `google-genai` client/API error specifically and raises a dedicated upstream exception (e.g. `UpstreamError`). A handler in `errors.py` (wired in `main.py` alongside the existing handlers) maps `UpstreamError` → `502 {"error":{"code":"UPSTREAM_ERROR","message":"El servicio no respondió. Inténtalo de nuevo en un momento."}}`; everything else still falls through to `500 INTERNAL_ERROR`. Neither path logs or returns the API key.
- **Off-topic guardrail** — handled inside the single Gemini call via the system prompt: the model is instructed to refuse non-plant-care requests warmly in Spanish and steer back to plants, returning a normal `200` `reply` (not an error). No second model call, so no extra credit spend.
- **Generation config** — `Settings.gemini_temperature` (default `0.7`), `Settings.gemini_max_output_tokens` (default `1024`) flow into `GenerateContentConfig`. Tunable via env for experimentation without code changes.

## Decisions

Recommended defaults, all confirmable before code touches:

- **Provider:** Google Gemini via the `google-genai` SDK — already the running service and what `AGENTS.md`/`mission.md` describe. This feature reconciles `tech-stack.md`/`roadmap.md` to match.
- **Model:** `gemini-3.5-flash-lite` (make default) — cheap and fast enough for a chatty, friendly tone; overridable via `GEMINI_MODEL`. Confirm given cost/latency appetite.
- **Temperature:** `0.7` (current) — warm and slightly varied without losing reliability; the `0.6–0.8` range is acceptable. Confirm.
- **Max output tokens:** `1024` — enough for an explained reply plus a concrete next step. Confirm.
- **Scope guardrail mechanism:** prompt-based, single-call. No separate off-topic classifier — it would double cost and latency for marginal benefit at this stage. Revisit only if the prompt guardrail proves leaky (tracked as a backlog note).
- **Upstream vs internal errors:** Gemini API failures → `502 UPSTREAM_ERROR`; unexpected internal failures → `500 INTERNAL_ERROR`. Improves on V0.1's blanket `500`, and the error envelope shape stays unchanged.
- **No streaming in 001** — single-shot only (V0.1 hard limit; streaming is feature 005).
- **Spanish-only:** enforced via the system prompt; no separate language-detection module in 001. A test asserts a Spanish reply to an English prompt; full programmatic language enforcement is deferred.

## Risks

- **Constitution staleness (highest).** `tech-stack.md` and `roadmap.md` still say OpenAI (`OPENAI_API_KEY`, `OPENAI_MODEL`, `gpt-4o-mini`, "OpenAI client setup"), but the service runs on Gemini. The workflow requires a plan to respect `tech-stack.md`, which currently contradicts reality. Mitigation: Phase 0 updates the constitution to Gemini before any feature code lands — the same pattern 000 used to populate the (then-empty) `tech-stack.md`.
- **Prompt guardrail is leaky.** A prompt-based off-topic refusal is not a hard guarantee; the model may occasionally indulge off-topic input. Mitigation: strong prompt language plus focused test cases; revisit a programmatic pre-filter later if needed (backlog).
- **No plant context in 001.** Without Supabase (002), replies are generic, which strains the "context over generality" principle. Mitigation: 001 is explicitly generic-but-on-brand; the app should set user expectations, and 002 closes the gap. Stated clearly in `spec.md` Out of reach.
- **Spanish-only not guaranteed by the model.** A non-Spanish user message could coax a non-Spanish reply. Mitigation: explicit prompt instruction plus a regression test; defer module-level language enforcement.
- **Prompt cost/latency.** A richer persona prompt increases per-request input tokens. Mitigation: keep the prompt focused; it is a `system_instruction`, amortized across the call. Revisit if cost/latency spike after 002 adds context.
- **Manual persona smoke spends credits.** CI mocks Gemini (no spend), but manual `/chat` persona checks do. Mitigation: keep the manual smoke small; prefer `gemini-2.5-flash`.
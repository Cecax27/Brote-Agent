# Mission

## What We Build

Brote-Agent is the AI backend powering the Brote plant-care mobile app. It is a Python service deployed on Google Cloud Run that exposes a REST API consumed by the React Native client.

The agent's job: make every plant-care interaction smarter through context-aware AI. It knows each plant's full history — photos, watering, fertilizations, repottings, past issues, location — and uses that context to give personalized, calm, expert-level guidance.

## Core Capabilities

- **Plant-aware chat.** Answer care questions with full context of the user's plants and their history.
- **Proactive insights.** Read plant data from Supabase and surface what needs attention today.
- **Web search.** Look up plant care information, pest identification, product recommendations.
- **Actionable advice.** Every AI response should offer the user a concrete next step.

## Principles

- **Context over generality.** Never give generic plant answers when the user's actual plant data is available.
- **Calm, never alarming.** The tone is supportive, not judgmental. Plants die sometimes — that's okay.
- **Action-oriented.** Always end with something the user can actually do.
- **Privacy-respecting.** User plant data stays in their Supabase instance. The agent only reads what it needs.
- **Serverless-first.** Stateless, fast cold starts, no long-running processes. Designed for Cloud Run.

## Boundaries

- The agent does NOT have its own database. All persistent state lives in Supabase.
- The agent does NOT serve a UI. The React Native client handles all presentation.
- The agent does NOT handle authentication. The client passes identity tokens; the agent verifies them.
- The agent does NOT replace human expertise. It augments, never overrides, the user's own judgment.

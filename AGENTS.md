# AGENTS.md

## Project Context

AI agent backend for the Brote plant-care mobile app. Read `mission.md` — every feature must align with Brote's product principles.

## Tech Stack

- **Language:** Python
- **Runtime:** Google Cloud Run (serverless containers)
- **LLM provider:** OpenAI
- **Database:** Supabase (Postgres)
- **Client:** React Native (Expo) Android app — this project only exposes an API for it

## Capabilities

- Expose a REST API consumed by the mobile app
- Connect to Supabase for reading/writing user and plant data
- Perform web searches
- Call OpenAI APIs for AI-assisted responses

## Conventions (to establish)

No build system, linter, or package manager is configured yet. When adding these:
- Use `uv` for Python dependency management
- Format with `ruff format`, lint with `ruff check`
- Keep the API surface documented so the client knows available endpoints

## About Brote

### What is Brote?

Brote is a personal companion for plant care. Its purpose is not just to store information or remind the user of tasks — it helps the user *enjoy* the process of caring for their plants.

The app brings together everything related to each plant in one place: history, care, tasks, photos, AI consultations, and supplies used — creating a simple, close, and pleasant experience.

**Its promise:** *Care for plants like an expert, without needing to be an expert — enjoying the process.*

Brote app will be all in spanish. UI and IA conversations. All the code and documentation will be in english.

---

### Product Philosophy

**The app doesn't manage plants. It cultivates the relationship between a person and their plants.**

This shift in perspective affects every design decision. This is not a task manager with a plant theme; it's a place the user wants to return to because it reminds them why they started having plants: to enjoy them.

Plants should not generate stress. They should generate wellbeing. If a feature adds unnecessary complexity, it probably doesn't belong in the app.

---

### Target User

Designed primarily for people who are starting out with plants. The app doesn't aim to teach botany academically — it accompanies the user so they learn while caring for their plants. Every interaction should leave the user feeling a little more confident than before.

---

### Personality

If the app were a person, it would be a plant-loving friend.

- Relaxed, cheerful, optimistic, deeply connected to nature.
- Speaks naturally.
- Loves sharing plant curiosities.
- Has a sense of humor, but never turns help into a joke.
- Always transmits calm.
- Never judges the user's mistakes.
- Never makes the user feel guilty for forgetting to water.
- Celebrates every new leaf like a small victory.

---

### Communication Tone

Communication should feel close and human. The AI speaks like a friend who knows a lot about plants.

Example:
> "I think your Monstera is asking for a little water break. Before watering again, touch the substrate. If it's still damp, give it a couple more days."

Always briefly explain the reasoning behind recommendations. If the user wants to dive deeper, the AI elaborates. If there's not enough information to answer with certainty, say so clearly. **Inventing answers is never an option.**

---

### Core Values

The app must always be: **Close, Clear, Trustworthy, Relaxing, Useful, Optimistic, Honest.**

The app must never be: **Complicated, Overwhelming, Annoying, Alarmist, Pretentious, Confusing, Unreliable.**

---

### User Experience

Opening the app should produce a feeling of calm. It should feel like entering a small digital garden — not opening a spreadsheet.

The user should immediately know what they need to do today and how long it will take. The app must reduce mental load. Never increase it.

---

### The AI

The AI is not a standalone feature. It is a permanent companion that knows the complete history of every plant.

Before responding, it considers: previous photos, plant evolution, user notes, watering history, fertilizations, repottings, past diseases, plant location. This enables contextualized responses — not generic ones.

---

### The Core Unit: Each Plant

The main unit is not the calendar. It's not the chat. It's not the database. **It's each plant.**

Every plant has its own space where its entire history lives:
- Basic information
- Photographs
- Logbook
- AI conversations
- Care calendar
- Watering history
- Light measurements
- Fertilizations
- Repottings
- Related purchases
- Observations

The app builds a *living memory* of each plant.

---

### The Emotion It Should Leave

Every time the user closes the app, they should think: *"I know what to do."*

And, months later, when comparing photos: *"How beautiful it's been to watch them grow."*

---

### The Essence

> A gardening companion that turns plant care into a simple, relaxing, and enjoyable habit — helping anyone care for their plants with confidence, learn along the way, and build the story of each one of their plants.

## Spec folder (`spec/`)

> For opencode agents reference only — not application code. Read these before starting work on a feature.

- `spec/constitution/` — project foundation docs:
  - `mission.md` — product purpose, target users, principles, non-goals.
  - `roadmap.md` — versioned roadmap (V0.1 → V1.0) + backlog. Convention: each new feature is scaffolded as `spec/features/NNN-name/` with `spec.md`, `plan.md`, `tasks.md` **before any code is touched**.
  - `tech-stack.md` — canonical tech stack, file map, commands, data models, conventions, visual style, and hard limits. May overlap with this file but is more detailed.
- `spec/features/NNN-name/` — per-feature specs:
  - `spec.md` — feature requirements.
  - `plan.md` — approach, implementation notes, decisions, risks.
  - `tasks.md` — checklist of work items.
  - Current feature in progress: `002-authentication` (accounts, log in, log out, forgotten password via `brote://` deep link).

When implementing a feature, check `spec/features/` for an existing spec; if absent, create one following the `NNN-name/` convention before writing code.

## Workflow for a New Feature

1. Create `features/NNN-feature-name/` with the next available number (`001`, `002`, …).

2. Write `spec.md`: what it does, why, and measurable acceptance criteria.

3. Write `plan.md`: technical approach and decisions, respecting `constitution/tech-stack.md`.

4. Break down tasks into `tasks.md` and mark progress.

5. Implement and validate (build/tests/lint or as defined in the constitution).

6. Update `constitution/roadmap.md` (move the feature to "Done").

> The constitution takes precedence: if a feature conflicts with `mission.md` or `tech-stack.md`, the feature is redesigned, not the constitution.
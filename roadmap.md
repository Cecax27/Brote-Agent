# Roadmap

## V0.1 Base — "The First Watering"

Each feature below has its own `spec/features/NNN-name/` with `spec.md`, `plan.md`, and `tasks.md`.

### 001-supabase-foundation
What: Everything needed to talk to the database.
- [x] Install `@supabase/supabase-js` + `@react-native-async-storage/async-storage`
- [x] Create Supabase client with env vars (`EXPO_PUBLIC_SUPABASE_URL`, `EXPO_PUBLIC_SUPABASE_ANON_KEY`)
- [x] Database migration — `plants` table (id, user_id, name, species, location, photo_url, notes, created_at, updated_at)
- [x] Database migration — `journal_entries` table (id, plant_id, user_id, type, content, photo_url, created_at, updated_at)
- [x] Row Level Security policies — users can only access their own data
- [x] Generate TypeScript types from database schema

### 002-authentication
What: Users can create accounts, log in, and reset their password via deep link.
- [x] Auth context + provider (session, user, signIn, signUp, signOut, resetPassword)
- [x] Supabase Auth listeners (`onAuthStateChange`) for session persistence
- [x] Basic components — from mockups, create reusable basic components 
- [x] Sign up screen — email, password, confirm password, display name
- [x] Log in screen — email + password
- [x] Forgot password screen — request reset link
- [x] Reset password screen — new password via deep link (scheme: `brote`)
- [x] Auth guard — redirect unauthenticated users to log in
- [x] Logout
- [x] Form validation + error messages (Spanish)

### 003-app-foundation
What: The app looks and feels like Brote. Navigation structure, theme, and the home screen.
- [x] Load fonts — `Fraunces` + `Inter` (per visual guide)
- [x] Design tokens — colors, spacing, typography scale, border radii, shadows
- [x] Root layout with (auth) and (app) route groups
- [x] Home screen — greeting, plant summary, "What does my garden need today?"
- [x] Plant detail screen (placeholder/scaffold)
- [x] Shared UI components — Button, Input, Card, Avatar, EmptyState, LoadingSkeleton
- [x] Watercolor illustration placeholders
- [x] Loading states and empty states for all screens

### 004-plant-management
What: Users can add, view, edit, and delete their plants. Photos included.
- [x] Create plant screen — name (required), species, location, photo (camera + gallery), notes
- [x] Image picker integration (expo-image-picker)
- [x] Plant list — rendered on home screen, sorted by newest first
- [x] Plant card component — photo, name, species, quick status
- [x] Plant detail screen — full info, photo, quick actions (journal, edit, delete, photo timeline)
- [x] Photo timeline view — per-plant photo history grid ("watch them grow")
- [x] Edit plant screen — pre-filled form
- [x] Delete plant — confirmation dialog, cascades to journal entries
- [x] Form validation (Spanish error messages)

### 005-journal-entries
What: Each plant has a chronological logbook of care events.
- [x] Add journal entry — type (watering, fertilizing, repotting, pruning, observation), content, optional photo
- [x] Journal entry list — grouped by month, rendered on plant detail screen
- [x] Journal entry card component
- [x] Edit journal entry
- [x] Delete journal entry — confirmation dialog
- [x] Empty state — "Aún no hay entradas en el diario"

## V0.2 Tools

### 006-watering-schedule
What: Per-plant watering schedule with calendar view and local notifications.
- [x] Database migration — `watering_schedules` table (plant_id FK, frequency_days, last_watered_at, next_due_at, notify_time, active)
- [x] Create watering schedule per plant — frequency, reminder time, active toggle
- [x] Watering calendar view — upcoming waterings for the week/month
- [x] Local scheduled notifications via `expo-notifications` on due dates
- [x] "Water now" quick action — logs a watering journal entry and advances next_due_at
- [x] Home screen integration — "Plants that need watering today" section
- [x] Edit / delete / pause watering schedule

### 007-light-tool
What: Measure ambient light via camera lux estimation and get placement advice.
- [x] Camera lux measurement — compute average luminance from a camera frame
- [x] Calibration step — user points camera at direct sun, then full shadow, to derive device-relative lux scale
- [x] Light reading per plant — record lux value and optionally associate with a plant
- [x] Light history per plant — chart or list of past readings
- [x] Placement advice — compare reading to the plant species' light need (low / medium / bright / direct)
- [x] Light profile field on `plants` — expected light level set during create / edit
- [x] Database migration — `light_measurements` table (plant_id?, lux, device_lux, created_at)

## V0.3 AI

All AI features are backend-proxied through Supabase Edge Functions. The app never holds an AI provider key — keys live in Supabase secrets. Start with OpenAI; swap providers server-side without app updates.

### 008-ai-foundation
What: AI infrastructure, Flora avatar, chat UI, and message persistence.
- [ ] Supabase Edge Function — proxy to OpenAI API, authenticated via Supabase session
- [ ] Database migration — `ai_conversations` table (id, user_id, plant_id?, title, created_at)
- [ ] Database migration — `ai_messages` table (id, conversation_id, role, content, photo_url?, created_at)
- [ ] Flora AI companion avatar — visual identity per brote-visual-guide
- [ ] Chat UI — message bubbles, typing indicator, plant context header
- [ ] Chat list — per-plant conversations, starting a new chat
- [ ] Context builder — gathers plant info + recent journal entries to inject into the system prompt
- [ ] Message persistence — save every message, resume conversations
- [ ] Loading / empty / error states

### 009-plant-identification
What: Identify plant species from a photo using the vision model.
- [ ] "Identify plant" action on create-plant screen and camera view
- [ ] Vision API integration via Edge Function — send photo, receive species suggestions
- [ ] Species suggestion UI — confirm suggested species or pick / type manually
- [ ] Confidence indicator — show how confident the AI is
- [ ] Auto-fill species + care hints on confirmation

### 010-ai-consultation
What: Symptom diagnosis, care advice, and general plant chat — always ending with a concrete action.
- [ ] "Ask about this plant" button on plant detail screen
- [ ] System prompt engineering — AI has access to plant info, journal history, past photos, light history, and watering schedule
- [ ] Symptom analysis — user sends photo + description, AI diagnoses and recommends action
- [ ] Concrete action ending — every response includes a next-step the user can take
- [ ] V1.0 enrichment — extend context builder to include inventory items (supplies used, fertilizer references)

## V0.4 Inventory

### 011-inventory-management
What: Track supplies — name, category, brand, store, price, quantity, purchase date, receipt photo.
- [ ] Database migration — `inventory_items` table (id, user_id, name, category, brand, store, price, quantity, unit, purchase_date, notes, receipt_photo_url, created_at, updated_at)
- [ ] Database migration — `inventory_item_plants` join table (item_id FK, plant_id FK)
- [ ] Database migration — nullable `journal_entries.inventory_item_id` FK to link fertilizing entries to a specific supply
- [ ] Create inventory item — form with name, category, brand, store, price, quantity, unit, purchase date, notes, optional receipt photo
- [ ] Inventory list — searchable, filterable by category
- [ ] Inventory detail — full item info, linked plants, linked journal entries
- [ ] Edit / delete inventory item
- [ ] Link item to journal entry — when logging a fertilizing entry, select which supply was used
- [ ] Link item to one or more plants

## V1.0 — "The Garden in Bloom"

### 012-onboarding
What: First-run experience that introduces Flora, requests permissions, and hooks the user.
- [ ] Welcome / intro screens — Flora introduction, app personality ("Your plant companion")
- [ ] Permission request screen — camera (photos + light tool) and notifications (watering reminders)
- [ ] First plant creation prompt or skip
- [ ] `eas.json` — development, preview, and production build profiles

### 013-settings-profile
What: User preferences and account management.
- [ ] Profile screen — display name, email, avatar
- [ ] Notification preferences — watering reminder time, quiet hours, per-plant toggle
- [ ] Data export — export plants + journal entries (CSV/JSON)
- [ ] Sign out — confirmation dialog
- [ ] Delete account — confirmation, cascading data deletion

### 014-health-indicator
What: Per-plant health status derived from care adherence, journal patterns, and photo recency.
- [ ] Database migration — `plants.health_status` column (enum: good, needs_attention, critical) or computed via DB function
- [ ] Health calculation logic — watering adherence rate, time since last fertilizing / repotting, photo recency
- [ ] Health badge on plant card and plant detail — color-coded visual indicator
- [ ] Health tips — AI-generated suggestions when status is needs_attention or critical

## Backlog / Ideas

- Native ambient light sensor (V2.0)
- Offline read cache for plants and journal
- Automated import of expenses from receipts with AI
- Automatic category rules (e.g. "amazon" → online purchase)
- Advanced photo comparison timeline
- Oauth login with Google and Facebook

> Each new feature is created as `spec/features/NNN-name/` with `spec.md`, `plan.md`, and `tasks.md` before any code is touched.

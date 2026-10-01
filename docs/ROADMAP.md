# CatsChannel Roadmap

## Mission

Create a maintainable Telegram cat-video reply-chain platform.

The project is a Social domain that models submissions, threads, moderation decisions, and Telegram publication. It is not a port of `nevermore/src/post.py`. «دیوار ناشناس» (TelegramBot-FirstGen `35eea1b8`) is the behavioral reference: deep-link entry and Telegram-native replies stay; the all-in-one module does not.

## Phase 0 — Foundation

Goals:

- reproducible Python environment
- CI baseline
- configuration management
- logging policy
- project structure

Deliverables:

- Python 3.13
- uv lockfile
- aiogram 3 application factory
- `src/social/` skeleton (handlers, service, repository, states, callbacks, schemas)
- tests running offline

## Phase 1 — Telegram Core

Build:

- bot startup lifecycle
- routers
- dependency injection boundaries
- error middleware
- callback/deep-link conventions in one module

Contract:

- public buttons are URL-only: `/start cat_<opaque-token>`
- `catreply:<internal-id>`
- `catmod:approve:<submission-id>`
- `catmod:reject:<submission-id>`
- or aiogram 3 typed `CallbackData` with the same fields
- `url` and `callback_data` are never set together

Non-goals:

- business features
- database coupling inside handlers
- hard-coded channel or bot usernames

Test FSM reset on purpose: a new `/start` during an open submission replaces that state.

## Phase 2 — Cat Submission Domain

Introduce:

- CatVideoSubmission entity
- repository layer
- TelegramMessageRef value object (`chat_id`, `message_id`)
- media metadata (`telegram_file_id`, `telegram_file_unique_id`)
- status and created_at

Required behavior:

- receive video
- validate input
- persist submission (`id`, `thread_id`)
- publish through the Telegram client
- persist the returned TelegramMessageRef
- acknowledge the user

That sequence is one awaited service call. Async repository only. No fire-and-forget publish.

## Phase 3 — Reply Chain

Implement:

- parent/child relationships (`parent_id` → internal `id`)
- thread identity (`thread_id`)
- Telegram reply projection (`reply_to` the parent's published TelegramMessageRef)
- private submission flow via the phase 1 deep link
- FSM state that stores internal ids only

Database truth:

internal IDs define relationships.

Telegram IDs are external references:

(chat_id, message_id)

Root posts and replies share one publisher.

## Phase 4 — Moderation

Add:

- moderation queue as an explicit status
- approve/reject callbacks from phase 1
- audit records (`ModerationDecision`)
- moderator message stored as TelegramMessageRef
- moderation chat id from configuration
- abuse controls

The moderation chat is not the thread. Do not model the queue on `@AfsarieCh`.

## Phase 5 — Production Hardening

Add:

- PostgreSQL deployment
- Redis where distributed state is required
- metrics
- backups
- operational documentation

## Architecture rule

Handlers translate Telegram events.
Services own decisions.
Repositories own persistence.
Telegram clients own Telegram API details.

## Reconciliation

The phase order is the existing issue map (foundation, Telegram core, submission, reply chain, moderation, production). Nine open GitHub issues could not be read in this environment (HTTP 403). Nothing in the in-repo map contradicts the inspection except the old top-level `src/cats/` and `src/moderation/` split; Social replaces that split. See `docs/ARCHITECTURE.md`.

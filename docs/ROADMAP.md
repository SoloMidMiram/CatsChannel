# CatsChannel Roadmap

## Mission

Create a maintainable Telegram cat-video reply-chain platform.

The project is not a script that forwards videos. It is a domain system that models submissions, threads, moderation decisions, and Telegram publication.

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
- tests running offline

## Phase 1 — Telegram Core

Build:

- bot startup lifecycle
- routers
- dependency injection boundaries
- error middleware
- callback/deep-link conventions

Non-goals:

- business features
- database coupling

## Phase 2 — Cat Submission Domain

Introduce:

- CatVideoSubmission entity
- repository layer
- TelegramMessageRef value object
- media metadata storage

Required behavior:

- receive video
- validate input
- persist submission
- publish safely

## Phase 3 — Reply Chain

Implement:

- parent/child relationships
- thread identity
- Telegram reply projection
- private submission flow

Database truth:

internal IDs define relationships.

Telegram IDs are external references:

(chat_id, message_id)

## Phase 4 — Moderation

Add:

- moderation queue
- approve/reject callbacks
- audit records
- abuse controls

## Phase 5 — Production Hardening

Add:

- PostgreSQL deployment
- Redis where needed
- metrics
- backups
- operational documentation

## Architecture rule

Handlers translate Telegram events.
Services own decisions.
Repositories own persistence.
Telegram adapters own Telegram API details.

# CatsChannel Roadmap

## Verified status - 2026-11-02

Merged main: 54e88b0ec80ee0538c5b9cf673c2c96d73cd0dff. Foundations,
intake and reply domain #2-#6 are complete (#5 closed via PR #28).
Durable publishing (#29), approve-only review (#36), reply-entry concurrency
(#37) and hosted metadata reuse (#38) are implemented.

The November 1 receipt in [open PR #39](https://github.com/SoloMidMiram/CatsChannel/pull/39)
records private review, actual admin approval, one exact-parent publication and
its reply button. This is bounded private acceptance, not public readiness.
#7 remains open for navigation interaction, submitter acknowledgement and recovery
acceptance. #8 next: audited rejection, then enforced isolation, startup safeguards
and complete moderation recovery. #9 retains sustained operational qualification.
PostgreSQL backend and CI already exist; public deployment remains unqualified.
Redis is deferred until measured need. Discovery #17-#22 and optional tools #35
remain independent. Phase lists below describe scope, not entirely absent work.

See [reconciliation](evidence/post-pilot-reconciliation-2026-11-02.md).

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

- Python 3.11 runtime and CI baseline, with a future 3.13 migration rehearsal
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

## GitHub execution board

The work is tracked as one coordinating epic plus small, independently verifiable child issues:

- [Epic #1 — CatsChannel foundation and cat-video reply-chain platform](https://github.com/SoloMidMiram/CatsChannel/issues/1)
- [CATS-001 — Bootstrap Python/uv/CI foundation (#2)](https://github.com/SoloMidMiram/CatsChannel/issues/2)
- [CATS-002 — Implement aiogram application core (#3)](https://github.com/SoloMidMiram/CatsChannel/issues/3)
- [CATS-003 — Create persistence boundaries (#4)](https://github.com/SoloMidMiram/CatsChannel/issues/4)
- [CATS-004 — Build cat submission workflow (#5)](https://github.com/SoloMidMiram/CatsChannel/issues/5)
- [CATS-005 — Implement reply-chain model (#6)](https://github.com/SoloMidMiram/CatsChannel/issues/6)
- [CATS-006 — Add Telegram publishing adapter (#7)](https://github.com/SoloMidMiram/CatsChannel/issues/7)
- [CATS-007 — Add moderation workflow (#8)](https://github.com/SoloMidMiram/CatsChannel/issues/8)
- [CATS-008 — Production hardening (#9)](https://github.com/SoloMidMiram/CatsChannel/issues/9)

# Status

Current state: media, aiogram core (#3), persistence (#4), source-aware submission
foundation (PR #16), and reply-chain domain (#6, PR #24) are merged. Python 3.11
bootstrap acceptance (#2) is complete. Issue #5 remains open for bot intake.

Owner review retained separate automatic source chains, but exposed a bounded #6
follow-up: current provider matching rejects Telegram-uploaded replies under
YouTube-source posts. Provenance and authorized placement must be separated before
intake. `/post`, modular intake routers and pilot regression expansion remain
planned in [BOT_POSTING_PLAN.md](BOT_POSTING_PLAN.md), not implemented features.

Completed:

- environment definition
- dependency baseline
- roadmap
- architecture boundaries
- CI skeleton
- Python 3.11 runtime and CI baseline
- configuration template and YouTube probe/download example
- explicit Telegram publish command for a private test workflow
- shared CLI/Telegram media acquisition and validation service
- immutable source cookies and disposable extractor copies
- owned subprocess cancellation and bounded termination
- verified cache reuse and atomic media-library publication
- explicit secret-safe YouTube proxy configuration
- structured CLI error envelopes
- async SQLAlchemy repository and unit-of-work contracts
- stable source-thread, post, submission, and Telegram projection schema
- initial Alembic migration with SQLite tests and PostgreSQL configuration
- validated local-library and Telegram-native submission contracts
- trusted source resolution with explicit unresolved-source selection
- durable one-use Telegram media handoffs and ambiguous-commit reconciliation
- source metadata, validation evidence, and bounded provenance persistence
- durable placement intents and hashed, reusable, revocable reply tokens
- root, normal append, exact-parent/nested branch decisions with optimistic tail updates
- application-local thread serialization and rollback without orphan posts
- database-backed opaque reply entry through the existing dispatcher/FSM contract

The media, aiogram-core, persistence, and source-aware submission foundations are
offline-complete. Private-channel Telegram publication remains a separate
authorized smoke test. Aiogram submission UX, publishing, and moderation
remain separate phases so transport behavior does
not become coupled to storage.

Logical graph finalization is implemented. The largest remaining functional gap
is bot integration: authenticated media intake, explicit source/parent selection,
moderation and durable delivery are not an end-to-end product flow yet.
The existing `/download` and manual `/publish` commands are pilot utilities.
Issue #5 now tracks intake, #7 durable delivery and #8 moderation. Their acceptance
requires real dispatcher/service integration with fake transport, followed by an
authorized live pilot. See [PUBLICATION_CONTRACT.md](PUBLICATION_CONTRACT.md) for
the logical-tail versus confirmed-delivery contract and unknown-send recovery.
See QUICKSTART.md for setup and upgrade phases.

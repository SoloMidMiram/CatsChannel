# Status

Current state: merged media/aiogram foundation plus persistence and source-aware
submission foundations.

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

The media, aiogram-core, persistence, and source-aware submission foundations are
offline-complete. Private-channel Telegram publication remains a separate
authorized smoke test. Aiogram submission UX, publishing, moderation, and
reply-chain product workflows remain separate phases so transport behavior does
not become coupled to storage.

The sample is not the full submission UI, moderation, publishing, or reply-chain
implementation. Live service validation remains a separate smoke-test step.
See QUICKSTART.md for setup and upgrade phases.

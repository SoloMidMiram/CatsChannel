# Test Strategy

Unit:
- services
- deterministic error policies and logging sanitation
- process and Telethon lifecycle ownership

Integration:
- aiogram `Dispatcher.feed_update()` with a mocked Bot API session
- middleware order, dependency injection, private/admin filters, and error routing
- validated-library-only upload and the single active media task gate

Contract:
- current `/start`, `/help`, `/probe`, `/download`, and `/publish` behavior
- cancellation propagation and failed error-response containment
- correlation ID, operation, duration, outcome, and safe error category logging
- async unit-of-work commit/rollback behavior
- stable source identity across display-name changes
- interleaved logical threads in one destination chat
- unique complete Telegram coordinates and source-media duplicate detection
- thread membership and optimistic tail-update conflicts
- initial Alembic migration parity with the SQLAlchemy schema
- validated local-library and Telegram-native submission inputs
- verified versus manually selected source identity and mutable display snapshots
- durable handoff binding, expiry, replay rejection, atomic consumption, and
  explicit ambiguous-commit reconciliation
- rollback on invalid identity, duplicate media, and repository/commit failures

Future contract suites add end-to-end reply-chain behavior and moderation lifecycle.

The dispatcher suite is the offline application pilot. A live private-channel
pilot is tracked separately and must not be simulated by weakening offline tests.

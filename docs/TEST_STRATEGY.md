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
- reply chain behavior
- moderation lifecycle

The dispatcher suite is the offline application pilot. A live private-channel
pilot is tracked separately and must not be simulated by weakening offline tests.

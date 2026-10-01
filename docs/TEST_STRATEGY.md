# Test Strategy

Unit:

- services (submit, reply, approve, reject)
- repositories (thread_id, parent_id, TelegramMessageRef round-trip)
- callback and deep-link parsing in `callbacks.py`

Integration:

- Telegram client (publish uses reply_to the parent ref)
- async persistence

Contract:

- reply chain behavior: domain ids first, Telegram projection second
- awaited publish then reference write (no background task)
- moderation lifecycle: reject does not publish; approve does
- URL-only public buttons
- `/start` during an open submission resets state deliberately

Fixtures do not require the legacy `sqlalchemy.util.preloaded.orm` import.

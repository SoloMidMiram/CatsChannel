# Bootstrap TODO

Completed:

- generated and validated `uv.lock`
- Python 3.11 baseline with a Python 3.13 compatibility gate
- runnable admin-only bot and YouTube integration spike
- offline configuration, downloader and safety tests
- shared CLI/Telegram acquisition service and validated media library
- bounded Windows/POSIX subprocess ownership and cancellation cleanup
- async persistence repositories, unit of work, and initial Alembic migration
- source-aware validated submission service and durable one-use media handoff

Next:

- complete the remaining aiogram deep-link, callback/FSM, and lifecycle criteria
- implement Telegram publishing and reply-chain behavior
- add the moderation domain model and workflow
- run live smoke tests against a private Telegram test channel and an approved video

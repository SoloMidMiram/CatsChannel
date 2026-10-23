# Bot API startup recovery and diagnostic validation

Date: 2026-10-22

Current code was inspected in the `feat/bot-api-transport-pilot` worktree at
base revision `525faac`. Aiogram calls its cached `Bot.me()` before entering its
existing `getUpdates` polling/backoff loop. The application now warms that cache
inside the owned lifecycle with a configurable bound of three attempts and a
linear delay. Recovery catches only `TelegramNetworkError` and `TimeoutError`;
cancellation and non-network failures propagate immediately.

Safe lifecycle diagnostics map only known `GetMe` and `GetUpdates` method types
to allowlisted phase names. Retry and final-failure records include integer
attempt counts but retain neither exception messages nor request data.

The transport remains single-attempt. The recovery helper invokes only the
read-only identity operation and does not wrap publication/file sends. Existing
durable publication behavior continues to place timeouts and connection failures
in `unknown` for explicit reconciliation, with regression assertions that the
transport send count remains one.

Validation on WSL Python 3.11 used `TMPDIR=/tmp` because mounted-drive pytest
capture is unreliable without it:

- Focused lifecycle, transport, and publication suite: 74 passed, 24 skipped.
- Full suite: 445 passed, 61 skipped.
- Ruff lint: passed.
- Ruff format check: 146 files already formatted.
- Python byte compilation and `git diff --check`: passed.

After validation, one live read-only Bot API preflight passed through the configured
HTTP proxy: identity, absent webhook, private destination access, administrator
membership, post/edit permissions, and polling readiness were all confirmed. It
reported one pending update. Polling was deliberately not started because consuming
that update separately could break the already-correlated `/post` and downloader
video handoff.

No live Telegram message or publication was sent during this implementation and
validation. The earlier correlated downloader response remains unreplayed.

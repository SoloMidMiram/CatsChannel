# Bot file timeout and live intake hardening

Date: 2026-10-22

With one real aiogram poller running, the authorized user sent `/post` once. The
poller handled the command successfully, Telethon selected the existing pilot
source, and exactly one reconciled retry forward was confirmed from the stored
downloader response. No source URL was resent and no publication was attempted.

The intake then failed after 30.6 seconds with code `timeout`; the pilot database
remained empty. Inspection confirmed that aiogram's `Bot.download()` defaults to a
separate 30-second timeout and does not inherit the configured session request
budget. The adapter now passes `BOT_API_FILE_TIMEOUT_SECONDS`, default 180 seconds
with a validated 30–600 range. A regression verifies the exact download argument.

The same live failure exposed a logging mismatch: the detailed failure record used
`timeout`, while the operation completion record used `internal_error` because
outer middleware logged before the router error observer. Trusted application and
domain errors are now classified before completion logging; untrusted external
exceptions still become `internal_error`. A regression verifies matching timeout
categories without leaking file identifiers.

A later restart exhausted all three bounded identity attempts. Its lifecycle log
correctly used `bot_api_network`, but the CLI summary used `internal_error`; the
CLI now preserves the safe Bot API classification and method phase. The current
poller subsequently started and remains alive with the corrected code. A prior
`/post` was cancelled during shutdown and has no prompt, so one fresh user command
is required before another explicit forward.

Validation: 449 passed, 61 skipped; Ruff lint/format, byte compilation, and
whitespace checks passed. The database still contains zero submissions, posts,
and publications.

# PR #30 live-hardening synchronization

Date: 2026-10-22

The 21 tracked live-pilot hardening files were reviewed, formatted, committed as
`5e144baa848b94e9fe6d7d45502486c1f324b52a`, and pushed to
`feat/bot-api-transport-pilot`. No ignored runtime database, Telegram session,
pilot log, local environment profile, or credential material was added.

The commit adds bounded read-only Bot API startup recovery, explicit file-transfer
timeouts, precise safe phases and CLI classification, Telethon terminal-future
cleanup, reviewed Telegram-native provenance, and correlated intake/publication
operation records. It retains PR #29's publication service and does not introduce
another sender or automatic publication retry.

`docs/BOT_API_TRANSPORT.md` now reflects the successful private pilot, the two
observed full-decode intake timings, bounded restart exhaustion/recovery, and the
explicit boundary that Issue #8 moderation remains unfinished. Stale claims that
the private pilot was blocked and the database empty were removed.

PR #30 remains an open draft stacked on PR #29. Its title is now `fix: harden Bot
API recovery and private-pilot diagnostics`; its body describes the implementation,
safety boundaries, local verification, live evidence, and remaining moderation and
supervision limitations.

Local WSL Python 3.11 verification at the committed tree reports 451 passed and 61
skipped. Ruff lint and format, compileall, and Git whitespace checks pass. GitHub
Actions run `39783894037` passed all three exact-head jobs: Ubuntu, Windows, and
PostgreSQL. The local branch and remote head both resolve to `5e144baa` and the
worktree is clean.

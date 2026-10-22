# Live forwarded-intake retry and connection containment

Date: 2026-10-22

The previously requested downloader-bot media was reconciled from Telegram
history. Its original request, downloader response, `/post`, and one confirmed
forward are represented by exact message IDs in the ignored runtime state. The
first forward produced a classified Bot API file-transfer timeout and the pilot
database remained empty: zero submissions, logical posts, and publications.
This proves no durable intake occurred and permits one explicit user-requested
retry; it does not permit an automatic send loop.

The adapter output exposed a separate provenance-schema mismatch before durable
intake. The adapter now emits the existing reviewed `telegram_native` media
schema, with a real adapter-to-durable-intake regression. That correction and the
Bot API startup recovery changes were present for the retry.

The coordinated retry performed no send. Its first read-only Bot API preflight
failed at `getMe`. A corrected harness allowed that specific diagnostic snapshot
failure to defer to the application's bounded startup recovery, but Telethon then
failed its initial MTProto connection before polling began. Read-only diagnostics
subsequently found:

- configured Telethon SOCKS route: connection closed during startup and classified
  as `telegram_connect`;
- configured Bot API HTTP route: `getMe` failed as `bot_api_network`;
- explicit direct comparison: both MTProto and Bot API routes failed.

No polling process remains. A newly sent `/post`, if present, was not consumed by
these attempts, and no retry video or publication was sent.

The MTProto failure also revealed an unretrieved Telethon terminal future after a
failed reconnect. Middleware cleanup now owns/retrieves the public disconnected
future without exposing its exception. A deterministic regression reproduces the
failed connection and confirms one retrieval. Repeating the live diagnostic still
reported the route failure, but no longer emitted the unretrieved-future traceback.

Validation on WSL Python 3.11:

- focused connection/downloader/lifecycle/media-adapter suite: 90 passed;
- full suite: 447 passed, 61 skipped;
- Ruff lint and formatting, byte compilation, and whitespace checks: passed.

The runtime remains safely resumable from the stored correlation after Telegram
connectivity changes. The next attempt must not resend the source link and must
forward the stored downloader response at most once after a fresh `/post`.

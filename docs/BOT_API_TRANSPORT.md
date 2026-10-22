# Bot API transport and private pilot readiness

This follow-up is based on PR #29 head
`72b7cc19c10d33c40c95b317322a30141296d235`. Publication behavior, logical placement,
and the newer reconciliation-destination guard are unchanged.

## Explicit routes

All production Bot construction uses `bot/transport.py`: polling/application,
publication/file operations, read-only preflight, and the operator recovery tool.
The same aiogram session carries these Bot API requests. Injected test Bots retain
their own sessions. There is no automatic direct fallback or media-send retry.

- `BOT_API_PROXY`: aiogram Bot API route; optional HTTP or SOCKS origin with an
  explicit port. Credentials, query/fragment and non-root paths are rejected.
- `BOT_API_TIMEOUT_SECONDS`: bounded request timeout, default 60, range 5–180.
  aiogram manages its normal additional long-poll budget separately.
- `BOT_API_FILE_TIMEOUT_SECONDS`: Bot API file-download timeout, default 180,
  range 30–600. This is explicit because aiogram otherwise uses 30 seconds for
  `Bot.download()`, independently of the session timeout.
- `BOT_API_STARTUP_ATTEMPTS`: bounded read-only `getMe` attempts, default 3,
  range 1–10. Only Bot API network/time-out failures are retried.
- `BOT_API_STARTUP_BACKOFF_SECONDS`: linear delay between those attempts,
  default 1 second, range 0–30.
- `TELEGRAM_PROXY`: separate Telethon/MTProto route; never implicitly reused.
- `YOUTUBE_PROXY`: separate yt-dlp route; never implicitly reused.

`aiohttp-socks` is an explicit base dependency. SOCKS5h/SOCKS4a aliases normalize
to the connector's base schemes while aiogram sets remote DNS (`rdns=True`).
SOCKS connector failures are normalized centrally to a safe `TelegramNetworkError`;
these exceptions are not subclasses of `aiohttp.ClientError`. The application warms
aiogram's cached identity with the bounded policy above, after which aiogram's normal
`getUpdates` backoff owns polling recovery. Logs identify only the allowlisted
`bot_api_get_me` or `bot_api_get_updates` phase and attempt counts. Error messages do
not copy token-bearing URLs or proxy exception text. No TLS verification is disabled.
Publication/file sends remain single-attempt; an ambiguous send is recorded for
reconciliation and is never blindly retried by this startup policy.

## Read-only preflight

```bash
uv sync --locked --all-extras
uv run --frozen cats-channel --bot-diagnose
```

This explicitly performs `getMe`, `getWebhookInfo`, `getChat`, and `getChatMember`.
It reports safe readiness flags, the failing phase, webhook presence, and channel
posting/editing permissions where available. It never prints the bot token,
webhook URL, private destination coordinates, API payloads, or exception messages.
It never deletes a webhook, consumes updates, starts polling, or sends a message.
Cancellation propagates after owned session cleanup. The complete diagnostic has
the configured timeout budget. `--doctor` remains offline.

`status=ready` means the configured channel/pipeline passes the checks;
`private_pilot_ready=true` additionally requires a channel without a public
username. For the first pilot, require that flag and explicit selection of the
private Telegram destination. `getChat` rejection does not prove whether an ID
is wrong or bot membership is missing. Correct the destination/membership first.
If a webhook is active, resolve its ownership before switching to polling;
diagnosis deliberately leaves it unchanged.

## Private pilot profile

Use an ignored local `.env`, not committed secrets. The configured `CHANNEL_ID`
must refer to the explicitly selected private test channel where the bot can post.
Do not substitute the public channel. Example non-secret settings:

```dotenv
BOT_API_PROXY=socks5h://127.0.0.1:10808
BOT_API_TIMEOUT_SECONDS=60
BOT_API_FILE_TIMEOUT_SECONDS=180
BOT_API_STARTUP_ATTEMPTS=3
BOT_API_STARTUP_BACKOFF_SECONDS=1
REPLY_ENTRIES_ENABLED=true
MEDIA_BACKEND=yt_dlp
YOUTUBE_PROXY=socks5h://127.0.0.1:10808
DOWNLOAD_DIR=.runtime/pilot-downloads
DATABASE_URL=sqlite+aiosqlite:///.runtime/pilot.sqlite3
```

Create `.runtime` before using this isolated database. Set `YOUTUBE_COOKIE_FILE`
to an existing OS-native Netscape export path if needed. A Windows `C:\...` path
must be mapped explicitly to `/mnt/c/...` for WSL; do not assume path strings are
portable. The application continues to reject missing configured cookie files,
and yt-dlp receives only a disposable working copy. Do not manufacture a Telethon
session or silently fall back between acquisition backends. Selecting yt-dlp is
an explicit local profile choice.

```bash
uv run --frozen alembic upgrade head
uv run --frozen alembic current
uv run --frozen cats-channel --bot-diagnose
# Only after private destination and permissions pass, run one owned polling process:
uv run --frozen cats-channel --bot
```

From the configured admin's private Telegram chat: `/post`, one selected video
URL, then `/pilot_publish <submission-id>`. Inspect the confirmed channel message
and exact-post reply button. Stop and restart the same process/database, repeat
the confirmed request, and verify no duplicate media. Do not induce an ambiguous
live send as a recovery test. Unknown outcomes use the existing explicit operator
reconciliation policy. A real authenticated command pilot remains separate from
the offline dispatcher tests; never fabricate inbound admin updates as live proof.

## Evidence — 2026-10-22

Local Python 3.11 checks:

| Gate | Result |
| --- | --- |
| WSL `uv run --frozen pytest --capture=sys -q` | 451 passed, 61 skipped |
| `uv run --frozen ruff check .` | Passed |
| `uv run --frozen ruff format --check .` | Passed, 146 files |
| `python -m compileall -q cats_channel tests` | Passed |
| `git diff --check` | Passed |

The transport regressions use real loopback SOCKS handshakes to prove remote-DNS
routing and single-attempt rejection without direct fallback. Lifecycle tests cover
bounded `getMe` recovery, exhaustion, cancellation and exact safe phases. Adapter
tests cover the independent file timeout, full-decode intake, truthful
`telegram_native` provenance and Telethon terminal-future cleanup. Operation-log
tests keep intake disposition/placement and publication state visible without
message text, file identifiers or target identifiers; publication-service and bot
completion events remain distinct.

The configured private-pilot preflight subsequently passed identity, absent webhook,
destination access and posting permissions. One Telegram-native normal submission
completed a 67.1-second transfer and full decode under the explicit 180-second file
budget. Explicit `/pilot_publish` then used PR #29's publication service and produced
one confirmed attempt and one durable destination projection. A second live upload
completed full decode in 54.1 seconds as an exact interactive reply and remains
pending with no publication attempt. No public production channel was used.

A later restart exercised the failure path: three bounded identity requests failed
with `bot_api_get_me` diagnostics during a proxy interruption, and the process exited
without replaying an update or send. A bounded maintenance launch recovered polling.
This demonstrates containment and recovery behavior, not an external process
supervisor or a long-duration availability guarantee. The timings above are
functional observations, not throughput or percentile benchmarks.

Issue #8 moderation remains deliberately out of scope. `/pilot_publish` is a
temporary admin-only approval boundary; it is not the separate inspection-channel
queue, durable reviewer/rejection audit or version-aware callback workflow. Source
identity selected through a downloader-bot handoff also remains user-selected rather
than independently verified.

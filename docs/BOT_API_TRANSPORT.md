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
- `TELEGRAM_PROXY`: separate Telethon/MTProto route; never implicitly reused.
- `YOUTUBE_PROXY`: separate yt-dlp route; never implicitly reused.

`aiohttp-socks` is an explicit base dependency. SOCKS5h/SOCKS4a aliases normalize
to the connector's base schemes while aiogram sets remote DNS (`rdns=True`).
SOCKS connector failures are normalized centrally to a safe `TelegramNetworkError`;
these exceptions are not subclasses of `aiohttp.ClientError`. Error messages do
not copy token-bearing URLs or proxy exception text. No TLS verification is disabled.

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
| WSL `uv run --frozen pytest -q` | 442 passed, 61 skipped |
| Windows `uv run --frozen pytest -q` | 441 passed, 62 skipped |
| Both: `uv run --frozen ruff check .` | Passed |
| Both: `uv run --frozen ruff format --check .` | Passed, 145 files |
| Both: `uv lock --check` and `uv build` | Passed |
| WSL Git `git diff --check` | Passed |

Locked all-extras sync passed on both systems. WSL used `.venv-wsl`, Python 3.11.16
and `TMPDIR=/tmp`; Windows used `.venv-windows`, Python 3.11.4 and a workspace UV
cache. Only `aiohttp-socks==0.12.0` was added to the lock; existing packages and
the Python policy were preserved. Regression tests use actual loopback SOCKS5
handshakes to prove remote-DNS routing and single-attempt rejection without direct
fallback, plus fake preflight calls, secret-safe failures, cancellation, lifecycle
and CLI checks. Full suites include existing publication and migration regressions.

Live read-only Bot API checks used the configured SOCKS route. Final `getMe`
passed, webhook was absent with zero pending updates, and `getChat` rejected the
configured destination. Permissions/private-pilot eligibility therefore remain
unverified. An initial 20-second diagnostic timed out; the final check used the
documented default 60-second budget. This is evidence of connectivity, not a
long-duration network reliability claim.

Playwright inspected the user-provided
`https://www.youtube.com/@FunnyCatsTimeofficial/shorts` and selected its first
listed Short, `AzAQrr-BRJ0`. Exact browser tools used:
`mcp__playwright_global__browser_navigate` and
`mcp__playwright_global__browser_snapshot`.
The explicitly selected yt-dlp backend completed that full transfer and FFmpeg
decode: **2,308,571 bytes**, **41.123 seconds**,
SHA-256 `7936277ae6b1ba29296c0f12e1edff9732489faa9ba7cd30f438fe2b95ca50b7`.
The direct extractor's source handle matched the requested channel. An initial
transfer failed with TLS classification; a subsequent metadata-only diagnosis
passed, followed by one successful complete-transfer attempt. No retry loop,
certificate bypass or dependency upgrade was added to mask the incident.

The ignored worktree profile enables durable reply entries, resolves the existing
cookie export through its WSL path, explicitly selects yt-dlp, and uses an isolated
database upgraded to `0005_durable_publication`. The original profile was preserved.
The pilot database contains zero logical posts and zero publications. No live
Telegram message was sent, no public-channel pilot occurred, and no private
channel permissions or restart/delivery pilot are claimed. A valid private test
destination and bot membership are the remaining prerequisites. Issue #8 moderation
remains the next phase after that pilot, not part of this infrastructure follow-up.

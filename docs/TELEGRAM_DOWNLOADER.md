# Receive videos from @whatsmusicbot with Telethon

This optional backend follows the user-confirmed workflow: send one YouTube link
to @whatsmusicbot and receive a video directly. It does not invoke yt-dlp, contact
YouTube, read YouTube cookies, run YouTube probes, click buttons, join channels,
or make payments. The third-party bot performs extraction on its own infrastructure.

This implementation has offline mock coverage. A real login and direct-video
conversation still need testing in your own terminal. The backend is not enabled
by default and does not automatically replace a failed yt-dlp attempt.

## Configure

Install the existing optional `userbot` dependency extra into the correct venv.
For WSL:

```bash
cd /mnt/f/Git/CatsCh/CatsChannel
export UV_PROJECT_ENVIRONMENT=.venv-wsl
uv sync --locked --extra userbot
```

For PowerShell:

```powershell
Set-Location F:\Git\CatsCh\CatsChannel
$env:UV_PROJECT_ENVIRONMENT = '.venv-win'
uv sync --locked --extra userbot
```

Keep using the same environment variable for subsequent uv commands. This avoids
replacing an environment created for the other operating system. FFmpeg and FFprobe
must be installed in the environment from which you launch the app.

Set these fields in your local `.env`:

```dotenv
MEDIA_BACKEND=telegram_bot
TELEGRAM_API_ID=your_numeric_api_id
TELEGRAM_API_HASH=your_api_hash
TELETHON_SESSION=.secrets/user
TELEGRAM_PROXY=socks5h://127.0.0.1:10808
TELEGRAM_DOWNLOADER_BOT=whatsmusicbot
TELEGRAM_RESPONSE_TIMEOUT=180
```

For WSL, override the session location with a path on the Linux filesystem,
using your actual Linux home directory. For example:

```dotenv
TELETHON_SESSION=/home/YOUR_WSL_USER/.local/share/cats-channel/user
```

Prefer this to a session database on `/mnt/f` or another Windows-mounted drive.
Do not share one session file between Windows and WSL processes. This setting
does not automatically move an existing session or change its permissions.

`TELEGRAM_PROXY` is an explicit Telethon/MTProto route and is independent from
`YOUTUBE_PROXY`. Supported schemes are `http`, `socks4`, `socks4a`, `socks5`
and `socks5h`. For a local Xray SOCKS inbound, use the example above. Telethon
does not automatically inherit CatsChannel's YouTube proxy. In WSL NAT mode,
`127.0.0.1` must actually reach the proxy port from WSL; otherwise use the
reachable Windows-host address or enable WSL mirrored networking.

Obtain API ID/hash from your Telegram developer application at
[my.telegram.org](https://my.telegram.org). They belong to your Telegram client
application, not BotFather. Keep their actual values in `.env`; never put them in
chat, screenshots, source control or diagnostic output. The normal CatsChannel
`BOT_TOKEN` is only needed when running its aiogram bot.

## Login once in your own terminal

```bash
uv run --locked --extra userbot cats-channel --telegram-login
```

This is interactive: Telethon asks locally for the phone number, Telegram login
code and, if enabled, your two-factor password. Use your user account. A BotFather
token is not a substitute for this user session. No message is sent to the
downloader during login. Do not run the interactive login through an agent tool.

The resulting session file (the configured path plus `.session` when needed)
contains account authorization. Protect it as
a password and use a private directory. POSIX directory creation requests mode
0700; Windows privacy depends on the directory's ACLs. Session files, session
journals and operation locks are ignored by Git.

Before login or download, run the offline check:

```bash
uv run --locked --extra userbot cats-channel --doctor
```

For the Telegram backend it reports Telethon installation/version, whether both
API credentials are configured, session-file presence, the selected bot, FFmpeg
and FFprobe availability, and `telegram_backend_ready`. Readiness means these
local prerequisites are present; it does not authenticate, read the session
contents, contact Telegram, or verify the bot. Session authorization is explicitly
`not_checked`. YouTube cookie/profile diagnostics are omitted and cookie handling
is `not_used`. No credential values or session paths appear in this report.

After login, make one read-only online connection diagnosis when investigating the
route or session:

```bash
uv run --locked --extra userbot cats-channel --telegram-diagnose
```

This command performs one proxied MTProto connection and one authorization-state
check, then disconnects. It makes zero automatic retries, never asks for a phone,
password or login code, never resolves or contacts the downloader bot, and never
sends a message. Its JSON includes only attempt counts, completed/failed phases,
stable error policy and safe exception class names. No diagnostic log file is
created automatically; structured failures normally go to stderr. Redirect the
JSON yourself only when you intentionally want a review artifact.

Before using the automation, make sure you have completed any initial manual
`/start` or onboarding with @whatsmusicbot and that sending a link produces video.

## First download

```bash
uv run --locked --extra userbot cats-channel --download \
  'https://www.youtube.com/watch?v=VIDEO_ID'
```

Replace VIDEO_ID with one permitted 11-character YouTube ID. Running this command
sends that canonical link to the configured third-party bot using your account.
The link is visible to that bot's operator. No automatic resubmission is made.

With MEDIA_BACKEND set to telegram_bot, the existing `/download` command in
CatsChannel also uses this backend. Its normal admin/private-chat restriction
still applies. Run the bot with `--extra userbot` as well.

`--probe`, `--diagnose` and `/probe` return `backend_capability` guidance
for this backend: the remote bot does not provide a metadata-only YouTube
API. They do not silently invoke yt-dlp. `--list-downloads` and `--verify-download`
remain local operations.

The existing media library is reused. A valid cache hit sends no Telegram request.
For an intentional first-path test when the ID is already cached, set a separate
ignored root temporarily, for example `DOWNLOAD_DIR=downloads/telegram-test`.

## Processing and provenance

The adapter resolves the configured username, requires a bot peer, sends one link
inside an exclusive conversation, and inspects only newer incoming responses from
that bot. It skips progress text and unrelated senders/replies. Buttons and
non-video documents stop the operation with an actionable error. The first
implementation supports new direct video messages, not media added by editing an
earlier text message or multi-step quality menus.

A reply to the request is preferred. When the bot returns an unthreaded message,
the association is based on a serialized conversation. Do not manually send
other requests to the same bot during an automated operation. A bot's unrelated
unthreaded video cannot be independently identified as unrelated by this protocol.

The manifest records acquisition backend, bot username/ID, request/response message
IDs and correlation mode. `source_identity_verified` is explicitly false: neither
a matching reply nor a successful decode proves that a third-party bot returned
the actual video from the requested YouTube ID. Title is a local source label,
not an invented YouTube title. Duration, dimensions and codec come from FFprobe.

The returned file must satisfy the configured byte limit, match Telegram's stated
file size, pass stream/duration inspection, and pass full FFmpeg decode before
atomic library publication. There are no raw chat exports, cookies, signed URLs,
phone numbers or API hashes in the manifest.

## Failure behavior

- Missing credentials, optional package or user session: fail locally; downloads
  never prompt for login or read a browser profile.
- A session operation lock prevents concurrent conversations sharing that SQLite
  session across processes. A crash can leave a lock. Remove it manually only
  after all clients using that session have stopped; never delete the session
  itself just to clear a lock. CatsChannel also deliberately retains this lock
  when a bounded shutdown cannot prove that its owned task terminated.
- Flood-wait errors return a cooldown error without automatically sleeping or
  resending the link. Client request retries and automatic reconnect are disabled.
- Login and transfer exceptions are classified through ordered regex rules over a
  bounded exception-type chain. The JSON response and stderr log include only the
  stable code, phase, safe exception class names and retry policy—not Telegram's
  raw exception message.
- The connection middleware recognizes API credential, phone/code/password,
  flood-wait, session-database, proxy/network, protocol and temporary Telegram
  server families. Unknown classes remain `telegram_download` with low confidence
  until a redacted regression fixture justifies a narrower rule.
- Response wait is limited by TELEGRAM_RESPONSE_TIMEOUT and a 20-message budget;
  transfer has a 300-second timeout. Cancellation is passed to the active async
  operation before disconnect and staging cleanup. Cancellation drain is bounded;
  any late task remains owned and prevents the session lock from being released.
- Audio-only output, buttons, missing video, disconnection, oversize content or
  failed validation never becomes a successful library item.
- `YOUTUBE_PROXY` configures yt-dlp only. Set `TELEGRAM_PROXY` separately when
  Telegram requires the proxy. A configured Telethon proxy is never silently
  replaced by a direct connection.

Set `LOG_LEVEL=WARNING` (the default) for normal operation. CatsChannel writes
structured failures to stderr, leaving CLI JSON results on stdout. Logging failure
is contained and cannot replace the original Telegram error. See
[ERROR_HANDLING.md](ERROR_HANDLING.md) for the rule and fixture workflow.

After the first live receipt, verify the file locally and inspect the video
manually before an explicitly authorized private-channel publication. No account
login, third-party message, download or publication was performed by the agent
during implementation.

References: [Telethon conversations](https://docs.telethon.dev/en/stable/modules/client.html#telethon.client.dialogs.DialogMethods.conversation),
[media downloads](https://docs.telethon.dev/en/stable/modules/client.html#telethon.client.downloads.DownloadMethods.download_media).

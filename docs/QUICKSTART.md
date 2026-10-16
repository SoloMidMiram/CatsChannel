# Practical Python and media setup

## Recommendation and review

Use Python 3.11 for the first working example, with a project-local environment
managed by uv. `.python-version` selects the newest available 3.11 patch; the clean
review environment resolved to Python 3.11.15. `requires-python` permits 3.11
through 3.13, and CI checks both 3.11 and 3.13. Python 3.11 is now in security-only
support and reaches end of life in October 2027, so treat it as a compatibility
baseline rather than a permanent platform.

The original setup required 3.13 only, had a comment-only `uv.lock`, no configuration
loader, and no runnable app. The example addresses these foundation gaps. Database
dependencies are now an optional `persistence` extra; the demo requires no database
or Redis. Telethon is an optional `userbot` extra and is not started by the app.

Package baselines inspected on 2026-10-15:

| Component | Declared range | Purpose |
| --- | --- | --- |
| aiogram | >=3.31,<4 | Normal Telegram Bot API bot; current inspected release 3.31.0 supports Python 3.11 |
| Telethon | >=1.45,<2, optional | MTProto user/client worker; inspected release 1.45.0 |
| yt-dlp[default,curl-cffi] | >=2026.8.19 | Metadata extraction, EJS scripts and optional browser impersonation support |
| pydantic-settings | >=2,<3 | Validated configuration from environment and `.env` |

Ranges express compatibility policy; `uv.lock` records the exact resolved versions.
Normal installs use `--locked`. Dependency upgrades are deliberate lockfile changes
that are reviewed and tested before production rollout.

Sources: [aiogram](https://pypi.org/project/aiogram/),
[Telethon](https://pypi.org/project/Telethon/),
[yt-dlp](https://pypi.org/project/yt-dlp/).

## Pick one runtime per virtual environment

A virtual environment cannot be shared between Windows and WSL. This checkout had
a Windows `.venv/Scripts/python.exe`, which is not runnable by WSL. If you work in
both environments, keep two ignored environments and select the matching interpreter
in the editor. Do not put application data or secrets inside either environment.

### WSL setup

```bash
cd /mnt/f/Git/CatsCh/CatsChannel
export UV_PROJECT_ENVIRONMENT=.venv-wsl
export UV_LINK_MODE=copy
uv python install 3.11
uv sync --locked
cp --update=none .env.example .env
uv run --locked cats-channel --doctor
```

Run the `export` once in each new shell, or add a project-specific shell helper.
Use `.venv-wsl/bin/python` in a WSL-connected editor.
`UV_LINK_MODE=copy` avoids hardlink warnings when uv's Linux cache and this
Windows-mounted checkout are on different filesystems.

### Windows setup

From the repository root in PowerShell:

```powershell
uv python install 3.11
$env:UV_PROJECT_ENVIRONMENT = ".venv-win"
uv sync --locked
Copy-Item .env.example .env
uv run --locked cats-channel --doctor
```

Activation is optional with `uv run`. For interactive PowerShell, activate
`.\.venv-win\Scripts\Activate.ps1`; select that same interpreter in your editor.

Install media tools in the same operating system where the bot runs. On Windows:

```powershell
winget install --id Gyan.FFmpeg -e
winget install --id DenoLand.Deno -e
```

On Ubuntu/WSL, install FFmpeg with `sudo apt update && sudo apt install ffmpeg`,
then install Deno 2.3 or newer using its
[official instructions](https://docs.deno.com/runtime/getting_started/installation/).
If the Deno binary download is blocked, Ubuntu 26.04's Node 22 package is a
supported fallback: `sudo apt install nodejs`. CatsChannel automatically enables
Node for yt-dlp when Deno is unavailable.
Open a new shell and rerun `cats-channel --doctor` after installing either tool.

### WSL localhost-proxy warning

If WSL reports that a Windows localhost proxy was not mirrored and requests to
YouTube time out before connecting, fix WSL networking before changing cookies or
yt-dlp options. On Windows 11 22H2 or newer, open `%UserProfile%\.wslconfig` from
Windows (not from the WSL shell) and merge these keys into its existing `[wsl2]`
section:

```ini
[wsl2]
networkingMode=mirrored
dnsTunneling=true
autoProxy=true
```

Do not create a second `[wsl2]` section if one already exists. In Windows
PowerShell, run `wsl --update` and then `wsl --shutdown`; reopen WSL afterward.
Mirrored networking lets WSL use Windows localhost services, while `autoProxy`
imports the Windows proxy configuration. If mirrored mode is unavailable, the
alternative is to configure the proxy to accept LAN connections and point WSL at
the Windows host address; do not expose that listener without access controls.

Confirm connectivity independently before running the downloader:

```bash
curl --connect-timeout 10 -I https://www.youtube.com/
```

An HTTP response (including a redirect or access-denied response) proves the TCP/TLS
path works. A connection timeout means the WSL proxy/network issue remains.

For an Xray listener reachable at WSL localhost, prefer the project-scoped setting
over shell-global proxy variables:

```dotenv
YOUTUBE_PROXY=socks5h://127.0.0.1:10808
```

`socks5h` delegates hostname resolution to Xray and avoids leaking or misrouting
YouTube DNS. CatsChannel passes this value directly as yt-dlp's `--proxy` argument;
it does not mutate the parent environment and does not fall back to a direct route
when the proxy fails. `--doctor` reports only whether a proxy is configured and its
scheme, never its host or credentials. Proxy URLs containing credentials, paths,
queries, or fragments are rejected.

YouTube extraction can require an external JavaScript runtime and challenge
scripts. The `default` yt-dlp extra installs its Python-side dependencies; it does
not install Deno or Node. Follow the current upstream
[EJS instructions](https://github.com/yt-dlp/yt-dlp/wiki/EJS) when extraction reports
JavaScript issues. FFmpeg is strongly recommended. When present, the demo selects
H.264 MP4 video up to 720p plus M4A audio and merges them. Without FFmpeg it falls
back to a combined progressive stream, which is less available and often lower
quality. Run `--doctor` to see whether FFmpeg, Deno/Node, yt-dlp and the optional
cookie file are available.

## Credentials and secrets

Edit `.env` locally:

```dotenv
BOT_TOKEN=your_botfather_token
ADMIN_USER_ID=your_numeric_telegram_user_id
CHANNEL_ID=@your_test_channel
DOWNLOAD_DIR=downloads
MAX_DOWNLOAD_MB=45
MAX_DURATION_SECONDS=300
YOUTUBE_PROXY=socks5h://127.0.0.1:10808
```

1. Create a normal bot through Telegram's official @BotFather and copy its token.
2. Set your numeric user ID. Obtain it from a trusted existing tool or a Telegram
   update for your own account; a username is not a numeric user ID.
3. For publishing, add the bot as an administrator of a private test channel with
   posting permission. Set its numeric ID or public channel username. Leave this
   blank to use probing/downloading only.
4. Start the bot and send `/start` in a private chat from the allowed user account.
5. Never paste credentials into chat, commit them, or share `.env` screenshots.
   Production should inject environment variables from a secret manager. Rotate an
   exposed bot token via BotFather. Real environment variables override `.env`.

No Telegram API ID/hash is needed for aiogram. For a future Telethon worker, obtain
an API ID/hash from your Telegram developer application, use a separate session
under `.secrets`, and log in interactively with your own account. Session files
and session strings grant account access; protect them like passwords. The example
reserves these variables but does not implement or start a user-account worker.
No YouTube Data API key is needed for yt-dlp. A metadata-discovery integration with
YouTube Data API would be a separate adapter; its API key does not solve download
authentication or cookie problems.

`.env.example` has blank placeholders and is safe to track. `.env`, `.secrets/`,
cookie files, sessions, downloads and local environments are ignored. Store cookies
outside the repo when practical. To check ignoring without displaying values:

```powershell
git check-ignore .env .secrets/user.session downloads/video.mp4
```

## Run and probe

```powershell
uv run --locked cats-channel --doctor
uv run --locked python -m cats_channel --check
uv run --locked cats-channel --diagnose 'https://www.youtube.com/watch?v=VIDEO_ID'
uv run --locked python -m cats_channel --probe 'https://www.youtube.com/watch?v=VIDEO_ID'
uv run --locked python -m cats_channel --download 'https://youtu.be/VIDEO_ID'
uv run --locked cats-channel --list-downloads
uv run --locked cats-channel --verify-download VIDEO_ID
uv run --locked python -m cats_channel --bot
```

Replace VIDEO_ID with a real 11-character video ID you may download and reuse.
`--doctor` reports local tools and cookie-file readiness without printing paths or
secrets. Its cookie checks include format, newline style, and aggregate
expiry/domain counts without names or values. `--check` validates required bot configuration offline; it does not
authenticate.
`--diagnose` makes one metadata attempt and emits a secret-safe decision manifest;
use it instead of repeatedly probing during troubleshooting. See
[MEDIA_DIAGNOSTICS.md](MEDIA_DIAGNOSTICS.md) for the error-code algorithm.
The regex taxonomy, structured exception example, cookie lifecycle, and Docker
tradeoffs are documented in [DOWNLOADER_ERRORS.md](DOWNLOADER_ERRORS.md).
The baseline and optional bgutil PO-token profiles are documented in
[YOUTUBE_PROFILES.md](YOUTUBE_PROFILES.md). Because the app passes
`--ignore-config`, profile options are explicit application settings rather than
user-level yt-dlp configuration.
`--probe` works without Telegram credentials, requests metadata without downloading
the video, and prints only ID/title/duration/availability/live status/source URL.
It still makes network requests. Metadata success does not prove media download
will succeed. `--download` atomically stores the media and a curated metadata
manifest under `downloads/library/youtube/VIDEO_ID`. Repeating it for a complete
item does not make another network request. `--list-downloads` and
`--verify-download` are local-only management commands. See
[MEDIA_LIBRARY.md](MEDIA_LIBRARY.md) for the layout, manifest, integrity checks,
and backup guidance. The bot cleans up its temporary files after upload or failure.

Bot commands:

- `/probe URL`: inspect one video.
- `/download URL`: return the downloaded media to the admin's private chat.
- Reply `/publish` to a Telegram video: copy it to CHANNEL_ID. You can also upload
  your own video to the chat and publish it this way, bypassing YouTube extraction.

Downloads are serialized, bounded to five minutes per download process, five
minutes of video by default, and 45 MiB per file. Probes have a 90-second process
timeout. The size setting is conservative for the demo, not a claim about every
Telegram API deployment's limit. Unknown-length/live content is rejected. A size
check after download prevents oversized uploads, but unknown remote sizes mean
`--max-filesize` cannot guarantee a strict disk/network quota. Use worker disk
quotas before public ingestion. WebM results are sent as documents; `/publish`
in this example accepts Telegram video messages only.

## aiogram versus Telethon

Use aiogram for the main application: it is a normal Bot API bot, needs only the
BotFather token, and covers submissions, moderation, replies and channel posting.
Telethon is an MTProto client that can log in as either a bot or a user. Add a
user-account worker only when a documented requirement cannot be served by the Bot
API. Run it as a separate process and dependency extra; its API hash and session
file are high-value secrets. Do not use a personal account merely to automate a
third-party downloader bot.

## yt-dlp versus third-party download bots

Use your own yt-dlp adapter first. It provides controllable versions, timeouts,
formats, and metadata. A third-party bot introduces another operator, service
availability, opaque output and possible account/client automation. Consider one
only as an explicitly selected fallback after measuring reliability and checking
its automation rules. Telegram supports limited bot-to-bot communication when both
bots opt in, but a downloader bot still needs a documented, stable interface and
permission for automation. Do not add Telethon just to simulate a user conversation
with another bot.

Cookies are optional and should be added only when access requires them. Set
`YOUTUBE_COOKIE_FILE` to a private Netscape-format cookie file. Start with a public
video without cookies. When it fails:

1. Check access from the intended environment, package version, and JS runtime.
2. Retry metadata and download separately; avoid repeated automated retry loops.
3. If login is required, follow upstream cookie export guidance and use only an
   account you control. Cookies expire/rotate and account-backed extraction has
   account risks. Never send cookies to a third-party bot.
4. Cookies alone do not address all failures. YouTube may require PO tokens for
   particular clients/formats or apply request limits. Follow the current
   [extractor guidance](https://github.com/yt-dlp/yt-dlp/wiki/Extractors#youtube)
   and [PO-token guide](https://github.com/yt-dlp/yt-dlp/wiki/PO-Token-Guide).

CatsChannel never gives the source cookie export directly to yt-dlp. Each operation
uses a private disposable copy, allowing yt-dlp to update its working jar without
rewriting the source. This preserves the local export but cannot prevent YouTube
from rotating or invalidating the session server-side. A direct `--download` now
uses one yt-dlp process for extraction, policy checks, and media transfer; avoid a
routine probe immediately before it when minimizing requests matters.

The example deliberately suppresses raw downloader stderr because it can contain
signed media URLs/account information. It reports a safe error and nonzero CLI
exit. It does not promise reliable extraction of every video or automatically
bypass access restrictions. A YouTube page probe cannot determine that a video
contains cats or that you have permission to republish it.

## Update and upgrade phases

1. **Foundation now:** lock packages, use a patched 3.11 environment, run offline
   checks, then smoke-test a public video and a private test Telegram channel.
2. **Monthly maintenance:** on a branch, run `uv lock --upgrade`,
   `uv sync --locked --all-extras`, `uv run pytest` and `uv run ruff check .`.
   Review dependency changes, test startup/probe/download/publish and commit the
   lockfile together with configuration changes. For a YouTube extractor break,
   prefer `uv lock --upgrade-package yt-dlp` first. Never silently upgrade production.
3. **Python upgrade rehearsal:** during the next foundation milestone, create a
   disposable 3.13 environment and run the same checks/smoke tests. CI tests 3.11
   and 3.13 meanwhile. Target switching the default to 3.13 by June 2027, after
   compatibility is demonstrated. Retire 3.11 before its October 2027 end of life.
4. **Production:** queue downloads in a separate worker, add durable submission
   state, moderation, idempotent publishing, disk quotas, rate limits and metrics.
   Add Telethon only for a concrete requirement Bot API cannot meet. Run it as a
   separate process with its own credentials, dependency extra and lifecycle.

The sample is an integration spike, not the completed moderation/reply-chain
platform. Tests use local mocks; real tokens, Telegram posting, YouTube extraction,
cookie validity, JS runtime and FFmpeg behavior need live smoke validation.

Local validation on 2026-10-16 produced these offline results from the lockfile:

- WSL Python 3.11.16: 76 passed, 1 Windows-only test skipped;
- WSL Python 3.13.15: 76 passed, 1 Windows-only test skipped;
- Windows Python 3.11.4: 75 passed, 2 POSIX-only tests skipped;
- Ruff lint/formatting, lock consistency, and package builds passed.

Real Telegram credentials, YouTube access, cookie validity, JavaScript challenges,
FFmpeg behavior, and private-channel publication still require authorized live
smoke tests.

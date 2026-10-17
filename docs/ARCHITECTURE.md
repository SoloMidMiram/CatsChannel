# Media foundation architecture

The CLI and Telegram adapter use one acquisition service. Neither entry point may
upload or report a successful item before local validation and atomic publication.

```text
CLI / Telegram handlers
          |
          v
      MediaService
          |
          v
YouTube extraction -> metadata policy -> playback validation -> library publication
       |                                      |
       v                                      v
cookie copy + owned process             FFprobe + full FFmpeg decode
```

Current module responsibilities:

```text
cats_channel/
  __main__.py                    # minimal package entry point
  cli.py                         # arguments and safe JSON rendering
  bot/
    application.py              # application factory and polling lifecycle
    context.py                  # correlation/timing middleware and operation context
    errors.py                   # safe bot response adapter and unexpected-error boundary
    handlers.py                 # private admin commands and explicit publication
  config.py                      # validated environment configuration
  diagnostics.py                 # ordered regex rules and secret-safe JSON logging
  errors.py                      # stable error and retry policies
  models.py                      # typed metadata, artifacts, and library items
  media.py                       # YouTube URL/profile/extraction adapter and classifier facade
  library.py                     # integrity checks and atomic local publication
  services/media_service.py      # shared synchronous/asynchronous acquisition boundary
  adapters/cookies.py            # immutable source and disposable cookie copy
  adapters/process.py            # owned process groups, timeout, cancellation, reap
  adapters/telethon_connection.py # MTProto lifecycle and phase-aware diagnosis middleware
  adapters/validation.py         # finite FFprobe data and complete FFmpeg decode
```

The retained `media.py` and `library.py` imports are compatibility facades for the
existing CLI and tests; cohesive process, cookie, validation, error, and model
responsibilities no longer live inside the handlers.

## Invariants

- The bot uploads only the `LibraryItem.media_path` returned by `MediaService`.
- Cache reuse verifies video ID, byte count, and SHA-256 without contacting YouTube.
- Invalid metadata, non-finite durations, decode failures, and corrupt cache entries
  cannot become successful items.
- Cancellation reaches the owned yt-dlp/FFmpeg process group; cleanup and lock
  release happen only after the process is reaped.
- A configured `YOUTUBE_PROXY` is passed explicitly to yt-dlp. Failure never causes
  a silent direct-network fallback.
- Staging publication is atomic. Same-process acquisition is serialized per video
  ID, and destination races accept only a verified winning item.
- Source cookies are never passed to yt-dlp and remain immutable.
- Telegram publication remains a separate explicit operation and is never blindly
  retried after an ambiguous API failure.
- Final CLI and bot boundaries emit one allowlisted JSON failure event to stderr.
  Exception messages, URLs, phone numbers, credentials and raw third-party logs
  never enter the structured logger.

Future submission, moderation, reply-chain, and persistence services should depend
on `MediaService`, not on yt-dlp, FFmpeg, or aiogram implementation details.

## Aiogram application core

`create_bot_application()` is the composition root. It creates no network
connection and accepts an injected `MediaService`, logger, monotonic clock, and
correlation-ID factory. The returned `BotApplication` owns one dispatcher, one
media-task gate, and the concrete dependencies made available through aiogram's
workflow data.

```text
run_bot()
    -> create_bot_application()
        -> private/admin router
        -> operation logging middleware
        -> MediaService dependency
        -> one-process media task gate
    -> Bot context
    -> dispatcher polling
```

The router preserves the initial pilot behavior: only the configured admin in a
private chat reaches `/start`, `/help`, `/probe`, `/download`, or `/publish`; one
media operation runs at a time; and an upload can only use the `LibraryItem`
returned by `MediaService`. The application core deliberately has no speculative
repository abstraction. Persistence, reply-chain decisions, moderation, and live
pilot optimization remain later features.

## Optional Telegram downloader backend

`MEDIA_BACKEND=telegram_bot` selects `adapters/telegram_downloader.py` for cache
misses. A separate Telethon user session sends one link to the configured bot and
receives a direct video; both CLI and aiogram downloads retain the same validation
and library publication path. yt-dlp remains the default for compatibility and is
not a fallback when the Telegram backend fails. Metadata probes are unsupported
on this backend rather than silently contacting YouTube.

Telegram receipts are recorded as acquisition provenance. Their association with
the requested YouTube ID is explicitly unverified. See TELEGRAM_DOWNLOADER.md for
login, session isolation, direct-message limitations and the live smoke-test gate.
The deterministic error-handling contract is documented in ERROR_HANDLING.md.

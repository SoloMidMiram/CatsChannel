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
  bot.py                         # aiogram wiring and explicit publication
  config.py                      # validated environment configuration
  errors.py                      # stable error and retry policies
  models.py                      # typed metadata, artifacts, and library items
  media.py                       # YouTube URL/profile/extraction adapter and classifier facade
  library.py                     # integrity checks and atomic local publication
  services/media_service.py      # shared synchronous/asynchronous acquisition boundary
  adapters/cookies.py            # immutable source and disposable cookie copy
  adapters/process.py            # owned process groups, timeout, cancellation, reap
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

Future submission, moderation, reply-chain, and persistence services should depend
on `MediaService`, not on yt-dlp, FFmpeg, or aiogram implementation details.

# Low-request YouTube diagnostics

CatsChannel treats each extractor execution as a scarce attempt. `--diagnose`
performs exactly one metadata extraction, suppresses raw yt-dlp stderr, and emits a
secret-safe JSON manifest. It never prints cookie paths, cookie values, signed media
URLs, request headers, or account data.

```bash
uv run --locked cats-channel --diagnose \
  'https://www.youtube.com/shorts/VIDEO_ID'
```

The schema-v3 manifest contains a UTC timestamp, video ID, runtime readiness,
extractor-attempt and automatic-retry counts, elapsed time, status, and either safe
metadata or one classified error with the next action. `log_analysis` contains only
the primary code, category, phase, confidence, observed signal codes, line counts,
allowlisted HTTP statuses/exception types, match scope, and a short fingerprint
computed after aggressive redaction. The terminal `ERROR:` line takes precedence
over earlier warnings; stderr without an `ERROR:` prefix is still classified from
the last matching line. Raw stderr is never included. The full rule design and
cookie/container guidance are in [DOWNLOADER_ERRORS.md](DOWNLOADER_ERRORS.md).
Save the manifest when needed with normal shell redirection; it is designed to be
safe for issue reports, but review any diagnostic artifact before sharing it.

## Decision algorithm

1. Run `--doctor`. This is local and makes no YouTube request. Correct missing
   cookie files, FFmpeg, and JavaScript runtime problems first.
2. Run `--diagnose URL` once. Do not run `/probe`, `--probe`, and `--diagnose` for
   the same investigation; they are separate extractor attempts.
3. Follow the manifest error code:
   - `invalid_url`, `cookie_missing`, `js_runtime`, or `ffmpeg`: repair locally,
     then make one diagnostic attempt.
   - `profile_config` or `proxy_config`: correct the selected profile/route before
     any network attempt.
   - `network_connect`, `network_tls`, or `timeout`: test the proxy with one bounded
     `curl` request. Repair or switch the proxy route, then make one diagnostic
     attempt. Do not test cookies while transport is broken.
   - `auth_cookies`: stop. Export a fresh private-session cookie jar once, using
     the same stable proxy exit IP, then make one diagnostic attempt.
   - `video_unavailable`: stop and replace the URL.
   - `po_token`: stop and configure a supported provider before another attempt.
   - `pot_provider`: repair the plugin-to-provider connection before another
     YouTube attempt.
   - `rate_limit`: stop and wait for the limit window; switching into a retry loop
     makes the restriction worse.
   - `http_forbidden`: check proxy reputation and current PO-token guidance first.
   - `geo_restricted`: stop or use an authorized route in an available region.
   - `policy_limit`: stop; changing retries cannot make the video meet policy.
   - `metadata_invalid` or `extractor`: inspect the locked yt-dlp version and its
     current upstream guidance. Do not loop.
4. If diagnosis succeeds and a download is intended, run `--download URL` directly.
   It performs extraction, policy filtering, and download in one yt-dlp process.
   Do not precede it with another probe merely as a routine step.
5. On failure, preserve the manifest and stop. Make at most one new attempt after a
   concrete state change such as switching a node, refreshing cookies, or updating
   yt-dlp.

## Cookie preservation model

`YOUTUBE_COOKIE_FILE` is the immutable source export. CatsChannel copies it into a
mode-`0600` temporary directory for each yt-dlp process. yt-dlp may update that
working jar during the operation; CatsChannel discards the copy afterward, leaving
the source file byte-for-byte unchanged.

This prevents local mutation but cannot guarantee session longevity. YouTube can
rotate or invalidate a session on the server, especially when a browser reopens the
same session, the proxy exit IP changes, or request limits are reached. Keep the
source under `.secrets`, never commit it, do not reopen its private browser session,
and use account cookies only when necessary.

## Manifest error codes

| Code | Meaning | Retry policy |
| --- | --- | --- |
| `network_connect` | DNS/proxy connection failed | Once after network repair |
| `network_tls` | Proxy/TLS path failed | Once after route/node change |
| `timeout` | Bounded request expired | Once after health check/cooldown |
| `proxy_upstream` | Proxy/upstream returned 5xx | Once after route change |
| `rate_limit` | HTTP 429 or explicit rate limit | Cool down; do not retry now |
| `http_forbidden` | HTTP 403 | Investigate proxy/PO token first |
| `geo_restricted` | Region restriction | Stop or use an authorized region |
| `auth_cookies` | YouTube requested authenticated cookies | Once with a fresh export |
| `cookie_format` | Cookie jar is not valid Netscape data | Once after local repair |
| `profile_config` | Optional profile is incomplete | After local setup |
| `cookie_missing` | Configured source file is absent | Once after local repair |
| `local_io` | Cookie/temp/local file operation failed | Repair locally first |
| `process_start` | yt-dlp process could not start | Repair environment first |
| `video_unavailable` | Removed, private, or restricted video | Do not retry |
| `js_runtime` | Node/Deno is unavailable or unusable | Once after local repair |
| `po_token` | Selected client/format needs attestation | Once after provider setup |
| `pot_provider` | PO-token provider failed or was unavailable | After provider repair |
| `policy_limit` | Live/unknown/over-duration media | Do not retry |
| `format_unavailable` | No supported format exposed | Investigate policy/token first |
| `media_delivery` | Metadata worked but media/fragment transfer failed | After route/token change |
| `media_validation` | Saved media failed FFprobe/full-decode validation | Investigate locally |
| `extractor_parse` | Expected response could not be parsed | Review yt-dlp first |
| `metadata_invalid` | Extractor metadata failed schema/finite-value checks | Investigate version first |
| `download_output` | Output was missing, duplicated, or unsupported | Inspect staged format output |
| `upload_limit` | Final media exceeded configured size | Do not retry unchanged policy |
| `cache_corrupt` | Stored bytes/ID differ from the manifest | Explicitly quarantine or remove |
| `cancelled` | Owned operation was cancelled and reaped | Explicit later attempt only |
| `cleanup_failed` | Staging cleanup could not complete | Inspect staging before retrying |
| `extractor` | Other safely redacted extractor failure | Investigate first |
| `internal_error` | Unexpected exception safely contained | Inspect code; no auto-retry |

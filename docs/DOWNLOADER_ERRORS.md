# yt-dlp error taxonomy and cookie operations

CatsChannel converts untrusted yt-dlp stderr into stable error codes. Raw stderr is
not returned because it may contain signed media URLs, request headers, account
details, or cookie material.

## Recognition model

Use ordered regular expressions, not statistical regression. The input is a small
set of evolving diagnostic strings, not numeric training data, and the desired
result must be deterministic and auditable. A lambda is used only to sort matched
rules by priority; it is not the classifier.

Each rule defines:

- a stable code used by application logic;
- a broad category such as `network`, `authentication`, or `download`;
- the phase where it occurred, such as `tls`, `metadata`, or `media_transfer`;
- a confidence level and one or more case-insensitive regex patterns.

Specific causes take priority over generic symptoms. For example, a line containing
both “unable to download video data” and `SSLError` is classified as `network_tls`,
while `media_delivery` remains in the signal list. A terminal `ERROR:` line takes
priority over earlier warnings. If yt-dlp emits no `ERROR:` prefix, the classifier
works backward from the last non-empty stderr line.

Safe diagnostics include only categories, counts, allowlisted HTTP status and
exception names, and a hash fingerprint computed after redaction. They never
include the matched text.

## Operational groups

| Group | Stable codes | Typical response |
| --- | --- | --- |
| Local configuration | `cookie_format`, `cookie_missing`, `profile_config`, `process_start`, `local_io` | Repair locally; no network retry yet |
| Authentication | `auth_cookies` | Refresh once using the documented export flow |
| Network | `network_connect`, `network_tls`, `timeout`, `proxy_upstream` | Repair or change the route before one attempt |
| Remote policy | `rate_limit`, `http_forbidden`, `geo_restricted` | Cool down or investigate; do not loop |
| YouTube attestation/runtime | `po_token`, `pot_provider`, `js_runtime` | Configure or repair the required provider/runtime |
| Content | `video_unavailable`, `policy_limit` | Stop or choose another permitted video |
| Format/download | `format_unavailable`, `media_delivery`, `media_validation`, `ffmpeg` | Check formats, media-CDN route, token, or FFmpeg |
| Extractor | `extractor_parse`, `metadata_invalid`, `extractor` | Review the locked yt-dlp version and upstream changes |
| Local integrity | `media_validation`, `cache_corrupt`, `cleanup_failed` | Do not publish; inspect or quarantine locally |

An unknown message intentionally remains `extractor` with low confidence. Add a
fixture based on a redacted real error before introducing a new rule; do not guess
from one word such as “failed”.

## Application handling

The CLI already uses this pattern through `media_error_report`:

```python
try:
    item = store_download(settings, url)
except MediaError as error:
    report = media_error_report(error)
    match error.code:
        case "cookie_format" | "cookie_missing":
            repair_local_cookie_configuration(report)
        case "auth_cookies":
            schedule_manual_cookie_refresh(report)
        case "network_connect" | "network_tls" | "timeout":
            pause_until_network_route_changes(report)
        case "rate_limit":
            enter_cooldown(report)
        case _:
            send_for_operator_review(report)
```

Those example functions represent application decisions; they should not directly
retry. The report contains the documented retry policy. A worker may place the job
in a durable state such as `waiting_for_network_change`, but only an operator or a
measured health-state change should release it.

## Cookie health and lifecycle

`--doctor` checks the cookie source without contacting YouTube. It reports whether
the file is readable, whether it has a Netscape header and valid seven-column rows,
its newline style, and only aggregate counts for entries, YouTube domains, expired
entries, and session entries. It never reports cookie names or values.

Recommended lifecycle:

1. Do not use account cookies for public videos unless YouTube actually requests
   authentication.
2. Export a Netscape-format jar from a new private/incognito session following the
   upstream YouTube extractor instructions, then close that private session and do
   not reopen it.
3. Store the export outside Git with owner-only permissions where supported.
4. Keep one immutable source export. CatsChannel copies it to a private temporary
   file for each process and lets yt-dlp mutate only that disposable copy.
5. Keep the browser export and downloader on a stable, consistent egress route.
6. Refresh only after an `auth_cookies` result or an intentional credential
   rotation—not after TLS, DNS, proxy, format, or PO-token errors.

The yt-dlp FAQ warns that browser extraction may export cookies for every site, so
the jar must be handled as a high-value secret. The upstream YouTube guide also
warns that account cookies can be rotated and that account-backed extraction has
account risk.

## What Docker changes

Docker can improve reproducibility and isolation, but it cannot extend cookie
lifetime, repair an Xray route, change YouTube rate limits, or satisfy PO-token
requirements.

Useful Docker properties:

- pin the Python, yt-dlp, EJS, JavaScript runtime, and FFmpeg environment;
- mount the source cookie as a read-only Compose secret;
- use a writable `tmpfs` for the disposable cookie copy;
- mount only the download library as persistent writable storage;
- run as a non-root user with a read-only root filesystem.

Illustrative Compose fragment, after a project image is defined:

```yaml
services:
  cats-channel:
    image: cats-channel:local
    read_only: true
    environment:
      YOUTUBE_COOKIE_FILE: /run/secrets/youtube_cookies
      DOWNLOAD_DIR: /data/downloads
      HTTPS_PROXY: http://host.docker.internal:10808
    secrets:
      - youtube_cookies
    tmpfs:
      - /tmp:size=128m,mode=1777
    volumes:
      - ./downloads:/data/downloads
    extra_hosts:
      - host.docker.internal:host-gateway

secrets:
  youtube_cookies:
    file: ./.secrets/youtube-cookies.txt
```

Do not use `127.0.0.1:10808` inside the container: that address means the container
itself. `host.docker.internal` must reach the host proxy, and Xray must permit the
Docker-side connection. Verify this for the chosen Docker Desktop/WSL networking
mode. Avoid mounting an entire browser profile; it exposes much more data and often
introduces profile locking and keyring/decryption problems.

References: the [yt-dlp FAQ](https://github.com/yt-dlp/yt-dlp/wiki/FAQ),
[YouTube extractor guidance](https://github.com/yt-dlp/yt-dlp/wiki/Extractors),
[EJS guide](https://github.com/yt-dlp/yt-dlp/wiki/EJS),
[PO-token guide](https://github.com/yt-dlp/yt-dlp/wiki/PO-Token-Guide), and
[Docker Compose secrets](https://docs.docker.com/compose/how-tos/use-secrets/).

# YouTube downloader profiles

CatsChannel keeps extraction behavior explicit because every yt-dlp process uses
`--ignore-config`. User-level yt-dlp configuration files do not affect the app.

## Route-first decision

Do not enable a PO-token provider to treat TLS, DNS, proxy, or connection failures.
Those failures occur before token-based authorization can help. First confirm that
the WSL process can consistently reach YouTube and that the Xray route sends media
CDN traffic, including `googlevideo.com`, through the intended outbound. Page and
metadata success alone do not validate the signed media-host route.

Do not disable certificate verification. Do not globally force browser
impersonation. Neither is part of these profiles.

## Baseline profile

This is the default:

```dotenv
YOUTUBE_PROFILE=baseline
YOUTUBE_POT_PROVIDER_URL=
```

Both profiles explicitly apply:

```text
--concurrent-fragments 1
--abort-on-unavailable-fragments
--sleep-requests 1
--retries 0
--extractor-retries 0
--fragment-retries 0
```

Unavailable fragments therefore fail the item instead of producing a knowingly
incomplete file. Diagnostics and downloads still make no automatic retry. Node 22
and the locked `yt-dlp-ejs` package remain the JavaScript setup when Deno is absent.

After downloading, persistent library items must pass three separate checks before
their staging directory is published:

1. yt-dlp metadata ID and duration policy;
2. FFprobe container, stream, and plausible-duration inspection;
3. a full FFmpeg decode plus file size and SHA-256 recording.

## Optional bgutil PO-token profile

The profile is intentionally absent from the baseline installation. Install its
pinned Python plugin with:

```bash
uv sync --locked --extra pot
```

Start the matching provider server without exposing its unauthenticated port to the
LAN:

```bash
docker run --name bgutil-provider --detach --init \
  --publish 127.0.0.1:4416:4416 \
  brainicism/bgutil-ytdlp-pot-provider:2.0.2-node
```

Then configure:

```dotenv
YOUTUBE_PROFILE=pot_bgutil
YOUTUBE_POT_PROVIDER_URL=http://127.0.0.1:4416
```

The application adds these arguments itself:

```text
--extractor-args youtube:player-client=mweb
--extractor-args youtubepot-bgutilhttp:base_url=http://127.0.0.1:4416/
```

`--doctor` reports the selected profile, installed plugin version, whether a
provider URL is configured, and profile readiness without printing the URL.
Selecting `pot_bgutil` without both pieces fails locally before contacting YouTube.

If CatsChannel later runs in Compose with the provider as another service, use its
service name, for example `http://pot-provider:4416`, rather than `127.0.0.1`.
Provider version 2.0.2 contains an important server-binding security change; keep
the plugin and container version matched. Review the provider's release and license
before distributing a combined image.

The provider does not guarantee success, repair a bad route, or bypass IP-based
login restrictions. Do not enable it for every failure.

## Controlled comparison

Only compare profiles after the route is stable. Use separate library roots so a
successful baseline item is not returned as an existing item during the provider
test:

```bash
YOUTUBE_PROFILE=baseline \
DOWNLOAD_DIR=downloads/baseline \
uv run --locked cats-channel --download 'https://www.youtube.com/watch?v=VIDEO_ID'

YOUTUBE_PROFILE=pot_bgutil \
YOUTUBE_POT_PROVIDER_URL=http://127.0.0.1:4416 \
DOWNLOAD_DIR=downloads/pot-bgutil \
uv run --locked cats-channel --download 'https://www.youtube.com/watch?v=VIDEO_ID'
```

For each run, compare extraction status, transfer completion, the manifest's
playback validation, and final hash. Do not run both repeatedly: one attempt per
profile is sufficient for a controlled comparison.

References: [yt-dlp download options](https://github.com/yt-dlp/yt-dlp#download-options),
[EJS guide](https://github.com/yt-dlp/yt-dlp/wiki/EJS),
[PO-token guide](https://github.com/yt-dlp/yt-dlp/wiki/PO-Token-Guide), and the
[bgutil provider](https://github.com/Brainicism/bgutil-ytdlp-pot-provider).

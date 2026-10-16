# Local media library

Both the command-line downloader and Telegram bot acquire videos as self-contained,
validated library items through the same `MediaService`. The bot uploads the stored
media path only after metadata, integrity, FFprobe, and full-decode checks pass.

## Layout

`DOWNLOAD_DIR` defaults to `downloads`. A completed item has this layout:

```text
downloads/
├── .staging/                         # incomplete work; cleaned after each command
└── library/
    └── youtube/
        └── Q_oekkGTGPE/
            ├── manifest.json         # portable metadata and integrity record
            └── media.mp4             # mp4, webm, or mkv
```

The YouTube video ID is the stable item key. Repeating `--download` for a complete
item first checks its ID, size, and SHA-256, then returns `status: existing` without
contacting YouTube. A corrupt cache returns `cache_corrupt`; it is never silently
reused or overwritten. A global index is not
required: `--list-downloads` scans the small per-item manifests, so moving or
backing up the library does not leave an index out of sync.

`manifest.json` contains:

- schema version, UTC download time, canonical source URL, and video ID;
- a curated metadata subset such as title, duration, channel, upload date,
  resolution, codecs, and selected format;
- media filename, byte count, and SHA-256 digest;
- FFprobe stream/duration results and successful full FFmpeg decode status;
- the size/duration policy and yt-dlp version used for the download.

It intentionally excludes cookies, request headers, signed media URLs, and raw
extractor logs.

## Commands

Download and atomically add one permitted video:

```bash
uv run --locked cats-channel --download \
  'https://www.youtube.com/shorts/Q_oekkGTGPE'
```

List the local catalog without network access:

```bash
uv run --locked cats-channel --list-downloads
```

Verify file size and SHA-256 without network access:

```bash
uv run --locked cats-channel --verify-download Q_oekkGTGPE
```

The download is first written beneath `.staging`. The application validates the
video ID, size limit, metadata, FFprobe stream/duration results, a full FFmpeg
decode, and the hash; it writes the manifest and only then renames the complete
directory into the library. Failed staging directories are removed only after owned
processes have terminated and been reaped. A cleanup failure is reported without
replacing the original operation failure.
Downloads use a 45-second socket-read timeout inside a five-minute process bound,
with yt-dlp retries disabled. Metadata probes retain the shorter 20-second socket
timeout. Operators, rather than an automatic retry loop, decide whether a changed
network route justifies another attempt.
An existing but invalid item is never silently overwritten; inspect or move it out
of the library before intentionally downloading a replacement.

The entire `downloads/` tree is ignored by Git. Back it up separately if the media
and manifests are important. Do not commit downloaded videos or assume that a
successful download grants redistribution rights.

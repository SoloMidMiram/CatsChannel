# Live Telegram downloader validation — 2026-10-17

The user explicitly authorized one live request for
`https://www.youtube.com/shorts/Sgnx_aNvyFs` through the optional Telethon
backend and configured third-party downloader bot.

## Result

- Read-only connection and authorization diagnosis: passed in one attempt.
- Automatic retries: zero.
- Request count: one.
- Bot response: direct `video/mp4` document with caption
  `whatsmusicbot | source` and buttons.
- Correlation: serialized conversation; the response was not a Telegram reply to
  the request message.
- Stored media: 23,650,577 bytes, 1080×1920, H.264 video with AAC audio.
- Duration: 61.417 seconds.
- SHA-256: `99ee49d88272a42954acf3d3b9f7fc136014a2754508f574a98f76ee6b486b91`.
- FFprobe stream validation and full FFmpeg decode: passed.
- Manifest source, recorded size, and SHA-256 verification: passed.
- Disconnect completed and no session-operation lock remained.

The media was stored under an isolated temporary library, not the repository
library. No Telegram channel publication was attempted.

## Important limitation

The third-party response was accepted as untrusted media and validated locally,
but `source_identity_verified` remains false. A serialized conversation and valid
video do not independently prove that the bot returned the exact content of the
requested YouTube ID. Manual viewing or an independent content comparison is
still required for that claim.

No credentials, account identity, session path, session contents, proxy address,
or raw exception text are recorded here.

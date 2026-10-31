# Private pilot: gfdwZV_ypbw

Completed on 2026-10-25. The configured HTTP proxy recovered and passed Bot API
identity, absent-webhook, private-destination and posting-permission checks. The
proxy remained enabled. The switch itself did not repair the earlier failure;
this run does not establish that DNS/routing is permanently fixed.

The saved downloader response for the user-selected URL
`https://www.youtube.com/shorts/gfdwZV_ypbw` was reused. The source URL was not
resent. One `/post`, one source selection, one forwarded video and one
`/pilot_publish` command completed through the real Telethon/aiogram workflow.

## Verified result

- Submission: `d08ef2f0-5217-4329-a2f7-f3f3e60b525b`.
- Full FFmpeg decode passed: 3,928,713 bytes, 65.248 seconds.
- SHA-256: `c3a06e141687d185881d43863fbc8d08dcd8f1b84df9743e6bd2ef13397ac719`.
- One logical post: `d164a804-9122-4ee4-a197-74da2a33e4a7`.
- One confirmed publication attempt for
  `59859960-91b2-45f1-b210-669a5e717bbd`; no automatic send retries.
- One destination projection; reply markup is `installed`.
- The delivered video, reply button and exact confirmed parent were read back
  through Telethon and verified.
- [Private pilot message](https://t.me/c/2885576054/1228).

Application logs contain seven structured events: successful `/post`, successful
source selection, validated pending intake, publication dispatch/confirmation,
publication-service completion and command completion. Intake took 6.015 seconds;
publication-service completion took 1.968 seconds. No application error or warning
events were found. The application log contains neither the configured bot token
nor Telegram API hash.

## Harness reconciliation and limits

The initial harness compared a Telethon user-account message ID with the Bot API
message reference and failed to observe an intake that had already succeeded.
That harness was interrupted. Its process exit and absence of competing pollers
were checked before releasing its stale session lock. No intake was resent.

The recovery harness downloaded the original saved downloader media locally and
matched its complete SHA-256 to the durable validated submission. It then sent one
publication approval. Final polling shutdown drained all updates; Telethon
disconnected cleanly and its session lock was removed.

The placement uses the existing, selected Telegram downloader-source thread.
The supplied YouTube channel association remains user-selected and unverified:
`source_identity_verified=false`. Neither channel identity nor a separate verified
YouTube source chain is proven by this run. Only the private test destination was
used; this is not production publication or Issue #8 moderation acceptance.

Ignored local evidence:

- `.runtime/telethon-pilot-gfdwZV_ypbw.jsonl` includes harness stages and recovery.
- `.runtime/bot-gfdwZV_ypbw.log` contains the application operation logs.
- `.runtime/telethon-recovery-gfdwZV_ypbw.json` marks the pilot complete.
- `.runtime/pilot-gfdwZV_ypbw-final-audit.json` records the final durable/log audit.
- `.runtime/pilot-downloads/reconciled-gfdwZV_ypbw.mp4` is the locally reconciled video.

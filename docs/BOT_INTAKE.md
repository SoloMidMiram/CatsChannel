# Authenticated bot submission intake

Issue #5 stops at a durable **pending** intent. It deliberately does not finalize
a logical post, publish to Telegram, moderate, or create a reply button.

```text
private admin /post or opaque reply deep-link
                 |
                 v
     source/exact-parent selection in FSM
                 |
                 v
 trusted local or Telegram-byte validation
                 |
                 v
       SubmissionIntakeService
          |              |
          v              v
 validated submission   immutable pending intent
          + private inbound projection
```

## Entry behavior

- `/post` and `/submit` start a fresh normal flow.
- `/start catreply_<opaque-token>` resolves an authorized internal thread and
  exact parent, then enters the same awaiting-media flow.
- The pilot remains private and admin-only. Callback data contains only internal
  UUIDs; raw Telegram coordinates and opaque tokens are not stored in FSM data.
- Normal Telegram-native media requires selection of an existing Telegram source
  thread. Verified direct-extractor media can resolve its source automatically.
- An authorized exact-parent flow may place Telegram media under a YouTube-source
  post. Its provider and unresolved provenance remain truthful, and the automatic
  source tail is untouched because intake does not finalize anything.

## Byte and cancellation boundary

Telegram videos are downloaded to a private temporary file through a writer that
enforces the configured byte limit. Declared and actual size are checked. FFprobe
metadata, duration policy, a video stream, and a complete FFmpeg decode are
required before a `ValidatedTelegramMedia` value exists. SHA-256 and bounded
evidence are computed from the actual bytes.

Cancellation signals the validation process token and drains the owned worker
before the temporary directory is removed. A newer command increments the flow
version; completed slow acquisition cannot persist or restore a superseded flow.

## Reconcile-first replay

The authenticated inbound `(chat_id, message_id)` private projection is the
replay key. Under an application-local lock, intake checks it before invoking the
acquisition callback:

1. No projection: acquire and validate once, issue a bound one-use handoff, and
   atomically persist the submission, private projection and consumed handoff.
2. Submission and intent exist: verify actor, conversation and placement, then
   return the existing pending result without acquisition.
3. Submission exists but intent is missing: verify the same ownership/placement,
   create only that intent, and return `recovered` without acquisition.
4. Any owner or placement mismatch: return `intake_conflict`; never transfer.

This handles a crash or database/service failure between the two short commits.
It does not claim cross-process serialization; durable uniqueness and conflict
checks keep a competing write observable.

## Local use

Enable persistence-backed reply entries, apply migrations, and start the bot:

```bash
uv sync --locked --all-extras
uv run --locked --extra persistence alembic upgrade head
uv run --locked cats-channel --bot
```

Required local settings include `BOT_TOKEN`, `ADMIN_USER_ID`, numeric
`CHANNEL_ID`, `DATABASE_URL`, and `REPLY_ENTRIES_ENABLED=true`. Keep `.env`,
database files, Telegram sessions, downloads, and cookies out of Git.

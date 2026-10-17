# Source-aware submission workflow

The submission phase accepts media only after acquisition and media validation.
It assigns a logical source, stores validation/provenance evidence, and returns an
internal submission ID. It does not create a post, choose a parent, publish to the
channel, or start moderation.

```text
MediaService / trusted Telegram adapter
              |
              | validated input (no database transaction)
              v
       source identity resolver
              |
              v
       SubmissionService
              |
              v
 PersistenceUnitOfWork (short transaction)
   submission + optional private projection + handoff consumption
```

## Input contracts

- `ValidatedLocalMedia` adapts a `LibraryItem` with explicit metadata, FFprobe and
  full-decode evidence, file integrity, acquisition backend, and provenance.
- `ValidatedTelegramMedia` carries a complete `(chat_id, message_id)` reference,
  downloadable `file_id`, stable Telegram `file_unique_id`, explicit validation
  evidence, and a required correlated handoff. A `file_id` alone is not accepted.
- Supported metadata is deliberately bounded: title, duration, dimensions,
  codecs, and container. Arbitrary extractor output is not persisted.

Acquisition and validation happen before `SubmissionService.submit()` opens a
unit of work. Repository objects never escape the unit-of-work context.

## Source identity

The resolver returns either `verified` identity with a stable provider/channel ID,
or `unresolved`. Direct yt-dlp channel metadata is trusted by the current library
resolver. Third-party downloader-bot captions, labels, requested URLs, names, and
usernames never upgrade identity to verified.

Unresolved media requires an explicit existing thread ID. That result is stored as
`user_selected`, remains distinguishable from verification, and must use the same
source provider. A selection does not choose a post, root, tail, or reply parent.
A conflicting manual selection cannot override verified identity.

Display name and username are snapshots. Null means absent and clears obsolete
thread metadata; the stable channel ID continues to own identity.

## Lifecycle and retries

This phase has one successful lifecycle state: `validated`. Future moderation,
publication, rejection, and retry transitions belong to later issues. Source media
uniqueness remains `(source_provider, source_media_id)` across every thread.

Expected failures use stable codes:

- `submission_media_invalid`
- `source_identity_unresolved`
- `source_identity_conflict`
- `source_selection_invalid`
- `duplicate_media`
- `handoff_invalid`
- `submission_persistence`

There are no automatic retries. A persistence failure is reconciled before one
explicit retry.

## Durable Telethon-to-aiogram handoff

`issue_handoff()` returns an opaque 256-bit token bound to the expected actor,
private conversation, operation, and expiry. Only its SHA-256 digest is stored.
Telegram-native submission atomically stores the submission/projection and marks
the handoff consumed in the same transaction.

Wrong actor, conversation, operation, expiry, and normal replay all return the
same safe `handoff_invalid` result. Atomic compare-and-set consumption permits at
most one submission. If commit success is ambiguous, call
`reconcile_handoff()` first:

- consumed returns the existing internal submission result;
- pending permits one explicit retry;
- invalid or expired is rejected.

Rollback leaves a pending token retryable and removes all partial submission
state. Raw tokens and private message bodies are excluded from persistence and
structured logs.

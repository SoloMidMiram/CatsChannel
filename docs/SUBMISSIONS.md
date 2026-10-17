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
- Telegram-native media always uses `source_provider="telegram"` and
  `source_media_id=file_unique_id`. Mismatches are rejected. A forwarded/copied
  file with another message coordinate or bot-specific `file_id` retains the same
  deduplication key. Re-encoded files with different unique IDs are different
  Telegram assets; this is not perceptual or cross-provider byte deduplication.
- Supported metadata is deliberately bounded: title, duration, dimensions,
  codecs, and container. Arbitrary extractor output is not persisted.

Acquisition and validation happen before `SubmissionService.submit()` opens a
unit of work. Repository objects never escape the unit-of-work context.

## Trusted adapter boundary

These validated dataclasses are internal assertions from trusted Python code,
not cryptographic certificates. Constructing them does not authenticate a file,
its original source, or the claimed decoder result. They must never be populated
by deserializing a Telegram message, callback, caption, or untrusted JSON object.
The request/service reject dictionary payloads and media/evidence of the wrong
contract type; successful decoding must be the boolean `True`, not a truthy
external string. These shape checks do not turn an untrusted constructor into a
trusted adapter.

The local adapter accepts only the `LibraryItem` returned by `MediaService` after
its real validation/cache-integrity path. A future Telegram adapter must obtain
the reference and actor/conversation from authenticated transport context, fetch
the bytes through the configured transport, run local media policy, inspection
and full decoding, and construct evidence from those actual results. It must
derive the media key from Telegram's `file_unique_id`, not user-provided text.
Neither the evidence nor a correlated handoff proves the original channel's
identity; that still needs the separate trusted resolver or manual selection.

This PR exposes no submission handler or external deserializer. Completing #3
and wiring a trusted Telegram validator are explicit gates before exposing the
submission/reply UI. Fake evidence in tests supplies the trusted adapter role;
it is not a production validation shortcut.

## Provenance persistence schema

`cats_channel/submission_provenance.py` owns strict nested schemas with unknown
fields forbidden. The service validates and snapshots media provenance and source
resolution evidence before opening a transaction; the repository validates the
assembled record again. Rejected values are not echoed in validation errors.

- Local media: relative library item path, enumerated acquisition backend,
  timezone-aware download timestamp, and an optional typed acquisition receipt.
- Receipt: backend, numeric bot/request/response IDs, false source-verification
  flag, and enumerated correlation method. Arbitrary captions/payloads are excluded.
- Telegram media: enumerated adapter and explicit operational file references.
- Resolution: enumerated status/method, adapter, and boolean trusted/stable-ID
  evidence. Adding a new method/field requires a schema review and regression.

Credentials, session data, private message bodies, raw external responses, and
arbitrary nested fields are rejected. Field allowlists prevent accidental payload
copies; they cannot detect deliberate secrets hidden in a legitimate identifier.
Operational file references are intentionally stored for delivery, not logged as
authentication credentials.

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

## PostgreSQL evidence

The dedicated `postgres` CI job uses a disposable PostgreSQL 16 service. It
executes 0001, seeds a legacy record, injects a 0002 migration failure and checks
transactional DDL rollback, upgrades to 0002, checks schema parity, and exercises
UoW rollback, source-media uniqueness, and competing handoff consumption.

The test is opt-in locally with `CATS_TEST_POSTGRES_URL` and
`CATS_TEST_POSTGRES_DISPOSABLE=1`. It requires a fresh loopback-only database/user
named `cats_test`. Never use a production database. The disposable CI result
does not validate production provisioning, permissions, backups, or deployment.

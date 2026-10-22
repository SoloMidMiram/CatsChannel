# CATS-004: source-aware submission preparation

Prepared on 2026-10-17. This is an implementation handoff, not implemented behavior.

## Baseline and sequence

- Base: merged PR #15, `0dca318848b886f6b77cddc127d32e5f265fbabf`.
- Prepared local branch: `feat/source-aware-submission` in
  `F:/Git/CatsCh/CatsChannel-aiogram-core`.
- Target: [issue #5](https://github.com/SoloMidMiram/CatsChannel/issues/5),
  CATS-004 Build cat submission workflow.
- Issue #4 is completed. Issue #3 remains open: its full acceptance criteria also
  include deep-link parsing, callback conventions, FSM reset, and lifecycle tests.
  Audit those items before depending on them. PR #14 established the factory and
  error boundaries; it did not establish completion of the whole issue.
- The older broad roadmap mentions publishing within submission. The current
  issue #5 explicitly excludes publication; use that focused boundary.
- Follow with #6 reply-chain behavior, then #7 publication, then #8 moderation.

## Deliverable for the next focused PR

A transport-independent submission service accepts explicitly validated input,
resolves trustworthy source identity or an explicitly selected existing logical
thread, and persists one internally identified submission with lifecycle,
validation, and provenance evidence. It does not create a post or choose a parent.

1. Define application input/result contracts for validated local `LibraryItem`
   media and Telegram-native references. Keep complete `(chat_id, message_id)`
   coordinates as external projections, never domain identity. Telegram-native
   references still require explicit validation evidence and policy checks;
   possession of a file ID alone is insufficient validation.
2. Model source identity status (`verified`, `user_selected`, `unresolved`),
   supported video metadata, validation evidence, media origin, and provenance.
   Verify stable channel IDs through a trusted adapter contract. Third-party
   downloader captions, labels, usernames, or requested URLs alone are not proof
   that returned bytes have that source identity. Preserve uncertainty rather
   than upgrading it to verified.
3. Require explicit selection of an existing internal thread when stable source
   identity is unavailable. Reject missing/unknown selection and conflicts with
   verified identity. A selection is user-selected provenance, not verified
   source identity. Selecting a thread does not choose its root/tail or a parent.
4. Add only the repository operations and migration needed to persist lifecycle,
   validation/provenance, and submission association. Reuse the single model owner,
   complete metadata-snapshot contract, source-media uniqueness, and explicit UoW.
   Decide/document a narrow lifecycle before coding; do not add moderation or
   publication transitions. Do not fabricate media IDs from mutable handles or
   confuse Telegram `file_id` with a stable original-source identity.
5. Define the Telethon-to-aiogram handoff as an explicit application contract:
   opaque one-use request token bound to the expected actor/source conversation
   and operation, with expiry and atomic consumption. Reject unrelated,
   mismatched, expired, and replayed responses. Keep token state durable if the
   handoff crosses processes or must survive restart; do not assume a process-local
   dictionary supplies that guarantee. Define retry behavior for repository failure
   so a transient failure cannot silently lose or double-accept a submission.
6. Keep acquisition/network work outside database transactions. Validate first;
   persist the submission, its provenance/projection, and any consumed handoff
   state together in a short UoW. Return an internal submission ID only after
   commit. Never keep a repository or session past UoW exit.
7. Add typed application errors and safe bot-facing adaptation for invalid media,
   unresolved/conflicting identity, duplicate media, invalid handoff, and
   persistence failure. Preserve cancellation and avoid automatic publication or
   blind retry loops. Tokens and private message bodies must not enter logs.

## Verification and review gates

- Verified identity and source rename preserve the intended stable source key.
- Removed public handles persist as null; reassigning them does not move identity.
- Manual selection is explicit and remains distinguishable from verification.
- Unresolved required identity and invalid media persist no partial submission.
- Both local-library and Telegram-native input contracts are exercised offline.
- Concurrent/replayed token consumption accepts at most one handoff; wrong actor,
  wrong conversation, expiry, and unrelated messages are rejected.
- Duplicate media are rejected across logical threads by database constraints.
- Repository/commit failure rolls back all submission-related state; defined retry
  behavior preserves one-use and idempotency guarantees.
- Migration upgrade, parity, failure rollback/retry, and offline PostgreSQL SQL
  generation pass; SQLite and PostgreSQL configuration remain supported.
- Test application behavior with fake repositories and real temporary SQLite;
  use real `Dispatcher.feed_update()` plus mocked transport for any new handler.
- Run full offline suite, Ruff, lock checks, and builds on the final revision;
  verify four CI jobs against that exact head. Keep baseline installation without
  the persistence extra working unless an explicit dependency change is intended.

## Exclusions and first implementation steps

No parent selection, root/tail advancement, deep-link reply behavior, channel
publication, inline buttons, moderation, Redis, production database provisioning,
performance tuning, or live service pilot belongs in this PR.

Start by auditing the relevant #3 prerequisites and current repository gaps, then
write failing submission/handoff contracts. Implement the domain service and
minimal migration before wiring transport adapters. If completing #5 requires a
separate remaining #3 core patch, identify that dependency explicitly rather than
claiming the merged core PR closed it. Do not close #3 or #5 until their actual
acceptance criteria are verified.

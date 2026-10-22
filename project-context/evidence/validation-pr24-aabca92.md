# Reply-chain domain PR #24 validation

Implemented the owner's pasted issue #6 specification as one focused PR:
https://github.com/SoloMidMiram/CatsChannel/pull/24

- Branch: feat/reply-chain-domain.
- Base: merged application core c9f2b20f717174eaaf47125b36d7c1ec012b2a0e.
- Initial implementation: fe37b305f640dd0e0ba2f3092d40384f29464d4e.
- Final head: aabca924e65d646395ce752993731c35543fb4f3.
- PR is open, non-draft and mergeable; issue #6 closes on merge.

## Implemented scope

Migration 0003 adds one-per-submission immutable placement intents with a
database mode/parent check, and reusable reply-entry tokens stored as SHA-256
digests. Normal intents select the current tail at finalization; interactive
intents retain the exact parent across waiting, later processing and restarts.
Roots initialize root/tail together; normal appends advance the logical tail;
older-post and nested branches do not. Root/tail membership, ancestry, cycles,
invalid lifecycle state, cross-thread parents and reused submissions are checked.

Post creation and optimistic root/tail updates share one transaction. A failed
CAS rolls back the inserted post. Keyed local locks serialize same-thread work,
allow different threads to overlap, release cancelled waiters and remove unused
entries. Shared cleanup ownership now drains UoW exit/session closure across
repeated cancellation before the service releases its thread lock.

The database-backed actor-aware resolver derives the thread from the post and
requires active token dates, valid ancestry and an unambiguous destination
projection. Unknown, invalid, expired, revoked, unauthorized and unavailable
entries return the same safe result. No raw token is persisted or logged.
The existing real dispatcher/FSM consumes internal IDs without graph decisions.
Explicit UoW injection or REPLY_ENTRIES_ENABLED=true enables persistent lookup;
the CLI owns database disposal and preserves operation/composition errors when
cleanup also fails. Baseline imports remain independent of persistence extras.

PlacedPost plus strict parent-projection preflight is the handoff to #7. No
Telegram API exists in the graph service. Domain finalization is logical placement,
not confirmed delivery; #7 must add durable publication state, delivery retry,
idempotency and reconciliation. No moderation UI or live media-entry adapter was
added. Python 3.11 remains the only supported runtime.

## Validation

- Final Windows Python 3.11 full suite: 330 passed, 32 skipped. The skips include
  29 opt-in PostgreSQL parameter cases, the existing opt-in migration test and two
  existing platform-specific skips.
- Ruff and formatting passed (112 files); lock consistency, offline sdist/wheel
  builds, whitespace and optional-dependency import smoke passed.
- Initial-head CI run 39059569370 passed Linux, Windows and actual PostgreSQL.
- Final-head CI run 39059649102 passed all three jobs: Ubuntu 3.11
  (117474794878), Windows 3.11 (117474795054), and disposable PostgreSQL
  (117474795107). The PostgreSQL job reports 60 passed in 12.64 seconds.
- The PostgreSQL CI job runs the shared graph/token/transaction/concurrency and
  dispatcher contracts on isolated schemas as well as migration 0001/0002/0003,
  injected rollback, retry, downgrade and schema parity checks.
- Local Docker PostgreSQL pull failed due to a registry TLS handshake error; no
  local test container was created. Actual PostgreSQL proof comes from CI.
- No live Telegram, YouTube or production-database calls were made.

No inline review threads were present at the final verification. Feature checkout
is clean and synchronized with origin/feat/reply-chain-domain (0 ahead/behind). Existing project-context changes remain
unstaged and separate on feat/project-memory. Next: review/merge PR #24, then #7
single-channel publication; moderation, authorized private pilot and measured
optimization follow. Do not repeat the completed core or reply-graph phases.

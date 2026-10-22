# Intake readiness after PR #26 merge

## Reconciled state

PR #26 merged at e0f9c2c6fe8aa483f0f9ee4a2c0a694342c05e98. Its final feature
head is 248fc63f3544bc43afcd6b7837f968505386e7a3, later than the initial 9294454
plan head. Final-head CI 39087800103 and merge CI 39087954845 passed all three
jobs: Linux Python 3.11, Windows Python 3.11 and disposable PostgreSQL.

Local main in CatsChannel-aiogram-core and the prepared feat/bot-submission-intake
branch in CatsChannel-bot-intake were fast-forwarded to the merge revision. Both
checkouts are clean. The intake branch remains local; no implementation commit
or remote intake branch was created. Its existing upstream is origin/main.
The separate feat/project-memory changes remain unstaged and preserved.

## Important final-head correction

The merged plan and live #5/#6 issues are narrower than the first plan draft:
normal automatic **and normal manual** appends remain source-matched. Only an
authorized exact-parent reply may place differently sourced media in the parent's
thread. A manual source selection is not a general cross-provider override.

Separate automatic source chains remain. A1 -> A2 -> A3 with user reply X under
A2 or A3 keeps A3 as normal logical tail. The next normal A4 attaches to A3,
never X. Replies to X can nest without moving the tail. B's chain is independent.
Logical placement and confirmed delivery remain separate as ADR-004 specifies.

## Implementation prerequisite: bounded #6 follow-up

#6 remains open and runtime still rejects Telegram uploads under YouTube-source
parents. Before wiring final #5 intake:

1. Make source persistence truthful: provider/media ID and source fields come
   from media/resolver evidence, never copied from a target thread to manufacture
   source identity. Preserve unresolved status when appropriate.
2. Make placement checks mode-specific. Normal automatic/manual placement stays
   source-matched. Interactive placement requires server-resolved, actor-authorized
   exact-parent context; a public boolean, arbitrary IDs or caller-supplied source
   labels cannot assert that authority.
3. Keep validation, deduplication, one post per submission, exact parent/thread
   membership and no-tail-advance for interactive branches unchanged.
4. Add regressions before the fix: Telegram -> YouTube exact reply succeeds with
   truthful stored provenance; normal cross-provider append still fails; invalid,
   stale or unauthorized targets fail; nested user replies never redirect A/B
   automatic tails. Test replay and migration/rollback if durable fields change.
5. Land/reconcile that bounded correction before final #5 integration. Do not
   treat merged planning documents as implementation of this prerequisite.

## #5 implementation handoff

Primary /post and optional /submit alias share one thin intake workflow. Bare
/post resets stale context and chooses an explicit normal source-matched target.
Opaque /start reply entry resolves and authorizes an exact parent, then directly
asks for media through that same flow. Reuse existing common/post/media/pilot
router boundaries, DI, admin/private authorization, flow leases, structured logs
and outer unexpected-error containment. No generic command plugin framework.

Before any new transfer, reconcile the actor-bound private inbound Telegram
projection. Recover an existing submission and query its intent by submission ID.
If only the intent is missing, create that intent without another transfer or
duplicate submission. Verify mode/target ownership; do not silently retarget a
replayed message. Acknowledgement failure must not erase committed durable state.

New input downloads actual Telegram bytes into owned temporary storage and uses
shared size/duration/stream/hash/full-decode validation before constructing trusted
evidence. Retain Telegram file_unique_id as provider-scoped media identity, curated
provenance and no raw transport data in FSM/logs. Keep cancellation/cleanup owned,
primary errors preserved and superseded flows unable to restore stale state.

The result is a validated submission plus one durable normal/exact-parent intent
and a **pending** acknowledgement. #5 does not call finalize_intent, send/copy to
the destination, moderate, create public reply tokens/buttons, change automatic
tails, or activate discovery. #7 handles confirmed publication; #8 moderation.

## Validation and pilot gates

Prepared intake checkout on Windows Python 3.11.4 using the existing local runtime:
334 passed, 36 skipped. This platform count differs from the earlier WSL baseline
335/35; no claim of a new failure is inferred from platform skips. Ruff check and
format (114 files), offline lock consistency, offline sdist/wheel builds passed.
No new dependency environment or local Docker service was needed.

Future #5 acceptance includes real dispatcher/fake Bot transport and temporary
database regressions for normal/exact entry, truthful cross-provider replies,
duplicate/replayed updates, submission commit before intent failure, no second
transfer, cancellation at each boundary, failed cleanup/acknowledgement and slow
replacement. Extend allowlisted phase/category/outcome/correlation logging and
redaction tests. Sanitized pilot incidents become offline failing regressions and
reviewed fixes; no autonomous policy learning or blind Telegram retry.

No live Telegram, YouTube or production-database calls were made. SQLite-first is
still a separate proposal, and Python 3.11 remains the sole supported runtime.

# Phase #5 readiness after PR #27 merge

## Reconciled state

PR #27 merged on 2026-10-18 at 02:11:06 UTC as
`f63d3825291388c07e7479358caf172bdd0e3d96`. The merge tree equals the
independently reviewed `c34d337d87c4a868902910a56ea00cd203836d25` tree.
Issue #6 is closed; issue #5 remains open for authenticated bot intake.
Merge CI run 39089183973 passed Ubuntu, Windows and PostgreSQL jobs.

Local main in `CatsChannel-aiogram-core` and branch
`feat/bot-submission-intake` in `CatsChannel-bot-intake` were fast-forwarded
from e0f9c2c to f63d382. Both working checkouts are clean. The intake branch
still tracks origin/main; no implementation commit or remote intake branch was
created. Separate project-context edits remain unstaged in feat/project-memory.
This handoff supersedes the prerequisite/status portions of the PR #26 handoff
and the original next-phase-cats004-intake-2026-10-18.md; preserve those as history.

## Bounded #5 outcome

Authorized private `/post` or opaque reply entry -> target selection when needed
-> actual Telegram bytes -> shared media validation -> SubmissionService
-> one immutable PostIntent -> pending acknowledgement.

- Retain admin/private access and Python 3.11. Optional `/submit` is one alias.
- Bare `/post` replaces stale context and explicitly chooses normal placement.
- `/start catreply_<opaque-token>` uses the actor-aware resolver, then enters
  the same awaiting-media workflow with the exact internal thread and parent.
- ReplyTarget is a trusted internal assertion, not a credential. Raw public IDs
  or an authorization flag must never construct authority at the bot boundary.
- Normal intake remains source-matched; exact replies may cross providers while
  preserving Telegram file_unique_id and truthful unresolved source provenance.
- User and nested replies never redirect a source's automatic tail. Intake
  itself does not finalize any intent or mutate logical tails.

## Implementation order and recovery gates

1. Add failing service/real-dispatcher regressions for both entries and partial
   commits before wiring handlers. Cover actor denial, revoked/expired entry,
   superseded flow, cancel, restart, invalid bytes and failed acknowledgement.
2. Design a durable intake operation/context before a submission can commit
   alone. Bind ownership, mode, thread and exact parent to a recoverable internal
   operation. FSM alone is insufficient after restart: the current submission
   records placement thread but does not preserve the selected exact parent.
   Reject replay with changed ownership/mode/parent rather than retargeting it.
   Choose the smallest persistence extension; add migrations/rollback checks if
   new fields or tables are needed. Do not claim the existing projection alone
   reconstructs a lost parent.
3. Add application-facing intent lookup by submission and safe private-inbound
   projection reconciliation. Before another transfer, recover the existing
   submission and intent. A committed submission with missing intent resumes
   only intent creation from its original durable authorized context.
4. Add a bounded Telegram byte adapter and shared local-media ingestion path.
   Current MediaService exposes URL acquisition/probe, so extend its shared
   validation/ownership boundary rather than pretending local intake exists or
   trusting Telegram metadata. Validate size, streams, duration, digest and full
   decode before constructing internal validation evidence. Clean owned files
   and drain workers on cancellation; never hold a transaction across transfer.
5. Orchestrate SubmissionService/handoff and ReplyChainService through a focused
   intake application service. Reconcile uncertain commit outcomes before any
   bounded repeat-safe retry; duplicate source media is not authority to reuse
   another actor's submission or an unrelated message's context.
6. Wire common/post/media/pilot router factories incrementally through existing
   DI, authorization, flow leases and outer error containment. Keep graph, SQL,
   acquisition retry policy and delivery decisions out of handlers. Preserve
   cancel/reset/replacement rules and prevent stale work from restoring state.
7. Extend allowlisted phase/outcome/category/correlation/duration/recovery logging
   and test redaction plus failed error responses. Sanitized pilot incidents
   become offline regressions and reviewed fixes, never autonomous policy changes.
8. Verify SQLite recovery, disposable PostgreSQL concurrency/migrations where
   applicable, real Dispatcher.feed_update with fake Bot transport, supported
   Python 3.11 CI, lint, format, lock, builds and documentation before a focused PR.

## Completion and exclusions

The acceptance gate is authenticated, validated media plus exactly one correct
durable pending intent, with repeat-safe recovery after every durable boundary
and no second transfer when an existing private projection identifies intake.
An acknowledgement failure cannot undo committed state. Keep the actual source
identity distinct from target placement throughout the flow.

No finalize_intent, destination send/copy, public token/button creation, moderation,
discovery activation, production deployment, backend switch or automatic live
retry belongs to #5. #7 publication follows, then #8 moderation and an explicitly
authorized private-channel pilot. SQLite-first remains a separate proposal.

## Fresh prepared-checkout validation

- Windows Python 3.11.4: 339 passed, 38 skipped (13.92 seconds).
- Ruff check and format: passed, 114 files formatted.
- Offline lock consistency: 55 packages; sdist and wheel builds passed.
- Merge CI: all three jobs passed in run 39089183973.
- No live Telegram/YouTube, production database or local Docker calls.

The initial sandbox uv cache write was denied; the offline lock/build checks
passed on rerun with existing-cache access. This did not change dependencies.

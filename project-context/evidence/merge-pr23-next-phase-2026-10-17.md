# PR #23 merge reconciliation and next phase

GitHub confirms PR #16 merged at 3ba1b2baa09d6567815969bf0129564a62cda47b.
PR #23 subsequently merged on 2026-10-17 at 18:27:14 UTC as
c9f2b20f717174eaaf47125b36d7c1ec012b2a0e. Issue #3 is closed.

The clean application checkout at CatsChannel-aiogram-core now uses main,
fast-forwarded to the same revision as origin/main. Its tree equals the reviewed
ace5af178c67e9eb4f57c7032011e34d88570b8d head. Final-head CI run 39057289843
and merge CI run 39058152067 both passed all three Python 3.11 jobs, including
disposable PostgreSQL. The merged Windows Python 3.11 suite passed with 295
tests and 3 skips. Existing project-memory checkout changes remain separate,
unstaged and preserved on feat/project-memory; that checkout was not reset.

## Completed foundations

- Media and optional Telethon backend, including safe diagnostics.
- Aiogram application core, owned lifecycle, cancellation cleanup, opaque reply
  entry and callback contracts, FSM replacement and regression coverage.
- Async persistence boundaries and migrations.
- Source-aware submission service, constrained provenance, canonical native
  Telegram identity and trusted evidence/handoff contracts.

Issue #5 remains open on GitHub, although its service acceptance audit is complete
in audit-cats004-acceptance-2026-10-17.md. Administrative acceptance/closure is
separate from implementing future live transport entry adapters. Issue #2 is
also still open. No issue was closed by this reconciliation.

## Next focused implementation: issue #6

Implement a transport-independent reply-chain domain over the existing UoW:

1. Stable source thread identity, explicit first root and canonical tail.
2. Normal append selects the current tail; interactive replies retain the exact
   selected parent, including older posts and nested branches.
3. Only confirmed normal append publications advance the automatic tail;
   interactive branches do not redirect the source feed. Define the domain
   transition API now; Bot API effects remain issue #7.
4. Reject missing/cross-thread parents and invalid lifecycle transitions;
   enforce projection availability at the publication boundary.
5. Implement actual opaque-token resolution against internal graph targets,
   using the merged actor-aware resolver/FSM contract.
6. Cover competing append attempts, interleaved sources in one destination,
   renamed sources, root/linear/nested replies and invalid transitions offline.

Keep Bot API publication, moderation UI and distributed locking out of this PR.
Do not repeat the completed application-core work.

Then implement #7 single-channel publication, reply buttons, idempotency,
per-thread serialization and reconciliation; #8 moderation; an authorized
end-to-end private pilot; then #9 measured optimization/production hardening.
Before exposing live submission handlers, add the trusted native-media adapter
that fetches and validates actual bytes through the existing media service.
Redis requires a concrete need. Discovery epic #17 remains a separate stream.

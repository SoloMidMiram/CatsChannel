# Review approval PostgreSQL gate correction

PR #36 at `b3106c71c37e93c643c40426270838eabb7bac88` passed both OS
jobs but failed PostgreSQL job `121357138605` in run `40255762772`.
The job log confirms 124 passed, 1 skipped, 1 failed: the final head assertion
still expected `0005_durable_publication` after migration 0006 had run.
This was an assertion failure, not a database connection failure.

The correction expects `0006_review_approval`, inspects the migrated
`review_items` columns, and keeps Alembic metadata parity checks. An injected
failure after creating `review_items` additionally verifies transactional
rollback to migration 0005, followed by successful upgrade and downgrade/re-upgrade.

The review suite now shares the existing isolated SQLite/PostgreSQL fixture and
is explicitly selected by the PostgreSQL CI job. Existing service and dispatcher
tests therefore run against both databases. Additional PostgreSQL-only delivery
and approval tests synchronize two independent transactions after reading the
same version, require exactly one conditional ownership winner, verify the stored
audit actor, and retain conservative restart states without replaying sends.
Barrier waits and the competing transaction group have bounded timeouts.

Pre-push local validation: focused WSL suite 17 passed, 17 skipped (PostgreSQL
not configured); lint/format passed. Local PostgreSQL image acquisition failed
at Docker Hub authentication with EOF. The new exact-head GitHub PostgreSQL job
is required before declaring this gate green; local skipped tests are not proof
of PostgreSQL behavior.

The 65-file root staging snapshot is excluded from this change. No live Telegram
sends or approval callbacks were generated. Issue #8 remains open. The restricted
pilot uses one private channel for review and publication; public deployment
requires a separate private review destination, as documented in
[review configuration](../REVIEW_APPROVAL.md). This deployment boundary is not
currently enforced by configuration validation.

# Audited rejection

This implementation extends the existing review service and version-aware callback
router; it does not add a second moderation subsystem or change public access.
Apply migration `0007_review_rejection` before running this revision.

Each new review has Approve and **Reject: unsuitable** actions. Only the configured
admin may use either. Rejection validates the stored review chat, message,
destination and pending version, then competes with approval using the same
database decision ownership. The current UI records the fixed safe reason
`unsuitable`; the application API additionally accepts `rights`, `duplicate` and
`other`. Arbitrary text is rejected, not stored or echoed as a reason.

The existing review row records the terminal decision, action, actor, timestamp,
version and bounded reason. The same transaction marks the submission `rejected`,
so later pilot publication cannot treat it as validated. Rejection refuses an
already logically placed item. It creates no logical post, publication or media
send. Approval winning the pending claim excludes rejection; rejection winning it
excludes later approval. Restart recovery touches only abandoned sending/approving
operations and never changes rejected decisions.

After commit the callback removes actionable controls and displays terminal
status. A failed edit or callback answer cannot reverse the decision. An existing
consumed handoff bound to a private submitter conversation permits one best-effort
submitter notification after commit. Missing/untrusted handoff means no notification.
Its failure is logged using a safe category; duplicates do not repeat notification
or a decision. This is not a durable notification outbox or a delivery guarantee;
operator notification recovery remains separate.

Migration 0007 adds `decision_action` and `rejection_reason` and allows the rejected
decision state. Existing audited approvals are backfilled as approve actions.
Downgrade refuses while rejected review rows exist, rather than deleting their
audit or converting rejection into pending/approval. No SQL transaction spans
Bot API operations. Back up and plan compatibility before any operator upgrade;
this PR performs no live migration, bot restart or publication.

Tests: `test_review_approval.py` covers real dispatcher callbacks, denial,
duplicate/approval competition, PostgreSQL simultaneous claims, rollback,
restart, failed markup/callback and failed submitter notification, plus absence
of logical posts/publications/media sends. `test_publication_migrations.py` covers
schema parity, DDL rollback and refusal of lossy rejection downgrade. Existing
publisher, hosted-media and PostgreSQL migration suites remain gates.

Public inspection/publication isolation is a separate Issue #8 slice and remains
a release blocker. This change alone does not establish full moderation acceptance
or public readiness.

## Rejection and direct pilot placement ownership

Review thread discussion_r4481215039 identified a race between rejection and the
explicit pilot publication boundary. Both rejection and intent finalization now
lock the submission row in their existing transaction before checking placement
or eligibility. PostgreSQL uses a row lock. SQLite retains its transaction snapshot and
rejects a competing stale snapshot write. Neither path changes the timestamp. The lock ends at commit or rollback, before
any Telegram operation. If rejection commits first, finalization reads rejected
status and refuses placement. If placement commits first, rejection finds the
post and refuses the decision. Migration 0007 is unchanged.

Barrier regressions in test_review_approval.py exercise both transaction orders
on PostgreSQL using the real publication service. The rejection-first test failed
on the prior implementation in CI run 42040284311, retaining evidence of the race.

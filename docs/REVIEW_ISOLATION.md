# Review/publication startup isolation

This independent Issue #8 slice changes startup policy, not moderation decision
ownership or intake authorization. No live configuration or permissions are changed.

For the persistent product flow (`REPLY_ENTRIES_ENABLED=true`), configure a
negative numeric `CHANNEL_ID`, a negative numeric `REVIEW_CHANNEL_ID` and the
existing authorized `ADMIN_USER_ID`. There is no fallback from a missing inspection
destination to publication. The default `REVIEW_ISOLATION_MODE=separate` rejects
equal destinations before any API lookup.

Before polling, the application performs bounded read-only identity/channel/member
checks. Inspection must be a private channel (no public username or active username
aliases); publication may be public or private. Both destinations must resolve
to their configured numeric IDs, be channels, and permit the bot to post and edit.
A lookup failure, timeout, insufficient permission or unverifiable privacy prevents
polling. No send, edit, webhook change or permission mutation tests access.

For a separately authorized restricted experiment only, set
`REVIEW_ISOLATION_MODE=private_pilot`. Both destinations must then be verified
private, even if distinct. This permits equal private destinations; it never
permits a public inspection copy. Intake authorization remains the existing
configured-admin policy. This mode is not public deployment approval.

`--bot-diagnose` applies the same policy to its read-only report. Preflight is
point-in-time verification, not sustained health monitoring. Every fresh startup
rechecks configuration and permissions. Failure precedes dispatcher polling and
startup recovery; owned resources still close through the existing cleanup boundary.
Legacy nonpersistent admin media utilities with review disabled gain no implicit
review destination.

Existing configurations enabling the product flow without an explicit review
destination must be corrected before restart. No automatic live restart occurs.
Historical same-channel pilot receipts remain evidence; that setup requires the
explicit private-pilot mode with this revision.

`test_review_isolation.py` covers distinct destinations, public inspection,
same-channel rejection/default, explicit private-pilot mode, missing/invalid values,
permissions, lookup/timeout/redaction, returned identity, fresh configuration
changes and actual application startup without mutation during failed startup.
Existing transport/lifecycle tests retain their separate ownership contracts.

This slice does not finish review recovery, acknowledgement, host supervision,
backup/restore or sustained public-operation acceptance. Public release remains
blocked by the other #8/#9 gates even after this PR is reviewed.

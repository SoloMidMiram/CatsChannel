# Post-pilot reconciliation - 2026-11-02

## Independently inspected baseline

Remote main: 54e88b0ec80ee0538c5b9cf673c2c96d73cd0dff.
PR #36 merged at 43db2b43e618f50d354d7327c6cd966fc947c7c8;
#37 at 728e87c76e86ff331b75592d02f3d26ed2af8aa2; #38 at main above.
PR #39 is open at 3b3101070cc59180c2ebc78a8802188ea63c33dc.
Its four-file diff contains a receipt, context record/source and generated overview.
No credentials, tokens, private file identifiers, raw logs, media bytes or runtime
artifacts were found in that diff. Review/publication services and dispatcher tests
support the described approval ownership and hosted metadata path.

## Recorded evidence

[PR #39 receipt at reviewed head](https://github.com/SoloMidMiram/CatsChannel/blob/3b3101070cc59180c2ebc78a8802188ea63c33dc/docs/evidence/telegram-hosted-private-acceptance-2026-11-01.md)
records 23,220,422 bytes, 171 seconds, confirmed private review, actual admin
approval, exactly one confirmed attempt, message 1232 replying exactly to 1230,
zero getFile/download/decode, full_decode=false and sha256=null. It records removal
of the approval button, installation of the publication reply button, clean poller
shutdown and later intake rejection by the temporary one-item observer guard.
These are inherited recorded observations, consistent with inspected code/tests.
Underlying ignored observer/audit/read-back artifacts were not located this session.
No Telegram operation, live send, service restart or deployment was performed.
Historical failed experiments remain retained.

PR #39 CI run 41339863014 passed Ubuntu, Windows and PostgreSQL at its reviewed
head. GitHub reports CLEAN, no formal reviews and an empty review decision.
Protection and active-rules reads both returned HTTP 403 with the GitHub plan
restriction: Upgrade to GitHub Pro or make this repository public to enable this
feature. Full merge-policy qualification remains unverified; #39 is left open.
No approval or branch-protection bypass was manufactured.

## Issue disposition

| Issue | Before | Reconciled result |
| --- | --- | --- |
| #1 | Open; intake next | Open; #5 closed, publisher/approval implemented, release incomplete |
| #7 | Open; exact-parent pilot pending | Open; exact-parent/button recorded; navigation, acknowledgement and recovery acceptance remain |
| #8 | Open; moderation absent | Open; approve-only implemented; rejection/isolation/recovery remain |
| #9 | Open; older pilot requirements | Open; operational qualification retained |

Review caption and admin callback updates do not prove submitter publication
acknowledgement. A single attempt is not duplicate-interaction stress acceptance.
Native child-to-parent reply is recorded; full navigation interaction is unproven.

Highest priority: authorized rejection in the existing durable review boundary.
Dispatcher/fake transport and SQLite/PostgreSQL tests must prove one audited
terminal decision, zero logical placement/publication/send, safe approve/reject
races, stale/unauthorized/replayed callbacks, rollback/restart behavior and failed
notification without replay. Then enforce public isolation and startup permission
safeguards. Discovery and optional #35 do not gate this core slice.

## Local validation

Locked all-extras sync, Ruff lint/format, context validation/generation and Git
whitespace checks passed. Full Windows Python 3.11.4 suite: 669 passed, 92 skipped,
1 failed: existing resolver symlink test raises WinError 1314 (host lacks symlink
privilege). No runtime change or test workaround was introduced. Exact-head CI
is reported separately on the documentation PR.

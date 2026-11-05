# Disposable backup and restore qualification

This test-only reliability slice is based on main
`98bd841c3e2271056ee183c7b6b5f2b85f18f683`, including merged PR #42 audited
rejection and PR #43 startup isolation. Its diff contains backup/recovery tests,
the existing CI gate extension and documentation/context records. It qualifies
disposable fixtures; production recovery remains an operator acceptance task.

`tests/test_backup_restore.py` creates only synthetic submissions, a confirmed
publication/projection, an ambiguous send and a terminal rejected review. All
transactions commit and fixture connections close before backup.

- SQLite: use sqlite3 backup into a separate temporary file, check database/FK
  integrity, then open a fresh Database against the restored file.
- PostgreSQL: only the explicitly disposable loopback cats_test database/user is
  accepted. Dump one fixture-owned `reply_<uuid>` schema with pg_dump, drop only
  that schema, and restore it with pg_restore. The schema is validated before
  deletion. Credentials are supplied via process environment, never argv/logs.
  CI runs the matching pg_dump/pg_restore binaries inside its existing PostgreSQL
  16 service and streams the archive over stdin/stdout. Local host-client runs
  must use a compatible client/server pair. The first CI attempt exposed a newer
  runner pg_restore emitting transaction_timeout against server 16; that failed
  attempt remains recorded rather than being ignored or retried unchanged.
- Fresh service instances recover abandoned work and verify audit/version/reason,
  rejected submission ineligibility, absent rejected placement, unknown attempt
  identity and confirmed Telegram projection. Replayed publication/approval must
  not send media or change rejection.

The fixture uses the current ORM schema. Actual Alembic migration and rollback
compatibility remain independently tested in the existing SQLite/PostgreSQL
migration suites; this test does not claim a production schema migration rehearsal.
Stopped writers are a precondition, not a discovered distributed lock. The test
does not prove host supervision, online backups, point-in-time recovery or live
Telegram outcomes. Those remain explicit operational acceptance work in #9.

The existing PostgreSQL CI job includes this file; no new service/job is added.
The PostgreSQL case skips when no disposable URL is configured. A configured
PostgreSQL qualification must provide pg_dump/pg_restore and the explicit safe
fixture flags; it fails rather than silently skipping a missing backup tool.
No durable notification outbox or ambiguous-send automatic retry is introduced.

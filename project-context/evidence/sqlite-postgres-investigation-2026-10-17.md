# SQLite versus PostgreSQL investigation

The owner asked whether PostgreSQL can be replaced by the available SQLite to
reduce development, Docker and test overhead. This investigation makes no runtime
or CI changes and records a recommendation, not an approved platform migration.

## Origin and current usage

Commit c392e09's environment document already recommended PostgreSQL for production
and SQLite for local tests, before persistence implementation. PR #15 implemented
async SQLAlchemy/UoW and Alembic for both. PR #16 review fix c2998a2 added the
Docker PostgreSQL CI job because actual PostgreSQL migration/concurrency proof was
missing from the production support claim. PR #24 extends that job with graph and
token contracts. This is a support-policy choice, not a Telegram/aiogram requirement.

SQLite is already the DATABASE_URL default and implements the same submissions,
threads/posts, projection, handoff, intent and token schema. No PostgreSQL-only
JSONB, advisory lock, SKIP LOCKED or similar dependency was found in the current
persistence/domain implementation. asyncpg is currently bundled into the optional
persistence extra alongside aiosqlite; it need not run a server to be installed.
The ordinary local suite skips PostgreSQL unless its disposable URL is supplied.

## New local evidence

On PR #24 head aabca924e65d646395ce752993731c35543fb4f3, all 29 SQLite
reply-chain parameter cases passed, with 30 other cases deselected. No Docker or
PostgreSQL server was involved.

An isolated temporary SQLite database reported journal_mode=delete,
busy_timeout=5000, foreign_keys=1. A controlled pair of different-source graph
finalizations reached insertion concurrently: one succeeded and one returned
reply_chain_unavailable. Retrying the failed intent in a fresh transaction
succeeded. The current per-thread coordinator therefore does not eliminate
database-wide SQLite writer contention. Existing tests explicitly permit/retry
that losing SQLite writer; PostgreSQL requires both transactions to succeed.

## Recommendation awaiting owner decision

Use SQLite as the current single-process, single-host pilot database on local
persistent storage. Keep SQLAlchemy/Alembic and the current graph contracts. Before
calling it the deployment baseline, coordinate short writes across services,
define bounded busy/conflict retries, verify cancellation/rollback behavior, and
document backup/restore and durable filesystem placement. Consider WAL as part of
read/write concurrency configuration, without assuming it enables multiple writers.

Make PostgreSQL an optional future backend with manual/opt-in CI, split asyncpg
into a PostgreSQL extra and correct docs that currently imply production always
requires it. Revisit PostgreSQL for multiple independent writers/processes/hosts
or measured database contention. Removing its CI promise is distinct from moving
data out of an existing PostgreSQL database; no such data migration was performed.

Official SQLite page inspection was attempted through
mcp__playwright_global__browser_navigate and failed with
net::ERR_SSL_VERSION_OR_CIPHER_MISMATCH. No browser substitute was used; findings
above are based on repository history, inspected code and local executable tests.

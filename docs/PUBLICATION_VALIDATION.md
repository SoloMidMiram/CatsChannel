# Issue #7 implementation evidence — 2026-10-22

Starting branch: `feat/telegram-publication`. Starting HEAD, merge-base and remote
main were all `5f5ddfe19f1c73906e487023e5983377512b9e0c` (merged PR #28).
The worktree was clean and had no publication implementation. Existing worktrees
were preserved. No dependency, lockfile or runtime-policy upgrade was made.

## Final local gates

| Environment | Command | Result |
| --- | --- | --- |
| WSL, Python 3.11.16 | `uv sync --locked --all-extras` | Passed |
| WSL, Python 3.11.16 | `uv run --frozen pytest -q` | **416 passed, 60 skipped**, 46.94 s |
| Windows, Python 3.11.4 | `uv sync --locked --all-extras --python C:\Users\cebit.ir\.pyenv\pyenv-win\versions\3.11.4\python.exe` | Passed |
| Windows, Python 3.11.4 | `uv run --frozen pytest -q` | **415 passed, 61 skipped**, 26.29 s |
| Both | `uv run --frozen ruff check .` | Passed |
| Both | `uv run --frozen ruff format --check .` | Passed, 141 files |
| Both | `uv lock --check` | Passed |
| Both | `uv build` | Passed, sdist and wheel |
| WSL Git | `git diff --check` | Passed |

WSL used `UV_PROJECT_ENVIRONMENT=.venv-wsl` and `TMPDIR=/tmp`. Native Linux temporary
files avoided the reported DrvFS capture issue; normal pytest capture worked and
`-s` was unnecessary. Windows used `UV_PROJECT_ENVIRONMENT=.venv-windows` and a
workspace-local `UV_CACHE_DIR`. Initial sandboxed Windows execution encountered
cache-access/network restrictions; authorized execution outside the sandbox passed.
The two OS runs above omit opt-in PostgreSQL cases; PostgreSQL coverage is below.

Focused migration/publication/production-adapter regression command:

```bash
uv run --frozen pytest tests/test_publication.py tests/test_aiogram_publisher.py tests/test_publication_migrations.py -q
```

Result: **44 passed, 23 skipped**, 19.48 s (WSL, no PostgreSQL configured).
Existing intake, dispatcher, persistence, reply-chain and lifecycle tests also ran
in the full suites. No original tests were removed. The legacy ambiguous-projection
fixture explicitly removes the new index in its isolated test schema so its
defensive read behavior remains tested; current-schema uniqueness is separately
enforced and tested. Lifecycle fakes now expose the startup recovery query.

## Disposable PostgreSQL 16

A task-owned `postgres:16-alpine` container exposed only
`127.0.0.1:55437`, with disposable database/user `cats_test`. A fresh database is
required by the existing migration test. One repeat accidentally reused its legacy
seed and failed with duplicate `legacy` primary key; recreating only this disposable
database fixed the fixture precondition. No application-code change was needed.

```bash
export CATS_TEST_POSTGRES_URL=postgresql+asyncpg://cats_test:disposable@127.0.0.1:55437/cats_test
export CATS_TEST_POSTGRES_DISPOSABLE=1
export UV_PROJECT_ENVIRONMENT=.venv-wsl TMPDIR=/tmp
uv run --frozen pytest tests/test_postgres_persistence.py tests/test_reply_chains.py tests/test_publication.py tests/test_publication_migrations.py -q
```

Final result: **123 passed, 1 skipped**, 53.57 s. The skip is the PostgreSQL-only
concurrent-writer test's SQLite variant; SQLite stale-CAS rejection is tested
separately. This runs actual migration rollback/schema parity, uniqueness,
transaction failure, simultaneous PostgreSQL claims, graph and delivery incidents.
CI's disposable PostgreSQL job now includes the publication/migration tests.

## Behavioral evidence and limits

Tests cover root/linear/older-parent/nested/interleaved placement, truthful
cross-provider replies, blocked/unblocked and missing parent projections, deleted
parent API rejection without fallback, replay, owned/stale/concurrent claims,
known rejection, post-effect timeout/disconnect, repeated cancellation with awaited
uncertainty, abandoned sending, post-send commit failure, invalid coordinates,
legacy projections, operator reconciliation and explicit requeue. They also cover
markup failure/restart/token replacement without resend, destination-only navigation,
safe logs, admin restrictions and real `Dispatcher.feed_update()` routing from
`/post` intake to pilot approval, projection, working token and acknowledgement.

All Telegram transport in tests is fake. No live publication, channel permissions,
real Telegram file acceptance, production PostgreSQL provisioning or live pilot
was verified. CI status and human review are separate from this local evidence.
One application process is supported. Unknown outcomes require independently
verified operator evidence. Token rotation invalidates copied older managed links
and may temporarily leave a stale button until repair. Migration fails rather
than choosing among duplicate legacy projections. Durable moderation, reviewer
audit and approve/reject UI remain Issue #8.

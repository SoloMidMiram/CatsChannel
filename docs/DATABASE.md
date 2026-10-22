# Persistence foundation

CatsChannel has one asynchronous SQLAlchemy model owner and ordered Alembic
migrations. SQLite supports local contract tests; PostgreSQL is the production
configuration target. Production provisioning and deployment are intentionally
outside this phase.

## Domain records and projections

```text
CatThread (stable source_provider + source_channel_id)
    ├── root_post_id / canonical tail_post_id / optimistic version
    └── CatPost (thread_id, optional parent_post_id)
            └── CatVideoSubmission (stable source_provider + source_media_id)

TelegramMessageRef = (chat_id, message_id)
    └── projection for a post or an unposted submission

MediaHandoffRequest
    └── token digest + actor/conversation/operation/expiry + one submission
```

Internal UUIDs own domain identity. A Telegram message ID is never accepted or
stored without its chat ID. A source display name and username may change without
changing the thread selected by the stable provider/channel key. Source-media
uniqueness is independent of thread identity, so moving or renaming a source does
not permit duplicate ingestion.

Submissions persist a source identity status, source display snapshot, narrow
`validated` lifecycle, bounded video metadata, validation evidence, media origin,
and curated provenance. The second migration adds these fields and the durable
handoff table. Raw handoff tokens are never stored.

Migration `0004_bot_submission_intake` adds nullable durable placement fields to
submissions. New intake rows store `normal_append` with no selected parent, or
`interactive_reply` with an exact parent. Legacy rows remain null and unchanged.
The matching immutable `post_intents` row is created separately; this enables
recovery after a committed submission without repeating media transfer.

Migration `0005_durable_publication` adds `publications` and `publication_attempts`.
Each post/destination pair has one versioned delivery state, current owned attempt,
independent markup state, managed token digest and latest confirmed direct-reply
pointer. Attempts retain claim ownership, number, timestamps, outcome and safe
recovery categories. A partial unique index permits at most one destination
projection per `(post_id, chat_id)`; Telegram coordinate uniqueness is retained.
SQLite and PostgreSQL share these constraints. Duplicate legacy projections fail
upgrade without choosing or deleting data. Downgrade removes publication history
and the new index, retaining logical posts/projections and existing reply tokens.
Do not downgrade during active publishing. See `PUBLICATION_CONTRACT.md` for
exclusive-process operator recovery and the sending/unknown no-resend policy.

`get_or_create(SourceIdentity(...))` treats display fields as a complete current
snapshot: `None` clears a stored name or username. This removes obsolete public
handles when a channel becomes private, even if the old handle is reassigned.
Use `get(thread_id)` for a lookup that leaves display metadata unchanged.

The root and tail IDs deliberately avoid circular database foreign keys back to
`cat_posts`; repository operations validate that each referenced post belongs to
the thread. Root and tail are initialized as a pair. Tail changes require both the
expected tail and expected version, making stale writers observable as
`ConcurrentThreadUpdateError`. Cross-process serialization belongs to later
publishing/hardening phases.

## Transaction boundary

Application services own transactions explicitly:

```python
database = Database.from_settings(settings)

async with database.unit_of_work() as uow:
    thread = await uow.threads.get_or_create(source)
    submission = await uow.submissions.create(
        source_provider="youtube",
        source_media_id=video_id,
    )
    post = await uow.threads.add_post(
        thread_id=thread.id,
        submission_id=submission.id,
        parent_post_id=thread.tail_post_id,
    )
    # initialize_root(...) or advance_tail(...) belongs in this same transaction.
```

Repositories flush but never commit. A successful unit-of-work exit commits; an
exception rolls back. SQLite uses explicit transaction control so repository
savepoints cannot accidentally escape the outer unit of work on Python 3.11.

Repository access belongs inside the unit-of-work context. Exit permanently
closes its session and clears repository/transaction state, so retained repository
references cannot start another transaction. Re-entering an exited unit of work
creates fresh repositories; entering it again while active is rejected.

## Configuration and migrations

Install the optional dependencies and apply the tracked migration:

```bash
uv sync --locked --extra persistence
uv run --locked --extra persistence alembic upgrade head
```

The local default is:

```dotenv
DATABASE_URL=sqlite+aiosqlite:///cats_channel.sqlite3
```

PostgreSQL must use the async driver:

```dotenv
DATABASE_URL=postgresql+asyncpg://USER:PASSWORD@HOST/DATABASE
```

Synchronous and unsupported driver URLs are rejected. Treat the complete URL as a
secret because it may contain credentials. Tests may call
`Database.create_schema_for_tests()` for isolated in-memory/temporary schemas;
application environments must use Alembic rather than metadata `create_all()`.

Online SQLite migrations use the same explicit `BEGIN` hooks as application
transactions, and Alembic treats SQLite DDL as transactional. A failed or
interrupted upgrade rolls back its schema changes and unapplied revision so the
upgrade can be retried. PostgreSQL keeps Alembic's native transaction behavior.

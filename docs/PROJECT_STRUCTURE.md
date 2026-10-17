# Current application boundaries

```text
cats_channel/
  bot/
    application.py   # composition root and polling lifecycle
    context.py       # per-update operation middleware
    errors.py        # safe response and unexpected-error boundary
    handlers.py      # current private admin router
  services/
    media_service.py # validated acquisition boundary
  submissions/
    entities.py       # explicit validated-media, source, handoff, and result contracts
    resolvers.py      # trusted source-identity adapter policy
    library_adapter.py # LibraryItem to submission input adapter
    service.py        # source assignment and atomic submission decisions
    errors.py         # typed application rejection
  adapters/          # process, cookie, validation, and Telethon integrations
  persistence/
    entities.py       # transport/ORM-independent persistence records
    contracts.py      # repositories and application unit of work
    models.py         # single SQLAlchemy model owner
    repositories.py  # async query and invariant implementation
    database.py       # engine/session lifecycle and transaction owner
    errors.py         # stable persistence failure categories
  diagnostics.py     # deterministic classification and safe structured logging
  errors.py          # stable error/retry policies
alembic/              # tracked application schema migrations
```

Aiogram objects stop at the handler boundary. `MediaService` receives ordinary
application values and returns a validated `LibraryItem`. The application factory
injects only dependencies that its current pilot needs. Persistence is a separate
application-service boundary and is not coupled to the current admin handlers.

Tests mirror these boundaries and exercise routing through the real dispatcher.
Source submission tests use both fake repository contracts and real temporary
SQLite. No submission handler is invented before its product UX is specified.

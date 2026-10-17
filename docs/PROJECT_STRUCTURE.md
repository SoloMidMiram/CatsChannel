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
  adapters/          # process, cookie, validation, and Telethon integrations
  diagnostics.py     # deterministic classification and safe structured logging
  errors.py          # stable error/retry policies
```

Aiogram objects stop at the handler boundary. `MediaService` receives ordinary
application values and returns a validated `LibraryItem`. The application factory
injects only dependencies that currently exist; repository interfaces are added
with the persistence feature rather than speculatively.

Tests mirror these boundaries and exercise routing through the real dispatcher.

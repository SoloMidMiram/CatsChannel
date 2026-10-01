# Initial Architecture

```
src/
  app/              # startup and dependency wiring
  telegram/         # aiogram routers, callbacks, filters
  cats/             # cat domain services and entities
  moderation/       # review workflow
  persistence/      # database models and repositories
  tests/
```

Boundaries:

- Telegram handlers never contain business decisions.
- Services do not depend on aiogram objects.
- Repositories do not know Telegram APIs.
- Telegram message references are stored as external projections.

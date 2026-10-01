# CatsChannel

Telegram cat-video reply-chain bot.

## Mission

Build a scalable Telegram bot that manages cat video submissions, publishing, reply chains, moderation, and future community features without coupling domain logic to Telegram transport details.

## Architecture principles

- Python-first modern async stack
- aiogram 3 based Telegram layer
- domain logic separated from handlers
- Telegram message IDs treated as external references, not primary identities
- persistence behind repositories
- observable workflows with tests and structured logging

## Development

```bash
uv sync
uv run pytest
uv run ruff check .
```

See `docs/ROADMAP.md` for execution phases.

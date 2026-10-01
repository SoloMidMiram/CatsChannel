# CatsChannel

Telegram cat-video reply-chain bot.

## Mission

Build a scalable Telegram bot that manages cat video submissions, publishing, reply chains, moderation, and future community features without coupling domain logic to Telegram transport details.

Social owns the reply chain. `thread_id` and `parent_id` are the domain graph. Telegram coordinates are a `TelegramMessageRef` (`chat_id`, `message_id`). «دیوار ناشناس» is a behavioral reference for deep links and native replies, not a module to copy.

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

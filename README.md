# CatsChannel

Telegram cat-video reply-chain bot.

For the optional Telethon path that receives videos from `@whatsmusicbot`, see
[`docs/TELEGRAM_DOWNLOADER.md`](docs/TELEGRAM_DOWNLOADER.md).

An admin-only integration example is available now. See
[`docs/QUICKSTART.md`](docs/QUICKSTART.md) for Python 3.11 setup, secrets,
YouTube probing/downloading, Telegram commands, and the upgrade plan.
Persistent command-line downloads use the self-contained layout documented in
[`docs/MEDIA_LIBRARY.md`](docs/MEDIA_LIBRARY.md).
Async persistence contracts and migrations are documented in
[`docs/DATABASE.md`](docs/DATABASE.md).
The source-aware submission service is documented in
[`docs/SUBMISSIONS.md`](docs/SUBMISSIONS.md).
For the current project brief, decisions and source-linked evidence, start with
[`project-context/overview.md`](project-context/overview.md). See
[`project-context/README.md`](project-context/README.md) for focused context selection.

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
uv sync --locked
uv run --frozen pytest
uv run --frozen ruff check .
uv run --frozen python tools/project_context.py validate
uv run --frozen python tools/project_context.py generate --check
```

See `docs/ROADMAP.md` for execution phases.

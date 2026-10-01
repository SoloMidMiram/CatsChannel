# API Boundaries

External:

- Telegram Bot API, behind a client the Social service awaits

Internal:

- Social handlers (routing)
- Social services (decisions)
- Social repository (persistence)
- `TelegramMessageRef` and submission schemas

Handlers do not pass aiogram objects into services. Repositories do not call Telegram.

## Deep link and callbacks

Defined once in `src/social/callbacks.py`:

- `/start cat_<opaque-token>` on a URL button
- `catreply:<internal-id>`
- `catmod:approve:<submission-id>`
- `catmod:reject:<submission-id>`

The opaque token resolves to an internal post or thread. Callback payloads do not carry Telegram user ids or message ids. A button has one of `url` or `callback_data`.

Channel chat, moderation chat, and bot username come from settings.

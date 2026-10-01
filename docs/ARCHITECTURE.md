# Architecture

Social owns cat-video submissions, reply threads, and their moderation workflow.

«دیوار ناشناس» on TelegramBot-FirstGen (`35eea1b8c641915f59dd2a2d6e1fa1e1f0d545b2`, `nevermore/src/post.py` and `message.py`) is behavioral reference only. Keep its topology: public message, deep link, private submission, Telegram-native reply, stored message coordinates. Leave its all-in-one module behind.

## Conflict with the previous layout

The bootstrap tree was:

```text
src/
  app/
  telegram/
  cats/
  moderation/
  persistence/
```

The wall inspection assigns this feature to Social and requires `handler → service → repository/client`. A top-level `cats/` package would be a parallel subsystem. This document follows the inspection. `src/app/` remains the composition root.

## Package

```text
src/app/                 # startup, settings, logging, wiring
src/social/
    handlers.py          # Telegram routing
    service.py           # thread and moderation decisions
    repository.py        # persistence
    states.py            # FSM, internal ids only
    callbacks.py         # one deep-link and callback contract
    schemas.py           # entities and TelegramMessageRef
```

A `src/social/cat_reply/` subpackage waits until this package is too small for the feature.

Handlers extract Telegram input and call the service. Services do not accept aiogram objects. Repositories do not call the Bot API. A Telegram client, used by the service, owns API calls. One shared async session factory lives in app wiring; Social does not create a private engine.

## Identity

```python
@dataclass(frozen=True)
class TelegramMessageRef:
    chat_id: int
    message_id: int
```

`thread_id` and nullable `parent_id` are the domain graph. `(chat_id, message_id)` is only the Telegram projection. Source, published, and moderation messages are separate refs. `reply_to` uses the parent's published ref.

## Flow

```text
/start cat_<opaque-token>
  → handler validates token
  → FSM stores internal parent id and thread id
  → user sends a cat video
  → CatReplyService.submit(...)
  → repository creates the submission
  → publisher sends the video (reply_to parent when this is a reply)
  → repository stores the returned TelegramMessageRef
  → user is acknowledged
```

Publish, the reference write, and the acknowledgement are one awaited service call. Do not schedule that work with `asyncio.create_task`.

Moderation, in its own phase, is an explicit insert:

```text
submission → moderation chat → approve/reject → service → publish or stop
```

The moderator message is a `TelegramMessageRef`. It is not `thread_id`. Chat and bot identities come from configuration. `@AfsarieCh` is not a queue.

## Callbacks

Public channel buttons are URL-only:

```text
/start cat_<opaque-token>
```

Internal actions:

```text
catreply:<internal-id>
catmod:approve:<submission-id>
catmod:reject:<submission-id>
```

aiogram 3 `CallbackData` may encode the same fields. A button sets `url` or `callback_data`, not both. Tokens and callback ids are internal. They are not Telegram user ids or message ids.

## Failures and privacy

Services raise typed errors. The handler edge logs them and returns a generic message. Persistence uses async sessions (`asyncpg` / `aiosqlite`). Private submission bodies are not copied into a global private-message log, and unmatched private messages are not forwarded to a hard-coded channel.

## Issue reconciliation

CatsChannel has 9 open GitHub issues. Issue bodies are not readable with the available GitHub integration (HTTP 403). The in-repo issue map matches phases 0–5 and does not ask for naked message ids or an all-in-one handler. The package-layout conflict above is resolved in favor of the inspection.

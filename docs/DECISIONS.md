# Architecture Decisions

## ADR-001

Use aiogram 3 and async Python.

## ADR-002

Use service/repository boundaries. Social owns the cat-video reply chain. Flow is handler → service → repository/client.

## ADR-003

Store Telegram message references separately from domain relationships. `thread_id` and `parent_id` are the truth. `TelegramMessageRef` is `(chat_id, message_id)` only.

## ADR-004

Treat «دیوار ناشناس» as behavior to preserve (deep link, Telegram-native `reply_to`, FSM for the next video, record the published message). Do not reuse `post.py`: no all-in-one module, no naked message ids, no raw user or message ids in callbacks, no hard-coded channel or bot names, no `@AfsarieCh` moderation queue, no synchronous ORM in async handlers, no fire-and-forget publish.

## ADR-005

Public reply buttons are URL deep links (`/start cat_<opaque-token>`). Internal callbacks use internal ids (`catreply:`, `catmod:approve:`, `catmod:reject:`) or aiogram 3 `CallbackData`. One button action field.

## ADR-006

Publish, persist the returned `TelegramMessageRef`, and acknowledge the user in one awaited service call.

## ADR-007

Package the feature as `src/social/` (`handlers`, `service`, `repository`, `states`, `callbacks`, `schemas`). This supersedes the bootstrap split of top-level `src/cats/` and `src/moderation/`, which conflicted with Social ownership in the wall inspection.

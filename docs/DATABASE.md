# Data Model Plan

Core names, kept from the original data-model plan and aligned with the wall inspection:

- CatThread — stable `thread_id`. Not a Telegram chat.
- CatVideoSubmission — a cat video post, including replies
- CatReply — the same row shape when `parent_id` is set; not a second graph
- ModerationDecision — approve/reject audit; does not define the thread
- TelegramMessageRef — `(chat_id, message_id)` projection

## Relationship truth

```text
CatVideoSubmission.parent_id → CatVideoSubmission.id
CatVideoSubmission.thread_id → CatThread
```

Telegram message ids are not edges.

## Submission fields

- id
- thread_id
- parent_id (nullable internal parent)
- author_user_id
- source_chat_id, source_message_id
- published_chat_id, published_message_id
- telegram_file_id, telegram_file_unique_id
- status
- created_at

A moderation message, when phase 4 exists, is another TelegramMessageRef on the moderation record. It is not `thread_id`.

## Conflict note

The first data-model note listed CatThread, CatReply, and TelegramMessageRef as peer tables without saying which graph is true. The inspection's constraint wins: `thread_id` / `parent_id` are the domain truth, and `(chat_id, message_id)` is only the Telegram projection. CatThread stays as the thread identity already named here. It does not replace `parent_id`.

Never store a naked message id. Channel, source, and moderation chats are different chats, so each reference includes `chat_id`.

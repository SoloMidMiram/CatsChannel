# Data Model Plan

Core entities:

- CatVideoSubmission
- CatThread
- CatReply
- ModerationDecision
- TelegramMessageRef

Telegram message IDs are projections:

(chat_id, message_id)

They are not domain identities.

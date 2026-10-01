# Initial Feature Scope

Included, in roadmap order:

- cat video submissions
- publishing as an awaited step that records a TelegramMessageRef
- reply chains (deep link, `thread_id` / `parent_id`, Telegram-native reply)
- moderation as an explicit later gate

Preserved from «دیوار ناشناس» (behavioral reference only):

- deep-link entry into the private bot
- Telegram-native reply references
- FSM while the next video is collected

Rejected from that implementation:

- all-in-one `post.py`
- naked message ids
- raw user or message ids in callbacks
- hard-coded channel or bot names
- `@AfsarieCh` as the moderation queue
- synchronous ORM in async handlers
- fire-and-forget publish

Deferred:

- recommendations
- AI classification
- analytics
- monetization
- a `cat_reply/` subpackage before `src/social/` needs one

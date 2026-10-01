# Issues

Issues are tracked in GitHub. The repository reports open issues; this checkout's GitHub integration cannot read issue bodies (HTTP 403).

Until those bodies are available, `ISSUE_PLAN.md` and `ROADMAP.md` are the execution contract. They already match the anonymous-wall inspection: Social ownership, deep-link entry, Telegram-native replies, `thread_id` / `parent_id` as domain truth, and `TelegramMessageRef` as the only Telegram coordinates.

Do not file follow-up issues that reintroduce `post.py`'s shape, naked message ids, raw ids in callbacks, hard-coded channel names, `@AfsarieCh` as the queue, synchronous ORM in handlers, or fire-and-forget publish.

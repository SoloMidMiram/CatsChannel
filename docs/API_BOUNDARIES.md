# API Boundaries

External:

- Telegram Bot API
- optional Telethon user session and configured downloader bot
- yt-dlp/FFmpeg subprocesses

Internal:

- aiogram handlers translate Telegram updates and responses
- `MediaService` owns validated acquisition decisions
- adapters own external protocols and process lifecycles
- persistence protocols expose domain records and explicit units of work
- SQLAlchemy repositories own queries and constraints but never commit

Avoid passing Telegram or SQLAlchemy objects into domain services. Pass complete
`TelegramMessageRef(chat_id, message_id)` values across the persistence boundary;
never pass a naked Telegram message ID.

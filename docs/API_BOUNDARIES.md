# API Boundaries

External:

- Telegram Bot API
- optional Telethon user session and configured downloader bot
- yt-dlp/FFmpeg subprocesses

Internal:

- aiogram handlers translate Telegram updates and responses
- `MediaService` owns validated acquisition decisions
- `SubmissionService` owns source assignment, lifecycle acceptance, and atomic
  submission/handoff decisions
- source resolvers decide whether stable source metadata is trustworthy
- adapters own external protocols and process lifecycles
- persistence protocols expose domain records and explicit units of work
- SQLAlchemy repositories own queries and constraints but never commit

Avoid passing Telegram or SQLAlchemy objects into domain services. Pass complete
`TelegramMessageRef(chat_id, message_id)` values across the persistence boundary;
never pass a naked Telegram message ID.

Acquisition and validation finish before a submission unit of work begins. The
current submission phase exposes application contracts only. The aiogram core
separately defines reply deep-link/callback conventions and private entry/reset
state; these do not accept media, choose a parent, moderate or publish a post.

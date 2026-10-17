# API Boundaries

External:

- Telegram Bot API
- optional Telethon user session and configured downloader bot
- yt-dlp/FFmpeg subprocesses

Internal:

- aiogram handlers translate Telegram updates and responses
- `MediaService` owns validated acquisition decisions
- adapters own external protocols and process lifecycles
- future repositories will own persistence when their concrete contracts exist

Avoid passing Telegram objects into domain services.

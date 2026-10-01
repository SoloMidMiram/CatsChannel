# Issue Execution Map

1. Foundation bootstrap
2. Telegram application core (deep-link and callback contract, no database in handlers)
3. Cat submission domain (async repository, TelegramMessageRef, awaited publish)
4. Reply-chain implementation (`thread_id` / `parent_id`, native Telegram reply)
5. Moderation workflow (explicit gate, configuration-backed chat, audit record)
6. Production hardening

Each issue should produce a small verifiable increment and avoid mixing infrastructure with product behavior.

Social owns steps 3–5. Do not open an issue that revives an all-in-one handler, naked message ids, raw ids in callbacks, hard-coded chats, synchronous ORM, or background publish.

GitHub lists 9 open issues on this repository. Their bodies were not readable here (integration HTTP 403), so this map remains the execution contract. Where a future issue disagrees with the wall inspection's architectural constraints, prefer the inspection and record the conflict in the issue.

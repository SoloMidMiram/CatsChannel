# Implementation Order

1. Foundation (`src/app/`, `src/social/` skeleton)
2. Telegram core (lifecycle, routers, callback/deep-link contract)
3. Persistence contracts (async repository, TelegramMessageRef, submission fields)
4. Cat submission (awaited validate → persist → publish → record ref → ack)
5. Reply chains (token to `thread_id` / `parent_id`, `reply_to` parent ref)
6. Moderation (status gate, then the same publisher)
7. Deployment

Avoid implementing product flows before boundaries exist. Reply publish reuses the submission publisher from step 4.

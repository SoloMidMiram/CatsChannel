# Bootstrap TODO

Completed:

- generated and validated `uv.lock`
- Python 3.11 runtime baseline and CI gate
- runnable admin-only bot and YouTube integration spike
- offline configuration, downloader and safety tests
- shared CLI/Telegram acquisition service and validated media library
- bounded Windows/POSIX subprocess ownership and cancellation cleanup
- async persistence repositories, unit of work, and initial Alembic migration
- source-aware validated submission service and durable one-use media handoff
- aiogram owned lifecycle, deep links, callback/FSM and reset contracts (#3, PR #23)
- durable reply intents/tokens, root/append/branch graph and concurrency rules (#6, PR #24)

Next:

- #5: connect authenticated bot intake and shared media validation to submission
  and durable normal/exact-parent intent services; preserve source selection
- #7: deliver approved logical posts with durable publication states, confirmed
  parent projections, reply buttons and ambiguous-send reconciliation
- prove the bot-triggered intake/approval/publication vertical slice with fake
  transport; the manual `/publish` utility is not this product flow
- #8: add the durable moderation queue and auditable approval/rejection workflow
- run live smoke tests against a private Telegram test channel and an approved video
- #9: measured optimization and operational hardening after the authorized pilot

See [PUBLICATION_CONTRACT.md](PUBLICATION_CONTRACT.md). Logical placement/tail
advancement is implemented; confirmed Telegram delivery is a separate next phase.

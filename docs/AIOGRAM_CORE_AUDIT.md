# Aiogram core acceptance audit

Issue #3 acceptance is implemented by the application-core refactor plus this
entry/lifecycle completion. The tests below provide offline evidence; issue
closure belongs to acceptance/merge of the completing PR.

| Issue #3 item | Current evidence | State |
| --- | --- | --- |
| Bot token and one destination channel | `Settings` and existing bot tests | Complete |
| Network-free application factory | `create_bot_application()` and dispatcher tests | Complete |
| Safe error middleware and cancellation | router error boundary and regression tests | Complete |
| Owned startup/shutdown lifecycle | `BotApplication.start_polling`, `ApplicationDispatcher`, `test_bot_lifecycle.py` | Complete |
| Public reply deep-link convention/parser | `entry.py`: canonical opaque payload, URL builder, injected authorized target resolver | Complete |
| Moderation callback-data convention | `ModerationCallback`: allowlisted action and canonical internal UUID | Complete |
| FSM internal-ID/reset conventions | `flow.py`: typed internal IDs, explicit reset/cancel/replacement and stale-resolution isolation | Complete |
| Offline acceptance regressions | `test_bot_entry_contracts.py`, `test_bot_lifecycle.py`, existing dispatcher tests | Complete |

The factory constructs a Bot, dispatcher and router without network calls. Its
owned polling lifecycle drains accepted updates before closing FSM storage,
unwinds resource contexts in reverse order, and closes its bot session exactly
once, including startup failure and repeated caller cancellation. A borrowed bot
passed to the legacy `start_polling(bot)` form remains caller-owned.

The default reply resolver rejects unavailable tokens; future reply-domain code
supplies the authorized token-to-target lookup. A successful injected resolution
sets an entry context containing internal IDs only. This defines the transport
contract without implementing submission, parent selection, publication, or a
moderation action. Public reply tokens are distinct from #5's durable one-use
media-handoff tokens. No product completion is inferred for #5-#8.

See [entry/lifecycle contracts](AIOGRAM_ENTRY_CONTRACTS.md) for ownership, state,
token, callback and shutdown semantics. Private handlers remain admin-only.

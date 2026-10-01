# Known Risks

- Telegram API changes
- media storage growth
- moderation abuse
- duplicate submissions
- message reference drift (published ref stored without the matching publish)
- orphaned channel messages if publish is detached from persistence
- naked message ids reused across channel, moderation, and private chats
- callback payloads that embed user ids
- hard-coded chat usernames drifting from configuration
- FSM cleared by a new `/start` without a test that locks the intended reset

«دیوار ناشناس» shows the last four in the reference implementation. This project does not inherit them.

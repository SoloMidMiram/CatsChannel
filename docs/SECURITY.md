# Security Baseline

- Never store bot tokens in repository files.
- Do not expose user identities in public workflows.
- Keep moderation actions auditable.
- Validate all media and callback inputs.
- Put internal ids or opaque tokens in callbacks and deep links, never Telegram user ids or message ids.
- Load channel, moderation chat, and bot username from configuration.

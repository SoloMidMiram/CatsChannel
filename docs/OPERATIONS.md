# Operations

For explicit Bot API proxy configuration, read-only connectivity/webhook/permission
checks, and the isolated private pilot procedure, see
[BOT_API_TRANSPORT.md](BOT_API_TRANSPORT.md). `--bot-diagnose` performs no sends or
webhook changes; require a confirmed private destination before the first pilot.

Before production:

- PostgreSQL migration
- secrets management
- backup policy
- deployment workflow
- rollback procedure

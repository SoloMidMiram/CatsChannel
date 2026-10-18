# Implementation Order

Merged foundations: Python 3.11/CI, aiogram core, persistence, source-aware
submission service and reply-chain domain (#2/#3/#4/#6 and PR #16).

Remaining delivery order:

1. #5 bot intake and durable source/parent intent integration.
2. #7 single-channel publication, durable delivery state and reconciliation;
   prove the bot-triggered slice with an explicit authorized pilot approval policy.
3. #8 durable moderation queue and audited actions over that same intent/flow.
4. Authorized private-channel pilot, measured optimization and hardening (#9).

The boundaries exist; the next work must connect them into usable bot behavior.
See [PUBLICATION_CONTRACT.md](PUBLICATION_CONTRACT.md). Issues are tracked in GitHub.

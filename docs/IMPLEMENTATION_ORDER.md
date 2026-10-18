# Implementation Order

Merged foundations: Python 3.11/CI, aiogram core, persistence, source-aware
submission service and reply-chain domain (#2/#3/#4/#6 and PR #16).

Remaining delivery order:

1. #6 bounded follow-up: authorized placement versus actual media provenance;
   retain separate automatic chains per source, and test cross-provider replies.
2. #5 modular `/post` intake and durable source/parent intent integration.
3. #7 single-channel publication, durable delivery state and reconciliation;
   prove the bot-triggered slice with an explicit authorized pilot approval policy.
4. #8 durable moderation queue and audited actions over that same intent/flow.
5. Authorized private-channel pilot, measured optimization and hardening (#9).

Safe logging and pilot incident-to-regression coverage are acceptance gates for
each phase, not a deferred infrastructure project. See
[BOT_POSTING_PLAN.md](BOT_POSTING_PLAN.md) for modular command and error boundaries.

The boundaries exist; the next work must connect them into usable bot behavior.
See [PUBLICATION_CONTRACT.md](PUBLICATION_CONTRACT.md). Issues are tracked in GitHub.

# Implementation Order

Merged foundations: Python 3.11/CI, aiogram core, persistence, source-aware
submission service and reply-chain domain (#2/#3/#4/#6 and PR #16).

Remaining delivery order:

The bounded #6 follow-up is complete: exact-parent placement is separate from
actual media provenance, while normal append remains source-matched.

1. #5 modular `/post` intake and durable source/parent intent integration is complete.
2. #7 single-channel publication, durable delivery state and reconciliation;
   prove the bot-triggered slice with an explicit authorized pilot approval policy.
3. #8 durable moderation queue and audited actions over that same intent/flow.
4. Authorized private-channel pilot, measured optimization and hardening (#9).

Safe logging and pilot incident-to-regression coverage are acceptance gates for
each phase, not a deferred infrastructure project. See
[BOT_POSTING_PLAN.md](BOT_POSTING_PLAN.md) for modular command and error boundaries.

The intake boundary is usable and deliberately stops at `pending`; #7 is next.
See [PUBLICATION_CONTRACT.md](PUBLICATION_CONTRACT.md). Issues are tracked in GitHub.

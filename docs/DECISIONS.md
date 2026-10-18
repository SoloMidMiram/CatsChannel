# Architecture Decisions

## ADR-001

Use aiogram 3 and async Python.

## ADR-002

Use service/repository boundaries.

## ADR-003

Store Telegram message references separately from domain relationships.

## ADR-004 — Logical placement and external delivery

Keep the merged #6 logical placement transaction unchanged: normal finalization
advances `CatThread.tail_post_id`. Issue #7 owns separate durable publication
states and confirmed Telegram projections. A child waits for confirmed parent
delivery; an ambiguous send requires reconciliation and never a blind retry.
See [PUBLICATION_CONTRACT.md](PUBLICATION_CONTRACT.md) for the implementation
contract. Publication state and full bot intake/moderation are not implemented yet.

## ADR-005 — Source chains and interactive media provenance

The owner confirmed separate automatic chains per stable source in one destination.
Retain `CatThread`; do not migrate to a global `ChannelFeed`. An authorized exact
reply may contain media from another provider and stays in the selected parent's
thread without moving its tail. This is a mode-specific exception: automatic and
manual normal appends remain source-matched. Actual media provenance must not be
relabeled as the target source, and an exact-parent placement must not manufacture
verified source identity. A bounded #6 follow-up was required because provider
matching originally rejected Telegram uploads under YouTube-source posts. That
correction is implemented with mode-specific validation and an internal
`authorized_reply_target` input; `/post` intake remains planned. See
[BOT_POSTING_PLAN.md](BOT_POSTING_PLAN.md) for command, error, pilot regression and
dependency details.

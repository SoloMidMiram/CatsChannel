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
thread without moving its tail. Actual media provenance must not be relabeled as
the target source. #6 needs a bounded follow-up because current provider matching
rejects Telegram uploads under YouTube-source posts; the broader rule is planned,
not implemented. See [BOT_POSTING_PLAN.md](BOT_POSTING_PLAN.md) for command, error,
pilot regression and dependency details.

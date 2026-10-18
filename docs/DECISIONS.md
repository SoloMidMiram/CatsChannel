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

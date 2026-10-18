# Reply-chain domain (#6)

The v1 graph and bounded provenance/placement correction are implemented. Separate
source chains remain authoritative, while a Telegram-uploaded reply may sit under
an exact YouTube-source parent without being relabeled as YouTube media. This
exception does not apply to normal automatic or manual appends. Target thread and
parent are placement data and never overwrite or verify media-source fields. See
[BOT_POSTING_PLAN.md](BOT_POSTING_PLAN.md) for the intake plan.

`ReplyChainService` makes graph decisions through repository/UoW protocols;
it imports neither aiogram nor SQLAlchemy and never calls Telegram. One source
provider and stable channel ID identify one `CatThread`, even if its display name
changes. Destination coordinates are optional projections, never graph identity.
All public graph arguments are canonical internal UUIDv4 strings.

## Durable decisions

Migration `0003_reply_chain_domain` adds `post_intents` and `reply_entry_tokens`.
Intents are immutable and unique per submission. The database mode/parent check
requires normal intents to have no selected parent and interactive intents to
have one. Normal intents require validated source-matched submissions with verified
identity or explicit same-provider source selection. Interactive intents also
accept validated unresolved or differently sourced media assigned through an
authorized exact target. They never infer or rewrite a source from captions,
usernames or target-thread metadata. Pending, cross-thread and reused submissions
are rejected with typed, safe errors.

`create_normal_intent(submission_id, thread_id)` defers parent selection.
`create_interactive_intent(submission_id, thread_id, selected_parent_post_id)`
stores the exact parent durably, including an older post or an interactive branch.
Moderation may retain the intent ID and finalize that same intent later; it must
not reconstruct the parent from the current tail or mutable FSM data.

`finalize_intent(intent_id)` serializes per thread, reloads the intent/submission
and current graph in a fresh transaction, and returns `PlacedPost(post_id,
thread_id, parent_post_id, advances_tail)`. A normal root initializes both root
and tail; subsequent normal posts attach to and advance the current tail.
Interactive posts keep their exact parent and never change the canonical tail.
Root/tail membership, ancestry, cross-thread parents, cycles, disconnected roots
and invalid lifecycle state are checked before insertion. Finalizing twice fails
with `reply_intent_conflict`; the original post is not duplicated.

Post insertion and root/tail compare-and-set share one transaction. A stale
version returns `reply_chain_conflict` and rolls back the inserted post. The
application-local keyed coordinator releases cancelled holders/waiters and
removes unused lock entries. Share the coordinator between service instances in
one application. Different source threads use different locks. SQLite remains a
single-writer development backend: concurrent writes across threads may need
caller retry after a typed `reply_chain_unavailable`; PostgreSQL can run those
transactions concurrently. There is no distributed locking or hidden retry.

## Opaque reply entry

`issue_reply_token(post_id, expires_at=None)` generates 256 random bits using the
shared PR #23 token helper. Only SHA-256 of the canonical 43-character token is
stored. The raw token is returned once to the trusted caller for link building
and excluded from dataclass representations. Tokens are reusable, independently
revocable and distinct from one-use submission handoffs. No token text is logged.

`DatabaseReplyTargetResolver(service, authorize_actor=...)` validates syntax,
looks up the digest, checks dates/revocation, derives the thread from the post,
checks ancestry, authorizes the actor and requires an unambiguous destination
projection in the configured numeric chat. Every unavailable or unauthorized
entry returns `None`, including storage/authorization failure; cancellation
propagates. Missing, wrong-chat, private-only and ambiguous projections fail
closed. Authorization is explicit and never granted by possession of a token.

`create_bot_application(..., persistence_unit_of_work=db.unit_of_work)` composes
this resolver with the existing admin/private-chat policy; handlers and FSM
behavior are unchanged. Alternatively inject a resolver with a different explicit
actor policy. Injecting a UoW borrows the database; its owner disposes it after
draining the application.

For the CLI path, install the persistence extra, run `alembic upgrade head`, set
numeric `CHANNEL_ID`, and set `REPLY_ENTRIES_ENABLED=true`. `run_bot` then owns and
disposes the database after bot shutdown. The flag defaults to false so baseline
installs remain offline-capable without optional persistence dependencies.
Enabling lookup does not expose submission media handlers or moderation actions.

## Publication boundary (#7)

Finalization commits a **logical placement**, not successful Telegram delivery.
`CatThread.tail_post_id` is the logical canonical tail. Confirmed delivery uses
separate durable publication state; it does not defer or repeat this tail update.
This phase intentionally advances the logical normal tail at domain finalization
as specified by #6. It adds no publication status, outbox, sender, copying,
reconciliation or delivery guarantee. #7 must coordinate placement with its
durable publication state/retry policy; calling finalization again is not a
delivery retry and rolling the tail backward after external effects is unsafe.

Before delivery, call `require_parent_projection(post_id)`: roots return `None`;
children return their exact parent's destination coordinates or fail with
`reply_parent_unpublished`. `finalize_intent(..., require_parent_projection=True)`
can enforce the same availability before committing a placement. A pending
unpublished parent must block child publication, never cause an unthreaded send.
The publisher consumes these decisions and performs no parent/tail selection in
handlers. Telegram `ReplyParameters`, delivery idempotency and reconciliation are
the next focused PR.

The normative #7 state transitions, parent-confirmation gate, ambiguous-send
recovery, post-confirmation button attachment and bot integration gates are in
[the publication contract](PUBLICATION_CONTRACT.md). These are planned publisher
requirements, not implemented delivery guarantees.

## Evidence

`tests/test_reply_chains.py` runs the same contracts on isolated SQLite databases
and opt-in disposable PostgreSQL schemas. CI runs both platforms on Python 3.11
and actual PostgreSQL, including migrations, rollback/retry, graph concurrency,
token safety and mocked-transport `Dispatcher.feed_update()` entry/replacement.
There are no live Telegram/YouTube calls. Migration downgrade removes the two new
tables and therefore their intents/tokens; older submissions/posts are retained.

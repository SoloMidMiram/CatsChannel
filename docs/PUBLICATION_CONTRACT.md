# Publication contract for issue #7

Durable publication and the explicit admin pilot are implemented by migration
`0005_durable_publication`, `publication/`, and the aiogram transport adapter.
The merged #6 graph keeps its existing semantics. Approve-only review is implemented in PR #36; complete moderation remains #8.

The owner confirmed one automatic chain per stable source, not one global channel
feed. Authorized reply-button media may have a different truthful provenance while
remaining in its exact selected parent's thread; normal append remains source-
matched. The #6 correction and #5 intake are implemented. Command
modularity and pilot error-to-regression gates are in
[BOT_POSTING_PLAN.md](BOT_POSTING_PLAN.md). Serialization and tail blocking below
are per source thread; a blocked A chain does not reroute or block healthy B.

## Logical placement and confirmed delivery

`finalize_intent()` commits an internal `CatPost` and, for a normal append, advances
`CatThread.tail_post_id` in the same transaction. This is the **logical canonical
tail**, not the last Telegram-confirmed post. Interactive branches do not advance
it. Normal intents choose that logical tail only at finalization; exact-parent
intents retain the selected post throughout waiting and moderation.

Issue #7 must never reinterpret this field as delivery state or roll it backward
after a failed/ambiguous send. Publication owns a separate durable record, unique
per `(post_id, destination_chat_id)`. A returned Telegram message and its confirmed
projection establish delivery. If a confirmed-feed cursor is needed later, it
must be separate from the graph tail.

| Publication state | Meaning and permitted next action |
| --- | --- |
| `pending` | Approved logical placement awaits an eligible send. |
| `blocked` | Its exact parent lacks confirmed destination delivery; no send. |
| `sending` | An owned attempt was durably claimed before the external call. |
| `confirmed` | A successful Telegram result and destination projection were durably recorded together. Never resend the media. |
| `failed` | Delivery is known not to have happened. Only explicitly safe retries may be scheduled. |
| `unknown` | Delivery may have happened. Reconcile; never automatically resend. |

These publication states are independent of submission validation and
moderation decisions. Pending moderation does not finalize a placement. Rejection
before approval creates no logical post. Approval finalizes once, then requests
publication for that immutable post.

## Parent gating and recovery

Before sending a child, require its exact internal parent's publication to be
`confirmed` and its unambiguous projection to exist in the configured destination.
Use that projection through `ReplyParameters`. `require_parent_projection()` is
the existing graph preflight; the publisher adds the durable delivery-state check.
Missing/deleted projections block or fail safely. Never send without the intended
reply, skip to an older confirmed post, silently reparent, or create a new root.

An unpublished logical tail may therefore have blocked descendants. Confirmation
can unblock them. A failed parent needs a known-safe retry; an unknown parent
needs reconciliation. Any irrecoverable graph repair is an explicit audited
operator decision, not an automatic transport fallback. Serialization and unique
attempt/projection ownership must prevent concurrent or duplicate sends.

No database transaction can atomically commit a Telegram send. A timeout,
connection loss, cancellation or crash after dispatch, or failure to persist a
successful result, leaves an unknown outcome unless evidence proves otherwise.
On restart, an abandoned `sending` attempt requires reconciliation. Reconciliation
must record the confirmed message reference, prove non-delivery before requeueing,
or retain `unknown` for operator action. Post finalization is never a send retry.

The publisher uses one owned, awaited workflow, persists confirmed state and
projection in one local transaction, then acknowledges the result. A local commit
failure after external success must not trigger another media send.

## Reply buttons after confirmation

Existing token issuance requires a confirmed destination projection. Preserve
that guard: send the media, durably confirm its returned projection, then issue
the reusable reply token and attach the URL button to that known message.
Track/retry button attachment separately; a failed markup edit must not resend
the media or turn a known media delivery into an unknown media outcome.

## Bot integration and delivery sequence

The current `/download` and manual `/publish` commands remain pilot utilities.
They do not implement the product submission, moderation or publication workflow.

1. **#5 intake:** authenticated media -> hosted metadata policy or local byte validation ->
   `SubmissionService` -> durable normal/exact-parent intent. Preserve existing
   admin/private restrictions until an explicit access-policy change.
2. **#7 publisher:** consume approved intents/placed posts through an application
   boundary; implement delivery states, parent gating, buttons and reconciliation.
   Prove a bot-triggered path with an explicit authorized pilot approval policy.
3. **#8 moderation:** replace that bounded pilot policy with a durable approval
   queue and auditable approve/reject actions, preserving the same intent.
4. Authorized private-channel pilot, then measured optimization/hardening (#9).

The vertical slice must connect real dispatcher routing to these services using
fake Telegram transport before any live pilot. More models alone do not complete
intake or publication. Discovery #17 remains independent. The SQLite-first option
is a separate proposed decision; this reconciliation changes no database policy.

## Implemented pilot and ownership

Enable the existing persistent application with `REPLY_ENTRIES_ENABLED=true`,
apply `uv run --frozen alembic upgrade head`, and configure a numeric `CHANNEL_ID`.
The configured admin can use `/pilot_publish <submission-id>` in a private chat.
This command explicitly approves only that validated submission's durable intent.
It never reads a parent from FSM state. This is a temporary authorization policy,
not durable moderation or an approval queue. Inspect third-party media before
approving it; approval does not verify its original source identity.

`PublicationService` reconciles the submission's existing post before finalizing
an intent, then creates/retrieves its unique publication. One shared application
coordinator serializes placement reconciliation, send, confirmation, and markup
per logical thread. The graph's coordinator remains separate. Repository CAS
checks state, version, current attempt and an owned claim token. Repositories
flush; the existing UoW commits. No transaction spans media reads or Bot API calls.
Concurrent application instances are unsupported; do not run two bot processes.

Permitted transitions are `pending -> blocked|sending`, `blocked -> pending`,
`sending -> confirmed|failed|unknown`, `unknown -> confirmed|failed` with operator
evidence, and `failed -> pending` only by explicit requeue. Confirmed is terminal
for media. A repeated pilot command never requeues failed/unknown/sending media.
Startup converts abandoned sending attempts to unknown before polling begins.
No lease expiry, timeout, or Bot API history lookup authorizes resend.

If an older/manual destination projection exists without a confirmed publication,
the service preserves unknown and requests operator review without sending. A
verified matching reference can be adopted through reconciliation; a conflicting
reference is rejected. Existing projection evidence never authorizes another send.

The adapter reuses stored bot-specific Telegram file IDs without `getFile`.
Hosted evidence checks bot identity and metadata policy, not bytes. See
[hosted reuse](TELEGRAM_HOSTED_REUSE.md). Local uploads use only bounded library paths, reject
paths escaping the library item (including symlinks), recheck manifest policy,
size and SHA-256 against persisted validation, and send the checked byte snapshot.
Root messages omit reply parameters; children require the exact parent with
`allow_sending_without_reply=false`. Bad-request/forbidden responses are known
rejections. Other dispatch errors, invalid returned coordinates, and post-send
commit failures remain uncertain. Captions are empty and no forward/copy API is
used. Media outcome and markup outcome are independent.

## Token rotation and destination navigation

Each publication owns one managed reply-token digest. Issuance through the
existing reply-chain service and replacement/deletion of its previous managed
token happen in one transaction. Other independently issued tokens are untouched.
Markup repair rotates this managed token because its raw value is never stored.
Repeated failed repairs retain at most one managed token, including across a
restart. Links copied before rotation become unavailable; the currently installed
button is reusable until its next repair/rotation. A crash between token commit
and Telegram edit can temporarily leave an outdated button. Reinvoke the confirmed
pilot command or run markup repair; this never resends media.

On child confirmation, its parent's `navigation_post_id` becomes that latest
confirmed direct reply and its markup becomes pending in the same transaction.
Repair adds a **Latest confirmed reply** hyperlink alongside **Reply with a cat**.
Older parents and nested branch posts work identically. This is one direct-child
pointer, not a child index. Links use `https://t.me/c/<channel-id>/<message-id>`
for configured `-100...` channel/supergroup coordinates. Private channel readers
must already be members. Other coordinate types omit the navigation link. Only
confirmed destination projections are linked; private intake coordinates never
appear. Telegram-native child-to-parent replies remain intact.

## Operator recovery

Stop the bot before running this local tool. It uses the same configured database,
bot and destination and requires `--bot-stopped` as an explicit exclusive-ownership
assertion. Keep the application stopped until recovery completes. Operators own
the evidence decision: message IDs must be independently inspected in the selected
destination and matched to this publication. A boolean assertion cannot discover
non-delivery; absence from Bot API history is not evidence.

```bash
uv run --frozen python -m cats_channel.publication.admin status PUBLICATION_UUID --bot-stopped
uv run --frozen python -m cats_channel.publication.admin recover-abandoned --bot-stopped
# Only after independently verifying the exact external result:
uv run --frozen python -m cats_channel.publication.admin confirm PUBLICATION_UUID --message-id 123 --bot-stopped
# Only after establishing definite non-delivery:
uv run --frozen python -m cats_channel.publication.admin prove-non-delivery PUBLICATION_UUID --bot-stopped
uv run --frozen python -m cats_channel.publication.admin requeue PUBLICATION_UUID --bot-stopped
# Confirmed media only; never calls a media send operation:
uv run --frozen python -m cats_channel.publication.admin repair-markup PUBLICATION_UUID --bot-stopped
```

Requeue only changes failed to pending; a later explicit pilot command sends it.
Confirm atomically writes projection, publication and attempt outcome. If recovery
cannot prove either result, leave unknown. If writing uncertainty fails during
cancellation/dispatch handling, durable sending remains non-retryable and startup
recovery converts it to unknown. Uncertainty recording has a ten-second operation
budget and uses the existing awaited cancellation-resistant UoW cleanup. No critical
task is fire-and-forget. Markup cancellation leaves confirmed media with repairable
pending/failed markup. Logs contain allowlisted identifiers, phase/state, attempt
number, duration and safe categories, never API errors, tokens or file IDs.

## Verification boundaries

Offline tests use actual SQLite migrations and disposable PostgreSQL 16, deterministic
barriers, fake Bot API transport and real `Dispatcher.feed_update()` routing.
They do not establish live channel permissions, real Telegram media acceptance,
or a private-channel pilot outcome. Those require a separately authorized pilot.
Migration 0005 intentionally fails on ambiguous legacy destination projections;
it never deletes or chooses among them. Resolve such data explicitly before upgrade.

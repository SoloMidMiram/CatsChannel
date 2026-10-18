# Publication contract for issue #7

This is the agreed implementation contract for the next publisher phase. Durable
publication records and the integrated submission/moderation flow are **not yet
implemented**. The merged #6 graph keeps its existing semantics.

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

These are future publication states, independent of submission validation and
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

1. **#5 intake:** authenticated Telegram media -> shared byte validation ->
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

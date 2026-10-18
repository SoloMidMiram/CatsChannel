# Posting commands and pilot regression plan

This plan records the owner's two confirmed choices on 2026-10-18:

- **Separate automatic chains per stable source**, inside one destination channel.
- An authorized exact-parent reply may contain media acquired through another
  provider. A Telegram upload can reply under a YouTube-source post without being
  relabeled as YouTube media.

This is a plan, not implemented `/post`, intake, publication or moderation UX.
It supersedes the attachments' suggested global-feed migration. Keep `CatThread`
per source; do not introduce `ChannelFeed` or guess parents from Telegram history.

## Parent behavior

| Entry | Parent decision | Advances the source's logical tail? |
| --- | --- | --- |
| First accepted normal item for source A | No parent; source A root | Yes, at logical finalization |
| Later automatic item for A | A's current logical tail at finalization | Yes |
| Automatic item for source B | B's own root/tail, never A's | Yes, for B only |
| Reply button under any confirmed post | Exact internal post represented by the token | No |
| Reply button under an interactive branch | Exact branch post | No |
| Manual normal append | Explicit authorized source-chain selection; show the chosen mode | Yes, only through normal finalization |

If A's normal path is `A1 -> A2 -> A3`, a button reply `X` under `A1` remains a
branch. A's next automatic item replies to `A3`, never `X`. B remains independent.
Pending/unknown delivery on A blocks A's descendants, not B's healthy chain.
Manual channel messages and service messages never move an automatic tail.

The logical tail still advances at `finalize_intent()`, as ADR-004 specifies.
The publisher sends a child only after the exact parent is confirmed and has the
correct destination projection. Confirmation advances delivery state, not that
same logical field again. A deleted parent halts that path and requires explicit
repair; there is no fallback to an older post or a new root.

## Bounded domain correction before intake (#6)

The current code conflates media provenance with target-chain assignment:
`SubmissionService._resolve_thread()` rejects a Telegram upload selected for a
YouTube source thread, and `ReplyChainService._submission()` repeats a provider
match requirement. Submission persistence also copies target-thread source
metadata into submission fields. A byte adapter alone cannot fix this.

Separate actual source/acquisition identity from **authorized placement basis**.
Automatic verified-source routing remains strict. A manual explicit choice or
authorized exact-parent entry establishes a placement target, not evidence that
the uploaded media originated at that thread's YouTube channel. Preserve media
provider, provider-scoped media ID and unresolved/verified provenance truthfully;
record explicit assignment separately where needed. Do not weaken validation,
deduplication, actor policy, or parent/thread membership checks.

An interactive child belongs to its selected parent's thread even when its own
media provider differs. Its parent must still exist in that thread and destination.
A normal automatic submission cannot exploit the interactive exception to switch
source chains. Public payloads/callbacks cannot assert trusted authorization.

Reopen #6 for this bounded follow-up and migration/regression design, preserving
the completed v1 history. No global graph rewrite is required. Existing data must
not be silently reclassified; any schema change needs migration/rollback tests.

## User flow and modular commands (#5)

`/post` is the planned primary posting command; `/submit`, if retained, is an alias
to the same implementation. Bare `/post` starts a fresh flow, shows normal mode
and explicit source-chain selection where required, then asks for one video.
It must never silently reuse an old exact-parent context or select a chain from
untrusted captions/handles. New-chain creation is an explicit admin action, not
an automatic inference from a user's text.

A channel button opens `/start catreply_<opaque-token>`. Authorized resolution
starts the same post flow directly in exact-parent mode and asks for media; the
user does not have to issue a second command. Raw chat/message IDs are not command
arguments or FSM state. Failed/unavailable links share one safe response.

Planned routing ownership, introduced incrementally when that feature lands:

```text
bot/routers/common.py       start/help/cancel and shared entry dispatch
bot/routers/post.py         /post alias, selection callbacks, awaiting-media input
bot/routers/media.py        existing probe/download utilities
bot/routers/pilot.py        explicitly separate admin publication utility
bot/routers/moderation.py   #8 only, when implemented
        -> application intake / placement / publication services
        -> trusted byte adapter and UoW repositories
```

Router factories receive dependencies through the composition root. Reuse existing
authorization, operation logging, flow leases and the outer error boundary.
Handlers translate updates and render results; they do not query ORM models,
classify downloader failures, own retry loops, choose tails or send publications
as hidden side effects. Avoid a generic command plugin framework until needed.

State transitions are entry -> target selection if needed -> awaiting media ->
validation/intake -> pending acknowledgement. `/cancel`, command replacement,
timeout and restart have explicit outcomes. Reuse versioned replacement so a slow
download/resolver cannot restore a superseded draft. Keep only internal context
IDs/enums in FSM. Durable submission/intent survives FSM reset; reset is not a
database deletion. Retain current admin/private restrictions for the pilot.

Before transfer, reconcile an existing private inbound projection. If submission
commit succeeded but intent creation failed, resume the existing submission and
create only the missing intent: no second download, duplicate submission or
changed exact parent. Duplicate/replayed updates need ownership checks and an
existing-result response. Intake acknowledges **pending**, never published.
It does not finalize, send to the channel, moderate or create reply buttons.

## Error boundaries and logging

The core already has structured correlation/duration/outcome logging, typed media
classification, cancellation-safe cleanup and an unexpected-error boundary. Extend
these at the new boundaries; do not replace them with nested catch-all handlers.

| Failure boundary | Required behavior |
| --- | --- |
| Invalid input, denied target, failed validation | Typed safe rejection and actionable prompt; no retry |
| Acquisition/temporary files | Bounded owned work, byte limits and cleanup; retry only an explicitly classified safe acquisition |
| Submission/intent commit uncertainty | Reconcile private projection/handoff and existing intent before fresh work |
| Database busy/conflict | Roll back/drain; bounded fresh-transaction retry only for a repeat-safe operation |
| Cancellation/shutdown | Propagate cancellation, drain owned work and cleanup, preserve the primary failure |
| Telegram send possibly dispatched | Durable `unknown`; no blind resend, restart replay or broad `except: retry` |
| Reply-button edit failure after confirmed media | Repair only markup on the known message; never resend media |
| Unexpected application failure | One outer containment boundary, safe category, correlation ID and incident evidence |

Define a small allowlisted event schema per new service: correlation ID, operation,
phase, outcome, safe error category, duration, attempt count and recovery action.
Allow internal submission/intent/post identifiers only where needed. Extend the
logger's field allowlist deliberately and test redaction. Never record command
arguments, raw tokens, Bot API payloads, captions, credentials, private coordinates,
file IDs, filesystem paths or exception messages. Do not attach arbitrary objects.
At INFO, keep one completion record per operation plus bounded phase/error events;
default logs and user responses should not become noisy.

## Learning from pilot failures (#9, from the first feature)

"Learning" means reviewed engineering feedback, not a bot changing its own rules:

1. Run an explicitly authorized private pilot against one selected revision.
2. Capture a bounded sanitized incident: revision, safe operation/phase/category,
   correlation ID, expected/observed outcome, durable lifecycle state and whether
   external delivery is known, absent or unknown. Review before sharing evidence.
3. Reduce it to an offline fake-transport/temporary-database reproduction. Preserve
   cancellation, replay and timing order with barriers; avoid sleeps as assertions.
4. Add a failing regression, make the smallest reviewed fix, and run relevant tests.
5. Re-run a bounded pilot only after a concrete change, and link the verified
   result to the incident. No automatic live replay, training from private logs,
   dynamic permission expansion or self-modifying retry/error policies.

Initial regression matrix: `/post` entry/alias, selection, invalid media, old button,
cross-provider exact parent, nested branch, source rename, A/B interleaving, stale
selection, duplicate update, partial commit, no second transfer, cancellation at
each boundary, cleanup failure, unknown/deleted parent, send timeout after effect,
restart reconciliation and failed button edit without duplicate media. Record the
safe log and user response expected for every error category.

## Practical delivery order

1. Bounded #6 source/provenance versus authorized placement correction and tests.
2. #5 modular `/post`/deep-link intake with pending result and recovery coverage.
3. #7 one-destination publication, strict parent projections, per-source ownership,
   confirmed/unknown recovery and post-confirmation reply buttons.
4. #8 auditable moderation over the same durable intent; no retargeting.
5. An authorized private pilot, incident regressions throughout, and later measured
   operational hardening. #9 observability begins with #5/#7, not after incidents.

Discovery #18-#21 stays metadata-only and can progress separately. #22 supplies
eligible media to the same normal-intent boundary, routes by verified stable source
or explicit authorized selection, and never publishes directly or grants approval.
Do not hold a database transaction across acquisition or a Telegram send. A local
per-source publication lock can span an owned send workflow; durable attempts and
short transactions handle effects and confirmation. Multi-instance coordination,
albums, extra destinations and speculative Redis are later needs. SQLite-first
remains a separate unapproved backend proposal; this planning change alters no CI
or runtime dependencies. Python 3.11 remains the sole supported runtime.

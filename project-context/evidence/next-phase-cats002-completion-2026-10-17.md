# Next focused phase after merged PR #16

Prepared on 2026-10-17 from main at
`3ba1b2baa09d6567815969bf0129564a62cda47b`.

## Immediate PR: complete the remaining CATS-002 contracts (#3)

Suggested branch when implementation starts: `feat/aiogram-entry-contracts`.
This is a proposed implementation scope; no new branch or feature code is created
by this reconciliation.

Reuse the existing application factory, routers, dependency injection, media gate,
error policies, cancellation boundary, and safe logging. Do not rewrite them.

Deliver only the missing transport/core conventions:

1. Owned-resource lifecycle with explicit startup and shutdown ownership, cleanup
   after startup failure, and cancellation-safe release. Keep database ownership
   explicit and persistence optional for commands that do not need it.
2. A validated `catreply_<opaque-token>` deep-link convention and parser/builder.
   Never expose raw chat/message/user IDs. Keep the public reply token distinct
   from PR #16's one-use media-handoff token. Define an injected resolver contract
   for an internal target; actual parent selection and product replies stay in #6.
3. Callback-data conventions containing internal IDs and allowlisted actions;
   moderation decisions and UI remain #8.
4. FSM contracts containing internal submission/thread/parent IDs. Define explicit
   reset/cancel/new-command replacement behavior and exclude private message text.
   Define the conventions here; the product reply flow remains a later phase.
5. Real Dispatcher.feed_update tests with mocked transport for parser/builder,
   malformed/unknown tokens, authorization, state reset/replacement, lifecycle
   failure, and cancellation. Preserve all current command behavior and diagnostics.

The merged `docs/AIOGRAM_CORE_AUDIT.md` remains the acceptance checklist. Close #3
only after the missing criteria have implementation and regression evidence.
Check the still-open #2 prerequisite acceptance separately; do not infer closure
from an old bootstrap merge or create an unrelated rebuild of the foundation.

## Submission acceptance checkpoint (#5)

PR #16 merged the source-aware application/persistence foundation, not a live
Telegram submission UI. Audit the actual #5 criteria against the final merged
revision and tests, then decide issue closure explicitly after prerequisite #3.

Preserve the review fixes: allowlisted provenance, `(telegram, file_unique_id)`
media identity, explicit source verification/manual selection, and atomic bound
handoff consumption. Evidence dataclasses are trusted internal assertions, not
authenticated media certificates. A real trusted Telegram validator and adapter
are required before exposing native submission handlers. If acceptance requires
additional integration, use a separate bounded submission-entry PR; do not fold
reply-parent selection or publication into the core-contract completion PR.

## Then CATS-005 reply-chain domain (#6)

Build domain services over the existing thread/post repositories:

- Explicit root and initial tail for a stable source.
- Normal append selects the canonical tail; serialize competing appends within
  one process and retain optimistic conflict checks.
- Interactive reply preserves the exact selected internal parent, including an
  older post. An interactive branch does not redirect the automatic source tail.
- Reject missing/cross-thread parents, invalid transitions, and unresolved source
  identity without explicit selection. Renames do not change thread identity.
- Telegram message coordinates remain optional projections. Final tail changes
  that depend on publication success are coordinated with #7, not invented as
  unconditional success before a Bot API response.

Test root, linear append, older-parent branch, interleaved source chains, renames,
invalid/cross-thread parents, and competing appends. No Bot API publication or
moderation UI belongs in this PR.

## Remaining main sequence

`#3 completion -> #5 acceptance/entry gaps -> #6 reply-chain domain -> #7 single-channel
publication -> #8 moderation -> authorized end-to-end pilot -> measured optimization`

#7 owns copy/upload, parent projection via ReplyParameters, inline URL buttons,
per-thread publication serialization, idempotency and ambiguous-result
reconciliation. #8 owns approval/rejection and its audit trail. Pilot measurements
come before performance tuning; #9 production hardening and any Redis adoption
remain evidence-driven, separately scoped work.

## Optional discovery track (#17)

The new discovery epic does not replace the main sequence. Its own issue permits:

`#18 stable watchlist -> #19 discovery + #20 ledger/checkpoints -> #21 scheduler`

These can proceed independently when their shared input/candidate contract is
agreed. Discovery means metadata/candidates, not downloaded/validated/approved
media. #22's acquisition/submission/moderation bridge waits for the applicable
#5-#8 interfaces and permission policy. The four-hour discovery schedule is only
roadmap scope here; this reconciliation creates no recurring automation or live
YouTube scan.

# Owner posting experience, plan review and issue amendments

Reviewed both user-supplied attachments about exact-parent buttons versus automatic
parent selection, compared current aiogram/submission/reply-chain code and GitHub
plans, and asked the two product questions that materially affect placement.

## Explicit owner answers

1. Automatic topology: **Separate automatic chain for each source (current
   implementation)**. The attachments' suggested one-global-ChannelFeed migration
   was not selected and must not be implemented implicitly.
2. Telegram media under a YouTube-source reply target: **Yes, keep the exact selected
   parent and truthful media provenance**. A reply belongs to its selected parent's
   thread; its media provider/source identity must not be fabricated from that target.

These answers supersede uncertainty in the attachments, not the established
logical-placement versus confirmed-delivery distinction. Automatic A -> A tail,
B -> B tail, and interactive branches never redirect normal tails. Do not inspect
Telegram history to guess a parent or hold SQL transactions across network calls.

## Confirmed implementation gap

SubmissionService._resolve_thread rejects a Telegram upload selected for a
YouTube thread. Submission persistence copies target-thread channel metadata into
submission fields, and ReplyChainService._submission repeats provider matching.
This blocks the owner's exact-button experience even with a trusted byte adapter.
Automatic source matching remains strict; authorized manual/exact placement must
be represented separately from actual acquisition/source evidence. Validation,
provider-scoped dedupe, actor checks and parent membership must remain intact.

## Published plan and board updates

PR #26: https://github.com/SoloMidMiram/CatsChannel/pull/26
Branch docs/bot-command-pilot-plan; base a6a0c8574239121006342d37f3b6e9fbe68d0ff7;
head 92944545c70bca9349a0c90bfe779f7b1e8ab8ef. Eight documentation files changed,
224 insertions and four deletions. No runtime/schema/dependency/access/backend
changes. Relative links, required decision/recovery content and whitespace checked.
PR is open, non-draft and mergeable. Exact-head CI run 39087167565 passed all
three jobs: Linux Python 3.11, Windows Python 3.11 and disposable PostgreSQL.
Separate project-context validation/generation checks and all 11 tests passed.

- #6 reopened for the bounded provenance/authorized-placement follow-up; completed
  PR #24 v1 history retained. No global graph rewrite.
- #5 now specifies primary /post (optional /submit alias), opaque-button direct
  entry into the same FSM, focused routers, existing DI/auth/log/error reuse,
  private-projection replay before transfer, pending-only acknowledgement, typed
  recovery and real-dispatcher/fake-transport coverage. #6 correction precedes it.
- #7 keeps per-source publication ownership, short SQL transactions, immutable
  exact parents, confirmed-parent gating, unknown-send reconciliation and button
  edit repair without media resend. Full product flow remains unimplemented.
- #8 records exact-target/media-provenance policy and focused moderation routing.
- #9 renamed to Pilot reliability and measured production hardening. Safe event
  schemas, incident capture and regression discipline begin in each feature PR;
  speculative deployment infrastructure stays later. SQLite-first remains proposed.
- #1 dependency order/checklists amended for reopened #6.
- #17/#22 bind automatic media to the same normal-intent per-source rule and
  incident discipline; discovery remains metadata-only until permission-gated
  acquisition and approval. Stale unfinished-core/draft-PR references reconciled.

## Pilot feedback model

Bounded sanitized incident -> offline failing regression -> reviewed narrow fix ->
bounded authorized revalidation. Record revision, correlation/phase/category,
expected/actual result and durable state/delivery certainty. Do not retain private
payloads, raw tokens, file IDs, coordinates, paths or exception text. No autonomous
policy learning, permission expansion, blind live resend or training on private logs.

The prepared feat/bot-submission-intake checkout remains clean at a6a0c85 and was
not edited. The planning checkout is clean and pushed; no bot implementation was
started. No live Telegram, YouTube or production-database calls were made.

Next: review/merge PR #26, implement the bounded #6 policy correction with regression
and any necessary migration checks, then #5 intake, #7 publisher, #8 moderation,
and authorized pilot with incident regressions throughout. Project-context changes
remain unstaged in the separate memory checkout.

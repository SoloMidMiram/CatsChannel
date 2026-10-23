# Publication contract and board reconciliation

Completed the owner's requested small documentation/board cleanup, resumed on
2026-10-18 after the automatic approval reviewer was temporarily unavailable due
to account usage limits. The rejected command had not executed; the same approval
path succeeded after the owner explicitly requested continuation.

## Merged baseline and documentation PR

PR #24 is merged at 2f6f37027fef3dbf8dbd3093ae217797222b0956; merge CI run
39062008254 passed all three jobs. Local main was fast-forwarded to that revision
before creating docs/publication-contract-and-board.

PR #25 is open and mergeable at 3840bb498be892453ec4cbf35660bb3a4a80b400:
https://github.com/SoloMidMiram/CatsChannel/pull/25

Its eight documentation files add 145 lines and remove 18; runtime code, schema,
dependencies and database policy are unchanged. Local Markdown targets and
whitespace were checked. Exact-head CI run 39063095212 passed Linux Python 3.11,
Windows Python 3.11 and PostgreSQL. Feature checkout is clean and synchronized.

## Consistent contract

Keep the merged logical placement semantics: normal finalize_intent commits a
post and advances CatThread.tail_post_id. This is the logical canonical tail,
not a Telegram-confirmed cursor. #7 must add separate durable publication records
with pending/blocked/sending/confirmed/failed/unknown states, unique ownership,
confirmed parent/projection gating and explicit ambiguous-send reconciliation.
Persist confirmed result/projection after Telegram confirmation; do not repeat or
roll back the graph-tail mutation. An unpublished logical parent blocks children;
there is no silent reparent/new root or blind retry.

Token issuance requires the known destination projection, so #7 attaches reply
buttons after confirming the media and retries markup repair independently from
media delivery. Publication states/records remain planned, not implemented.

## Applied GitHub cleanup

- #2: all Python 3.11 bootstrap acceptance criteria checked with merged-main/CI
  evidence; closed as completed.
- #5: retained open and renamed to Complete bot submission intake over merged
  foundation. Completed PR #16 service criteria are checked. Remaining acceptance
  explicitly requires authenticated byte validation, source selection, durable
  normal/exact-parent intent, replay recovery and dispatcher integration. Manual
  download/publish commands are not this product workflow.
- #6: closed acceptance checked and logical-tail/delivery distinction recorded.
- #7: contradictory delivery-time graph-tail criterion replaced with separate
  publication state, projection confirmation, recovery and bot vertical-slice gates.
- #8: pending moderation retains intent; approval finalizes once; exact parents
  remain fixed. Separate validation/moderation/delivery states are explicit.
- #1: completed child checkboxes and delivery order reconciled.
- Draft PRs #10 and #11: inspected, then closed as superseded without merging or
  deleting branches. Their tips are not ancestors of current main; no merged-tip
  claim was made. Board links/useful architectural invariants exist in the current
  design; their old documentation/layout should not overwrite it.

## Remaining work

Review/merge documentation PR #25. Implement #5 bot intake over existing services;
then #7 durable delivery with a fake-transport bot-triggered pilot approval path;
then #8 durable moderation. Follow with an authorized private-channel pilot and
measured optimization/hardening. More records alone do not close the integration
gap. SQLite-first remains a separate proposed decision. No live Telegram/YouTube
or production-database calls were made. Project-context updates stay unstaged in
the separate feat/project-memory checkout.

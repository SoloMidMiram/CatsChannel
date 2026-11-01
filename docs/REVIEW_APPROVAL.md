# Review channel and Approve button

Set `REVIEW_CHANNEL_ID` to a numeric channel ID and restart the bot. The bot must
have posting and editing permissions in that channel. `CHANNEL_ID` remains the
publication destination. The pilot owner selected the existing private pilot
channel for both roles, so a review copy appears there first and approval creates
the actual published reply as a separate message.

This same-channel arrangement is limited to the restricted private pilot. A
review copy is visible before approval, so public deployment requires a distinct,
private inspection destination and verified channel permissions. The current
configuration does not enforce this deployment boundary; do not enable review
delivery into a public publication channel. Issue #8 remains open for complete
moderation acceptance, including rejection and deployment safeguards.

Validated new submissions automatically receive a review copy with an **Approve**
button. Intake is durable before review delivery; a review transport failure does
not discard the submission. Previously accepted pending submissions can be queued
through `ReviewService.enqueue(submission_id)` without re-uploading their media.

Telegram-hosted intake now means metadata-policy acceptance, not full byte
decoding. The review caption identifies this limitation. See
[Telegram-hosted reuse](TELEGRAM_HOSTED_REUSE.md) for evidence and policy details.

Only the configured `ADMIN_USER_ID` can approve. Buttons contain an internal review
ID and version and are bound to the stored review channel, exact review message,
submission and publication destination. A copied/forwarded button or stale pending
version cannot approve a different item. The reviewer actor and decision time are
committed before publication is invoked. Repeated or concurrent clicks cannot
acquire the same approval again.

Approval calls the existing publication service, preserving immutable intent,
exact-parent delivery, durable attempt ownership and duplicate protection. It does
not use a separate direct sender. Confirmed approval changes the review caption
to **Approved. Published to the channel.** and removes the button. Failure to edit
that caption does not resend or undo the published video.

Review delivery has `pending`, `sending`, `confirmed`, `failed` and `unknown`
states. Approval has `pending`, `approving`, `approved`, `blocked` and
`needs_reconciliation` states. Startup marks abandoned review sends `unknown` and
interrupted approvals `needs_reconciliation`. Neither outcome is automatically
resent. A review button delivered before a failed confirmation transaction stays
unavailable until its exact message binding is reconciled by an operator.

This is the requested approve-only pilot workflow. It does not add rejection
buttons/reasons, multi-reviewer policy, an operator reconciliation UI, or the
remaining full Issue #8 moderation requirements. The existing admin-only
`/pilot_publish` command remains available as the explicit pilot override.

Migration: `0006_review_approval` adds `review_items` and does not change existing
submission, reply intent or publication records. Configure the channel only after
applying migrations. `--bot-diagnose` checks review posting/editing permissions
when the setting is present.

## Live verification — 2026-10-25

The existing owner-submitted reply `34e430c7-5244-4232-a098-029fd32b75cb` was
queued once as review `416abf79-165d-46af-bfac-bb20c74ec493` at
[review message 1229](https://t.me/c/2885576054/1229). The configured admin clicked
Approve; the harness did not simulate the click or send an approval command.
The decision audit records that admin and its timestamp.

The publication service produced one confirmed attempt for publication
`a9e80d17-7d24-4a64-b555-c761ca00b9b0`. Read-back verified the actual
[published reply 1230](https://t.me/c/2885576054/1230), its exact parent message
1228, and its installed reply button. The review copy now says
“Approved. Published to the channel.” and its Approve button is removed.
The original unresolved/unverified source provenance remains unchanged.

The old poller stopped with zero active updates. A SQLite backup was taken before
applying migration 0006; Alembic metadata parity passed. The proxy failed on fresh
connections after restart, before any review send. After the owner repaired the
route, both permission preflight and review delivery passed. The new poller
remained running as PID 32560 and processed the real channel callback.

Validation: Windows full suite **471 passed, 62 skipped**; WSL review/migration
suite **17 passed**; Ruff lint/format and Git whitespace checks passed. Focused
tests cover real dispatcher channel callbacks, non-admin denial, forged/stale
buttons, concurrent and repeated approval, interrupted send/approval, changed
destinations, and real publication-service exact-parent preservation.

Ignored local evidence: `.runtime/reply-review-delivery.json`,
`.runtime/reply-review-verification.json`, `.runtime/review-live-bot.log`,
`.runtime/reply-live-status.json` and `.runtime/review-queue.log`.

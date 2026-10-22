# Live second-video intake and observability audit

Date: 2026-10-22

The already-running aiogram poller consumed the owner's new interaction without
agent-generated Telegram input. The observed sequence was `/post` in 471 ms, an
exact-reply `/start` entry in 621 ms, and Telegram-native `post_intake` in
54.149 seconds. The intake completion outcome was `pending_created`; there were
no error events in the observed live output.

Read-only database reconciliation proves one new validated submission,
`5642d5ec-66f4-4704-8742-91ef31002639`, with full-decode evidence. Its durable
intent is `interactive_reply` to logical post
`1af7f9f2-c753-4a71-a437-e6847659771f` in the existing source thread. Its
source identity is truthfully `unresolved`, which is valid for cross-provider
media attached through an authorized exact-parent entry. It has one private
message projection and no logical post, publication, publication attempt, or
destination projection. Nothing was published during this diagnosis.

Final database totals are two submissions, two intents, one logical post, one
publication, one publication attempt, and three message references. The first
publication remains confirmed; the second submission remains pending.

## Confirmed observability flaws and fixes

- Intake completion logs previously said only `pending_created`, so operators
  could not distinguish an automatic-tail submission from an exact-parent
  submission. Completion records now include allowlisted `disposition` and
  `placement_mode` fields without message text, Telegram file identifiers, or
  internal target identifiers.
- The publication application service and bot middleware both emitted the
  event name `bot_operation_finished`, producing two semantically different
  completion records for one command. Service-level completion is now named
  `publication_operation_finished`; middleware retains the bot event.
- The pilot router swallowed `PublicationError`, replied generically, and let
  middleware record the command as successful. Publication errors now pass to
  the shared safe error boundary, so failure and completion records share the
  same correlation and error category. Successful/durable non-success states
  record `publication_state`, and invalid syntax records `invalid_request`.

Focused regressions cover the new intake fields, deduplicated publication event
names, confirmed publication outcomes, and matching ineligible-publication
failure/completion categories with no media send. The complete WSL Python 3.11
suite passes with 450 passed and 61 skipped; Ruff lint/format, compileall, and
Git whitespace checks pass.

The first live restart then exercised the bounded startup policy: three `getMe`
attempts failed as `bot_api_network`, with phases and attempt counts correctly
logged, and the process exited without consuming or sending an update. A
one-shot read-only diagnostic confirmed the proxy route was still unavailable.
The maintenance relaunch retained the 180-second file budget, used a 30-second
ordinary API budget and a bounded window of ten read-only identity attempts with
15-second backoff. It recovered without a retry event and remained running with
an established connection to the configured local proxy. This restores polling
but does not replace an external service supervisor.

## Outstanding Issue #8 implementation

GitHub Issue #8 remains open, and the current code does not implement its core
moderation workflow. Specifically absent are a separately configured inspection
destination and permission preflight, durable inspection-delivery ownership and
unknown-send recovery, a distinct moderation state, stored review projections,
version-aware internal-ID callbacks, durable reviewer actor/action/time records,
rejection reason/audit records, authorization and stale/duplicate callback
handling, moderation-specific rate/abuse controls, and an operator path for
inspection reconciliation. The existing `/pilot_publish` command is explicitly
a temporary admin-only bypass: it finalizes placement and calls PR #29's
publication service directly. It must not be mistaken for Issue #8 approval.

The live timing is one functional observation, not a throughput, percentile,
concurrency, or long-duration reliability benchmark. The bot also has no
continuous health monitor; polling backoff and structured events are process
behavior, not external supervision or automatic process restart.

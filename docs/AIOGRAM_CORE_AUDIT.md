# Aiogram core acceptance audit

Audited against GitHub issue #3 and merged `main` at `0dca318` before starting the
source-aware submission phase.

| Issue #3 item | Current evidence | State |
| --- | --- | --- |
| Bot token and one destination channel | `Settings` and existing bot tests | Complete |
| Network-free application factory | `create_bot_application()` and dispatcher tests | Complete |
| Safe error middleware and cancellation | router error boundary and regression tests | Complete |
| Owned startup/shutdown lifecycle | Bot context exists; generic owned-resource lifecycle coverage is absent | Partial |
| Public reply deep-link convention/parser | No `catreply_<opaque-token>` parser exists | Missing |
| Moderation callback-data convention | No moderation callback model exists | Missing |
| FSM internal-ID/reset conventions | No product FSM exists | Missing |

Issue #3 therefore remains open. The missing features are not prerequisites for
the transport-independent issue #5 service: that service does not register a
handler, parse reply deep links, use callback data, create FSM state, publish, or
own a long-lived database resource. Its durable media-handoff token is a separate
one-use correlation contract, not the future public reply token.

The missing issue #3 behavior must be completed before a later reply/submission UI
depends on it. This audit is not evidence that issue #3 can be closed.

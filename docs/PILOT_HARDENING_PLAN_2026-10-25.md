# Pilot review and error-handling plan

Status: both completed pilots reviewed; the owner's new reply intake is verified.
This records findings and planned changes. Production retry and persistence
policies have not been changed as part of this observation.

## Evidence from both complete pilots

| Observation | 2026-10-22: hxg0GqFwKzE | 2026-10-25: gfdwZV_ypbw |
| --- | --- | --- |
| Downloader | Existing response recovered; interrupted sends reconciled | One URL request; saved response reused |
| Bot API | Intermittent startup/polling failures | Hostname TLS failed, public-IP TLS succeeded; configured route later recovered |
| Intake | Separate 30-second file timeout discovered; explicit 180-second budget introduced | Full decode, 3,928,713 bytes, 65.248 seconds; intake completed in 6.015 seconds |
| Correlation | Recovery metadata and durable state required | User-account and Bot API message IDs differ; harness was corrected by full-file SHA-256 reconciliation |
| Publication | One confirmed attempt; destination projection | One confirmed attempt; destination video, exact parent and reply button read back |
| Later reply | Separate 54.149-second exact-parent intake remained pending | Owner's new 6.125-second exact-parent intake is validated and pending |
| Provenance | User-selected/unverified | User-selected/unverified; existing Telegram downloader-source thread |

Sources: [second complete pilot](PILOT_GFDWZV_YPBW_2026-10-25.md),
[proxy diagnosis](PROXY_DIAGNOSIS_2026-10-25.md), and the first pilot's ignored
`.runtime/telethon-pilot-hxg0GqFwKzE.jsonl` and recovery file. Checked-in historical
evidence under `../project-context/evidence/` includes
`bot-file-timeout-live-intake-2026-10-22.md`,
`live-end-to-end-private-publication-2026-10-22.md`, and
`live-second-video-intake-and-observability-2026-10-22.md`.

Successful publication is proven for both private pilots. Persistent network
reliability, verified YouTube ownership and Issue #8 moderation are not proven.
Two intake timings are functional observations, not a benchmark.

## Current owner-driven reply observation

The first launch failed after three bounded `getMe` attempts, before polling.
A single maintenance relaunch uses at most ten read-only identity attempts with
five-second linear backoff and a 30-second request timeout. This is runtime-only;
the saved application profile and production defaults remain unchanged.

The owned process records a heartbeat, PID, startup state, active updates,
successful/failed `getUpdates` calls and selected exact-parent context. No message
text, token, file identifier or raw transport exception is included. Runtime URL
acquisition uses the existing `telegram_bot` backend. Process status is separate
from an actual successful poll.

The second launch recovered after two logged startup retry failures. PID `6164`
entered polling and remained running. An initial `/start` failed on a
`TelegramNetworkError`, classified too generically as `internal_error`; its error
notification failed about 60 seconds later. An `ignored` message completion was
also recorded. Telethon history confirms the owner sent `/start` before the first
13,589,552-byte video; the owner did not simply send the commands in reverse order.
The sparse operation log cannot conclusively bind the ignored event to one
particular historical message. Bot history and local log timestamps also show
clock skew, so ordering is checked within each source rather than equating their
wall clocks.

The owner's subsequent `/start` succeeded, and the new video was accepted at
01:46:59 UTC (05:16:59 Asia/Tehran). Durable submission
`34e430c7-5244-4232-a098-029fd32b75cb` has full FFmpeg decode evidence:
13,589,552 bytes, 137.95 seconds, SHA-256
`3e013328e3a16fec9c7f05292068685692f04caa53bf1d318841585ae46baeac`.
Its intent is `interactive_reply` to `d164a804-9122-4ee4-a197-74da2a33e4a7`.
At the end of that intake observation, no logical post or publication had been
created for this new reply. Source identity remained `unresolved`, valid for the
authorized cross-provider exact-parent flow. The observer did not auto-approve it.
The owner subsequently approved the review copy through the new inline button;
one confirmed publication preserved the exact parent. See
[review approval verification](REVIEW_APPROVAL.md#live-verification--2026-10-25).

The investigation reproduced a silent-ignore path offline using the real
`Dispatcher.feed_update()` with a mocked resolver and Bot API transport: suspend
reply-entry resolution, dispatch a video, observe `UNHANDLED` with zero intake
calls, finish entry, and dispatch the same video to observe one intake with the
correct exact parent. This demonstrates a concrete application gap, without
claiming that the sparse live logs prove every detail of the same interleaving.
Evidence: `.runtime/queued-entry-reproduction.json`,
`.runtime/reply-live-history-metadata.json`, `.runtime/reply-live-bot.log`,
`.runtime/reply-live-startup-failed.log` and `.runtime/reply-live-status.json`.

## Retry policy to implement explicitly

| Operation | Policy | Stop condition / durable guard |
| --- | --- | --- |
| Identity and permission reads | Bounded transient-error retries with capped delay and total elapsed budget | Authentication/configuration/rejection errors stop immediately; never announce polling before a real attempt |
| `getUpdates` | Keep aiogram's existing backoff as the sole owner | No nested retry decorator; track last successful poll separately from process liveness |
| `getFile` and byte download | Proposed opt-in maximum two transient read attempts within one total file budget | Same authenticated inbound reference, no committed submission, current flow lease; reset partial temporary bytes; cancel/drain before retry |
| Decode, size/duration policy and identity validation | No automatic retry | Corrupt/oversized/rejected media is not a transient transport error |
| Database commit | Reconcile first; classify known rollback vs ambiguous outcome | Reuse consumed handoff/private projection and immutable intent; never reacquire merely because an acknowledgement is missing |
| Downloader URL, `/post`, forward and publication send | No blanket automatic retries | Persist dispatch ownership; unknown outcomes require reconciliation; confirmed media is never resent |
| Reply markup | Separate bounded idempotent repair | Repair only markup on the confirmed destination message; no second video |
| Shutdown | Graceful drain with a bounded escalation policy | Process exit or confirmed underlying closure before releasing ownership; retain uncertain session locks |

Turning the proxy off selects a route; it does not make an unavailable direct
route healthy. Do not silently fall back, hardcode Telegram IPs or disable TLS
verification. The observed hostname/IP difference supports DNS/domain-routing
investigation, not an automatic global resolver rewrite.

## Ordered, reviewable changes

0. **Entry ordering and explicit unhandled outcomes.** Reserve an authorized
   private reply-entry transition before awaited target lookup, and give a video
   arriving behind that transition a bounded admission/defer policy before FSM
   handler filters can discard it. A successful entry should accept the queued
   video once under the same captured parent. Failed entry must produce an
   explicit recoverable outcome rather than silent ignore. Do not serialize all
   handlers behind long downloads: `/cancel` and replacement commands must still
   invalidate old leases immediately. Deferred media must never adopt a later
   unrelated source/parent. Add opaque inbound correlation so ignored, deferred,
   rejected and committed updates can be distinguished without content logging.
1. **Incident correlation and diagnostic classification.** Preserve allowlisted
   root exception categories across `BotApiSession` normalization: proxy
   negotiation, connection reset, DNS, TLS verification and request timeout.
   Keep public messages stable and raw token-bearing exceptions private. Add
   an opaque operation identifier tying intake, durable submission and completion
   together. Clearly label Bot API references versus MTProto account references;
   equality of their message IDs must never be an invariant.
2. **Read-only transfer recovery.** Add the bounded file-read policy above in the
   adapter, independent from publication. Use one elapsed budget across attempts,
   injectable sleep/clock and current flow-lease checks after every wait. Default
   behavior and migration need explicit review before enabling retries.
3. **Pilot runner recovery.** Replace single-video hardcoded harnesses with one
   stage runner, atomic dispatch checkpoints, namespace-tagged message references,
   hash-based fallback reconciliation and a stop-file hook. Each stage first
   reconciles durable state. A failed observer must not cause a second send.
4. **Acknowledgement and replay boundary.** Add focused durable regressions for
   committed intake followed by failed acknowledgement and process restart.
   Return the existing submission/intent on replay. Preserve exact parent and
   never advance a normal tail for an interactive branch. Keep this persistence
   change separate from the transport/logging change.
5. **Operations and process ownership.** Add one poller owner lock, health status
   with last-success time and capped external restart policy for exhausted startup.
   Process supervision must not retry publication. Stopping must drain active
   operations and retain enough state to reconcile ambiguous delivery.

## Regression matrix and existing coverage

Use real `Dispatcher.feed_update()` with mocked Bot API transport for application
contracts, deterministic barriers for races, local proxy fixtures for transport
and a temporary SQLite database for durable replay. Do not induce live ambiguous
publication as a test.

| Incident / invariant | Existing protection | Focused addition |
| --- | --- | --- |
| Video arrives during reply-entry lookup | Offline reproduction currently yields `UNHANDLED` | Barrier-based real dispatcher test: queued video accepted once after successful entry; failed entry, cancel and replacement do not bind it to a different parent |
| Reply prompt and error notification both fail | Safe outer error containment exists; live failure is labelled `internal_error` | Inject `SendMessage` network failures; retain safe method/phase classification and primary cause, bounded notification time, no handler or media replay |
| Startup recovery/exhaustion | `tests/test_bot_lifecycle.py`: bounded identity attempts, exact phase, cleanup and cancellation | Recovered/exhausted readiness state plus total budget and no nested retry |
| Proxy routing | `tests/test_bot_transport.py`: real SOCKS handshake, remote DNS, proxy-off direct routing, secret-safe errors | Proxy accepts CONNECT then resets TLS; safe cause classification and no false-ready result |
| Independent file timeout | `tests/test_telegram_media_adapter.py`: explicit timeout, decode and cancellation cleanup | Partial read then success, exhaustion, unchanged total deadline, temporary-byte reset |
| Stale flow during retry | `tests/test_bot_submission_intake.py`: cancel/source replacement barriers | Cancel or replace during backoff; no second transfer, commit, acknowledgement or stale cleanup |
| Durable replay | `tests/test_bot_submission_intake_persistence.py`: replay after submission commit avoids retransfer | Lost acceptance reply across process restart; one private projection and one intent |
| Distinct message-ID namespaces | Observed live harness defect | Different Bot API/MTProto IDs for identical media; correct correlation, unrelated same-sized file rejected |
| Unknown publication | `tests/test_publication.py`: cancellation, commit failure after send, competing claims, restart reconciliation | Preserve these gates unchanged under new transport retry configuration |
| Markup repair | `tests/test_publication.py`: managed token rotation without media resend | Retryable edit failure remains separate from confirmed media delivery |
| Exact interactive reply | `tests/test_bot_submission_intake.py`: exact parent retained | New owner-driven reply snapshot plus restart/replay with older parent, unchanged normal tail |

## Completion gates

For each code change: reproduce the incident with a failing focused regression,
apply the smallest fix, run the focused suite, then the relevant complete suite
and lint/format checks. Use exact revision CI when a commit/PR exists. The latest
completed local baseline before this observation was 458 passed / 62 skipped on
Windows and 32 passing WSL transport tests; no new full-suite result is implied.

The live reply intake gate passed: successful opaque-link entry, durable validated
intake with `interactive_reply` to `d164a804-9122-4ee4-a197-74da2a33e4a7`, no
unexpected source switch, unchanged normal tail and no publication. If the
owner approves publication, additionally verify one attempt, the exact Telegram
parent, installed reply markup, durable projection and duplicate-free recovery.
Record current process/readiness state and observed limitations with the result.

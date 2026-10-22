# PR #30 review reconciliation

Date: 2026-10-22

PR #29 merged at `57927938c24fd7fe076a5fe7fdf114b171b712b7`; its publication
head was `72b7cc19c10d33c40c95b317322a30141296d235`. PR #30 incorporates this
main baseline and retains only Bot API transport, bounded identity startup
recovery, file-transfer timeouts, Telethon terminal-future cleanup, safe outcome
logging and their regression tests. Project-context tooling/evidence is split to
`docs/project-context` for independent review. The split preserves Git history.

Before this split, head `9bfe147bf38455ea462c425609e27395973c8036` passed CI run
`39785789857` on Ubuntu, Windows and PostgreSQL. The split heads require their
own CI; prior results are historical evidence, not a substitute for final checks.

Historical post-split WSL Python 3.11 verification: 451 passed, 61 skipped with
`python -m pytest --capture=sys -q`; Ruff lint/format, byte compilation and
whitespace checks passed. Runtime and test files are unchanged from transport
head `5e144ba` at that stage; the subsequent review corrections below change
transport diagnostics and add regressions.

## Follow-up P2 corrections

The review of `de403a2` correctly found broad timeout classification and polling
failures hidden inside aiogram's listener. The general classifier now recognizes
only `TelegramNetworkError`; raw timeouts are normalized only at known Bot API
request boundaries. Resource, database-startup and shutdown timeouts retain an
internal category in lifecycle/CLI diagnostics.

Configured sessions now emit structured `getUpdates` failures with consecutive
attempt counts before aiogram consumes them. A healthy empty response resets the
series. Aiogram owns the same polling backoff, cancellation propagates, and media
sends remain single-attempt. Regressions exercise the actual aiogram listener,
counter reset, cancellation, redaction, API rejection and one failed media send.

Post-correction Python 3.11 validation: WSL full suite 457 passed/61 skipped;
Windows full suite 456 passed/62 skipped. Targeted transport, lifecycle,
publication, intake and Telethon regressions: 98 passed on WSL. Ruff lint/format,
byte compilation and whitespace checks passed. Local regression transport uses
fakes and loopback SOCKS; no live Telegram requests, sends or runtime restart
occurred. Exact-head CI remains a separate check after the correction is pushed.

## Findings and acceptance boundaries

| Finding | Reconciled disposition |
| --- | --- |
| Mixed operational and project-context scope | Split into independent branches/PRs, both based on merged main. |
| Exact-parent live reply acceptance | Still outstanding: the recorded second submission is pending with zero publication attempts. No live approval or send is performed by this review. |
| Process supervision and sustained reliability | Issue #9 follow-up; bounded startup/polling recovery does not provide process restart or availability guarantees. |
| Admin pilot bypass | Restricted pilot mechanism remains; Issue #8 owns durable reviewer decisions, inspection delivery and audit. |
| Remote evidence validation | Context validator checks local structure; current external claims require GitHub/code verification. Context tooling is outside this PR's final diff. |

Engineering review of the transport changes can proceed separately from private
pilot acceptance and production deployment. The missing live exact-parent check
does not establish a code defect. It remains a gate before claiming the complete
interactive-reply pilot has passed. Production readiness is not established.

An independently authorized pilot should inspect the exact destination parent
and reply button, then verify restart/replay does not create a second media send.
Any uncertain delivery must use exclusive operator reconciliation with independent
evidence; never blindly repeat publication. This document does not authorize it.

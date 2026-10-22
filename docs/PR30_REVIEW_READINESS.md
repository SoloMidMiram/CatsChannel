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

Local post-split WSL Python 3.11 verification: 451 passed, 61 skipped with
`python -m pytest --capture=sys -q`; Ruff lint/format, byte compilation and
whitespace checks passed. Runtime and test files are unchanged from transport
head `5e144ba`; the remaining reconciliation edits are documentation only.

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

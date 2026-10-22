# PR #23 final validation snapshot

PR #23 remains open, mergeable, and non-draft:
https://github.com/SoloMidMiram/CatsChannel/pull/23

- Branch: `feat/aiogram-entry-contracts`.
- Base: `3ba1b2baa09d6567815969bf0129564a62cda47b`.
- Exact head: `eb52a481c88c1a1beb0550cb9dc8b5fa44adf8ad`.
- Exact-head CI: https://github.com/SoloMidMiram/CatsChannel/actions/runs/39056010842
- All five jobs passed: Ubuntu and Windows on Python 3.11 and 3.13, plus
  disposable PostgreSQL integration.

The final review added regressions and fixes for lifecycle failure precedence,
FSM cancellation cleanup, polling shutdown after callback failure, and stable
first-download locking on Windows. The Windows race came from resolving a library
path before it existed; the canonical library root is now materialized before the
per-item lock key is calculated.

Final local validation:

- WSL Python 3.11, all extras: 291 passed, 2 skipped.
- WSL Python 3.13, all extras: 291 passed, 2 skipped.
- Windows Python 3.11, all extras: 290 passed, 3 skipped.
- WSL baseline without optional extras: 254 passed, 4 skipped.
- Ruff lint and formatting, frozen lock consistency, offline sdist/wheel builds,
  wheel-content inspection, and `git diff --check` passed.

The feature worktree was clean after commit and push. No live Telegram, YouTube,
or production-database calls were made.

## Issue #2 policy audit

The behavioral foundation requirements are present and covered across Python 3.11
and 3.13. One literal tracker criterion still says `.python-version` must be 3.13,
while the repository's documented baseline intentionally remains Python 3.11 with
3.13 in CI. PR #23 does not silently change that policy. Closing issue #2 requires
an explicit tracker decision to accept the dual-version policy or change the
repository baseline.

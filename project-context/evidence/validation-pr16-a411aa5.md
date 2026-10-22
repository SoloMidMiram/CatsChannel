# PR #16 source-aware submission validation at `a411aa5`

Verified on 2026-10-17.

- Pull request: <https://github.com/SoloMidMiram/CatsChannel/pull/16>
- Issue: <https://github.com/SoloMidMiram/CatsChannel/issues/5>
- Head commit: `a411aa56d89afa2404e826946cf82f45b0703a67`
- Base commit: `0dca318848b886f6b77cddc127d32e5f265fbabf`
- GitHub state: open, mergeable draft
- GitHub Actions run: <https://github.com/SoloMidMiram/CatsChannel/actions/runs/39041152554>
- Exact-head CI: Ubuntu and Windows on Python 3.11 and 3.13 all passed
- WSL Python 3.11.16 with all extras: 219 passed, 1 skipped
- WSL Python 3.13.15 with all extras: 219 passed, 1 skipped
- Windows Python 3.11.4 with all extras: 218 passed, 2 skipped
- WSL Python 3.11 baseline without persistence extras: 185 passed, 3 skipped
- Ruff lint/format, lock consistency, whitespace, SQLite migration parity and
  interruption/retry tests, PostgreSQL offline SQL rendering, and offline
  sdist/wheel builds passed
- Built artifacts were checked for local environments, secrets, sessions,
  cookies, downloads, and private environment files; none were included

The branch adds transport-independent validated-media contracts, conservative
stable-source resolution, explicit manual selection for unresolved sources,
durable one-use Telegram handoffs, typed submission failures, bounded evidence
persistence, and migration revision `0002_source_aware_submissions`.

The issue #3 audit found bot configuration, network-free construction, and error
containment complete; generic resource lifecycle is partial, while public reply
deep links, moderation callback conventions, and product FSM/reset conventions
remain missing. PR #16 therefore does not add an aiogram handler, choose a reply
parent, publish, moderate, or claim issue #3 complete. Issue #5 remains open while
the PR is a draft. No live Telegram, YouTube, or database service call was made.

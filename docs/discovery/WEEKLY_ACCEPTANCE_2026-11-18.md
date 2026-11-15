# Weekly discovery acceptance for November 18

## Historical review-stack evidence (November 12, 2026)

| State | Evidence and disposition |
| --- | --- |
| Implemented | Watchlist and initial contracts are on main. The resolver, uploads and experimental UUSH adapters, ledger migration and one-shot CLI are on the review stack. [#53](https://github.com/SoloMidMiram/CatsChannel/pull/53), [#54](https://github.com/SoloMidMiram/CatsChannel/pull/54), [#55](https://github.com/SoloMidMiram/CatsChannel/pull/55), [#56](https://github.com/SoloMidMiram/CatsChannel/pull/56). |
| Offline qualified | Integration head b13157a9a5b3193bd132b6ed504a758a282c74bd passed Ubuntu, Windows and PostgreSQL CI. The focused Windows run passed 44 tests with 13 skips, including the CLI recovery path and SQLite migration rollback. The CI suite exercises disposable PostgreSQL migration and recovery. [Integration CI](https://github.com/SoloMidMiram/CatsChannel/actions/runs/43278725978). |
| Live qualified | Historical feasibility verdict E remains inconclusive. The metadata and browser preflights qualify synthetic controls only. UUSH membership and coverage on the deployment route remain unverified. [#47](https://github.com/SoloMidMiram/CatsChannel/pull/47), [#49](https://github.com/SoloMidMiram/CatsChannel/pull/49), [#50](https://github.com/SoloMidMiram/CatsChannel/pull/50). |
| Policy approved | Written guidance for the multi-owner operator queue and review of field-level retention are outstanding. [#51](https://github.com/SoloMidMiram/CatsChannel/issues/51). |
| Still blocked | Real API-data ingestion, deployment-route live qualification and scheduling remain gated. Media acquisition and moderation require independent rights and workflow approval. [#21](https://github.com/SoloMidMiram/CatsChannel/issues/21), [#22](https://github.com/SoloMidMiram/CatsChannel/issues/22). |

The full local Windows run recorded 788 passes, 144 skips and one failure. The unchanged MCP symlink test requires a Windows privilege unavailable on this account (WinError 1314). Hosted Windows CI passed on the same integration head.

The fixture CLI default uses an in-memory database. Its persistent fixture mode proves that channel A resumes page two, channel B is skipped after completion, and observations remain unique. The PostgreSQL job also covers owner fencing, before/after-commit recovery and migration rollback.

## Merge confirmation (November 15, 2026)

The component reviews and final integration are complete. SoloMidMiram accepted
`e3f887dbe9856ac56816be1361c23df7c56e3371` for source merge, and PR #56 landed on
November 15 at `ad653687a91e9b0a2c4c770bc23606fadebe5cbf`. The merge has parents
`1e67b95` and `e3f887d`. Its tree `0053e7f3a8b6a9e5d35a609b4e5d409cbe5df7ee`
matches the accepted integration tree. Ubuntu, Windows and disposable PostgreSQL
passed [post-merge CI](https://github.com/SoloMidMiram/CatsChannel/actions/runs/43730028685).
Issue #51 remains open and production ingestion remains gated.

The cumulative integration PR also incorporates the policy and acceptance
documents and [PR #57's qualification harness](https://github.com/SoloMidMiram/CatsChannel/pull/57).
The original integration CI link above identifies the reviewed scanner baseline.
The current cumulative result is tracked by [PR #56's checks](https://github.com/SoloMidMiram/CatsChannel/pull/56/checks).

## Cumulative verification

The offline code at commit 8eab36d5895da657a517599c6f06f1b403617af1 includes
the known-video lookup and the complete fixture discovery stack. On Ubuntu WSL,
a clean archive of that commit on the Linux filesystem passed the full local
suite with CPython 3.11.16. It recorded 816 passes and 134 skips after
`uv sync --locked --all-extras` and `uv run --frozen pytest -q --tb=short`.
The Windows symlink privilege failure described above did not recur there.
[Hosted CI on the same commit](https://github.com/SoloMidMiram/CatsChannel/actions/runs/43289954871)
passed Ubuntu, Windows and disposable PostgreSQL. The evidence supports offline
review. Live qualification and production use remain gated by #51.

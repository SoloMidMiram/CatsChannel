# ACT-P2A metadata reconciliation

Reviewed on November 18, 2026 from baseline
`1d066c1e30b91798f642c2b28666ed72f5e56bdf`.

The ACT-P1 failure diff contained 106 expired entries: 88 sources and 18 records.
Independent standard-library inspection of the baseline catalogs at this date
reproduced that exact ID set. The complete original/result/rationale ledger is
`act-p2a-reconciliation-ledger-2026-11-18.json` (source-192).

## Evidence meaning

Each fixed commit citation was checked with Git against the approved ancestry.
Each dated local validation, review, merge, proposal or conversation artifact was
read in its original scope. Its bytes remain unchanged. Fixed completed GitHub
runs were read through their metadata endpoints; all 19 referenced runs were
completed successfully at their recorded October heads. This is archival
verification, without a new workflow dispatch or a new test-result claim.

Nine merged PRs and ten distinct issues were read through GitHub metadata during
the accepted diagnosis. The sanitized snapshot is retained in source-190, with
additional November 18 checks for issue #5, roadmap issues #8/#21/#51, PR #47 and
the main ref. Issue #5 closed at `2026-10-22T04:08:18Z`. Its earlier open-state
observation is preserved in historical fact-028; fact-088 records the later state.
The other parts of the October board snapshot are not promoted to new claims.

The source-005 roadmap file explicitly describes a November 15 baseline. Its
reviewed baseline document is historical evidence, without present operational
qualification. Sources source-020 and source-021 were read at their original URLs
on November 18. Source-191 records the limited guidance actually reverified.

## Separating contracts and implementation snapshots

Decisions decision-003/010/011/012/013/015/017 combine enduring design choices with
dated feature-completion or acceptance details. Their original words, event
dates, source references and details remain as historical superseded records.
Decisions decision-025 through decision-031 restate only their accepted core
contracts and supersede each predecessor exactly once.

The review compared those contracts with the baseline source boundaries:

- Optional Telethon acquisition and shared local validation in
  `cats_channel/adapters/telegram_downloader.py` and
  `cats_channel/services/media_service.py`.
- Explicit bot composition and lifecycle ownership in
  `cats_channel/bot/application.py`, `bot/lifecycle.py`, `bot/entry.py` and
  `bot/flow.py`.
- Repository/UoW transaction ownership in `cats_channel/persistence/database.py`
  and `persistence/contracts.py`.
- Submission provenance and durable handoff ownership in
  `cats_channel/submissions/service.py`.
- Normal-tail versus exact-parent placement in
  `cats_channel/reply_chains/service.py`.
- The recorded owner topology choice in source-090.

These are documentary/source-level contract checks. They do not claim new live
transport verification, production qualification, or a passing full suite.
In particular, decision-012's old statement that submission handlers were not
exposed remains a historical implementation boundary; it is not copied into the
new stable contract.

## Other dispositions

fact-002/003/007/009/011/015/017/029 describe past merges, test results or
completion observations. Historical scoping preserves their event chronology.
fact-008's October 17 unverified publication state already has the unique
successor fact-041, supported by source-114's October 22 private-pilot receipt.
No second successor, new publication, or broader release approval is introduced.

proposal-004 remains the October 17 SQLite investigation/proposal. Its original
status and results are preserved historically. This review neither approves a
database-policy change nor asserts a present owner endorsement. Existing
PostgreSQL dependencies and CI remain untouched.

Original verification dates are retained except source-005, source-020 and
source-021, whose narrow documentary claims were actually inspected now.
New records and snapshots use their real November 18 review date. The 30-day
policy, validators and test assertions remain unchanged.

Cleanup-wrapper correction, synthetic qualification, Bubblewrap skip differences,
uv selection and checkout bypass are separate ACT-P2 operational evidence. They
are not application changes and are not proof that the full workflow passes.

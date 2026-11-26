# ACT-P2 candidate evidence — 2026-11-26

Verdict at final preparation: **BLOCKED — hosted jobs cannot start under the
account billing/spending condition**. This is not maintainer source acceptance
or production approval. Separate technical review passed after findings were fixed.
Issue: https://github.com/SoloMidMiram/CatsChannel/issues/61.

Branch `fix/act-p2-context-freshness` targets main, based on
`1d066c1e30b91798f642c2b28666ed72f5e56bdf` (tree
`74d142597985a1dfe4eb773a8337ad9a0d4c3684`). The final candidate is identified by
Git/PR metadata; this document records pre-push validation, not a self-referential
commit ID. No other PRs are merged or changed.

## Reproduction and metadata

The [diagnosis](act-p2-diagnosis-2026-11-26.md) precedes validator changes.
Independent baseline validation emitted exactly 166 freshness diagnostics:
48 records and 118 sources. The [complete ledger](../../project-context/evidence/act-p2-inventory-2026-11-26.json)
retains every original, result, disposition, justification, supporting reference
and dependency, plus twelve inconsistent branch/research snapshots and baseline
ID manifests. It extends the retained November 18 per-entry review rather than
treating its old 106-entry inventory as complete now. No inventory IDs are deleted.

Historical test counts, merge events, process observations and private-pilot states
remain dated observations. Six additional dated implementation decisions retain
their contracts and scope historically; the seven previously split stable
contracts remain explicit. Current external guidance retains its actual November
18 review date. No blind date refresh or 30-day policy change was made.
fact-028 retains its historical board statement; fact-088 uniquely supersedes it
with issue #5's October 22 closure. New fact-089 records November 26 GitHub state
and the bounded scheduler/qualification distinction. PR #60 is merged; offline
scheduling is implemented. Host scheduling and live/public operations remain
unqualified, with #51's policy gate still open.

All 43 original context receipts compare unchanged with baseline Git blobs.
All original catalog IDs remain. Supersession uniqueness and cycles are tested.
Local text receipt digests detect changes after universal newline normalization;
actively maintained stable contracts are not treated as immutable receipts.
Current records cannot depend on explicitly stale/unknown sources. Existence,
digest validity, freshness and claim truth remain separate checks: no digest
proves a remote state, a private receipt's truth, or operational readiness.

## Actual local checks

Native Windows, CPython 3.11.4 x64, uv 0.13.8, locked pytest 8.4.2,
pytest-asyncio 0.26.0 and Ruff 0.17.1. A new dedicated venv was synchronized from
the retained offline cache: no downloads, lockfile edits or changes to the prior
pilot environment. Tests use an explicit credential-free environment, temporary
HOME/USERPROFILE, no application/proxy credentials and only the asyncio pytest
plugin. Filesystem permissions and outbound networking are not isolated.

| Check | Result |
| --- | --- |
| `uv sync --offline --locked --all-extras --python <prepared Python 3.11>` | PASS, exit 0; 55 packages checked |
| `uv run --frozen pytest -q -ra --junitxml=<local evidence>/full.xml` | PASS, exit 0; 835 passed, 152 skipped; 81.903 pytest seconds, 86.047 launcher seconds |
| `uv run --frozen ruff check .` | PASS, exit 0 |
| `uv run --frozen ruff format --check .` | PASS, exit 0 |
| `uv run --frozen python tools/project_context.py validate` | PASS, exit 0; 139 records, 169 sources |
| `uv run --frozen python tools/project_context.py generate --check` | PASS, exit 0 |
| `uv run --frozen python tools/regress.py run --profile context --repeat 2 --timeout 120` | PASS, exit 0; both repetitions passed |
| Baseline inventory replay and original evidence/ID comparison | PASS |

After the independent-review fixes, the final full local run passed **838 tests,
152 skipped**, with zero failures/errors (110.599 pytest seconds, 125.422 launcher
seconds). All listed lint, formatting, validation, generated checks and both
context regressions were repeated successfully on the corrected code. Explicit
November 26 CLI replay also exited 0. The earlier 835-pass result above is retained
as the pre-push candidate's measurement, not substituted for this final run.

The initial run is retained separately: 824 passed, 7 failed, 152 skipped.
The seven failures exposed incorrectly pinned live README/CLI files; receipt pins
were narrowed to evidence, not disabled. Ruff's nested-condition finding was also
corrected. The final successful run used the corrected code and additional tests.

Skipped cases: 138 disposable/PostgreSQL concurrency tests, 5 Bubblewrap tests,
3 Linux sandbox-command cases, 2 opt-in external-MCP cases and 4 POSIX lifecycle
cases. These are unexecuted qualifications, not passes. New lifecycle tests cover
30/31-day boundaries, historical/stable non-expiration, CLI clock injection,
newline-independent digest tampering, stale/unknown dependencies, provenance and
privacy rejection, complete ID/claim retention, unique supersession and idempotent
generation. Existing future-date, source-path and cycle tests remain intact.

## Issue #61 acceptance matrix

| Criterion | Local disposition |
| --- | --- |
| Actual main/base, issue, open branches/PRs and CI inspected | PASS; main unchanged, PRs #47/#49/#50 left untouched |
| ID-complete reproducible baseline inventory | PASS; 166 entries at November 26 |
| Individual evidence-backed disposition and no expired current entry | PASS at November 26; maintainer semantic review remains required |
| fact-028 historical provenance and supported closure | PASS; unique fact-088 successor |
| Deterministic evaluation-date replay, default strict freshness | PASS; default remains real date, explicit CLI as-of supported |
| Receipt integrity, source linkage and dependency invalidation | PASS locally; optional canonical-text digests plus existing reference checks |
| Historical evidence/IDs retained and outputs regenerated | PASS; 43 original receipts unchanged |
| Current roadmap integration without production promotion | PASS; fact-089 is limited to offline implementation and outstanding gates |
| Focused and full local checks | PASS on Windows; platform skips recorded |
| Fresh hosted Ubuntu, Windows and PostgreSQL on final head | BLOCKED at preparation; obtain after draft PR creation |
| Independent technical review | PASS after reproducing and fixing malformed source-ID/freshness dependency-index crashes; regression evidence retained |
| Owner source acceptance | Pending explicit maintainer decision; not inferred from tests or technical review |

## Risks and next review

Draft PR #62 was opened from the initial candidate
`4d103d8ebafc26a012fc70422074bede906dd810`. Its fresh hosted run
[45876686092](https://github.com/SoloMidMiram/CatsChannel/actions/runs/45876686092)
executed no steps: Ubuntu and PostgreSQL annotations report recent account payment
failure or a spending-limit block; Windows was cancelled by matrix fail-fast.
This is missing platform qualification, not a failed executed pytest assertion.
No billing/security settings were changed and no workflow was manually rerun.

Final review reproduced malformed source IDs and malformed dependency freshness
([]/{}) raising TypeError in the added dependency index. A string-ID guard and
tuple membership now retain ordinary validation diagnostics instead of crashing.
The separate read-only AI technical review rechecked those fixes and reported
PASS with no remaining material findings. It did not execute tests or authorize
merging. The final reviewed head and subsequent hosted outcome belong to the
PR metadata and completion report; the earlier successful run above remains
dated evidence for its own candidate, not an assertion about unrun platforms.

Current claims still expire by design; future dates may require real reverification.
Historical scoping preserves old implementation details that must not be read as
present permission. Receipt digests are optional and text-specific; remote links
are not fetched by validation. Newline normalization deliberately ignores line
ending differences. CPython patch level, plugin discovery and native Windows
coverage differ from hosted Linux/PostgreSQL. No act simulation, runner, live
service operation or production change was performed. Cleanup-wrapper and ACT-P1
environment differences remain independent evidence.

At every subsequent review iteration record branch/PR/head, actual checks,
findings and disposition. This branch changes only directly affected context
representations; the separate uncommitted repository-map/roadmap branch remains
untouched. A source merge and closing issue #61 require explicit owner acceptance.

# PR #31 requested-audit checkpoint correction

Date: 2026-10-22

Review comment: https://github.com/SoloMidMiram/CatsChannel/pull/31#discussion_r4351637888

The comment is valid at `b84812684cc55778eef1b65966361555f75415db`: after
successful test repetitions, the runner persisted pass before a requested log
audit began. Interrupting that audit left a misleading passing report on disk.
Negative-control regressions on that baseline produced three expected failures
and one pass: both successful-test audit paths exposed the early pass, and audit
interruption retained it; preserving an earlier test failure already worked.

Successful test checkpoints now remain running while the requested audit is
pending. Pass is persisted only after the audit finishes successfully. Earlier
test failures remain fail, even if the later audit passes. An interrupted audit
leaves the incomplete running checkpoint intact without inventing an audit result.

Regressions inspect the on-disk report inside the audit callback, exercise audit
success and failure, preserve an earlier test failure, and inject KeyboardInterrupt
during the audit to verify that no passing checkpoint survives. No live service,
Telegram operation or application restart is involved.

Validation: focused context/offline-tool suite 61 passed; full WSL Python 3.11
suite 518 passed/61 skipped; full Windows suite 517 passed/62 skipped. Ruff lint,
formatting, compilation, context-generation freshness and whitespace checks pass.
The real Windows `run --profile context --repeat 1 --log ...` command also passed
with a synthetic local fixture, persisting both the test result and successful
audit in the final report. Corrective-head CI is checked separately after push.

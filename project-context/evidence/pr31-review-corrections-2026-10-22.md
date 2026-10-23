# PR #31 review corrections

Date: 2026-10-22

Reviewed baseline: `6eacce04d20b5f2bb1b6efd8a7f4c7349cad0e4d`. Fresh GitHub
metadata confirmed all three exact-head CI jobs passed in run `39801146512`.
That result applies to the baseline, not automatically to the corrective commit.

All three supplied P2 findings were reproduced from the baseline and corrected:

- Strict log audits now check both failure-to-completion and error-completion-to-
  failure correlation. Incomplete windows may omit either counterpart explicitly;
  matched category/outcome contradictions still fail. Successful completions and
  returned publication states are not treated as missing exception records.
- Text and JSON share a complete-output character-budget contract, including
  serialized formatting and the final newline. Query display is bounded while
  retrieval retains the full query. Details may be omitted before whole records;
  mandatory audit fields are preserved and JSON is never sliced into invalid text.
- Supersession validation detects directed cycles iteratively, including cycles
  reached from a noncyclic tail. Existing self-link/unknown-target diagnostics
  remain. CLI validation blocks selection and generation on inconsistent history.

Focused regressions cover orphan/mismatched correlation, both log orders,
incomplete-window semantics, oversized Unicode queries, full CLI stdout budgets,
JSON detail/record fallback, two-record and multi-record cycles, a cycle with an
incoming tail, valid chains, and generation refusing invalid history.

These corrections change developer tooling only. No Telegram runtime/dependency
changes, live service calls, media approval, publication or bot restart occur.
Issue #8's durable moderation workflow remains the next product milestone.

## Verification

- Baseline negative controls loaded the original tooling from Git: orphan error
  completion passed, oversized text/JSON exceeded 300 characters, and a two-record
  supersession cycle passed validation. No live application code was invoked.
- Corrected focused tools suite: 57 passed.
- Full WSL Python 3.11 suite: 514 passed, 61 skipped.
- Full Windows Python 3.11 suite: 513 passed, 62 skipped.
- Actual repeated context gate: 2/2 passed, 57 tests per run.
- Ruff lint/format, compilation, context validation/generation freshness and
  whitespace checks passed. Corrective-head CI is checked separately after push.

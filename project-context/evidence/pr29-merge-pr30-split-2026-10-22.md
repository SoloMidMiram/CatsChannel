# PR #29 merge and PR #30 scope reconciliation

Date: 2026-10-22

GitHub CLI metadata and a fresh Git fetch confirm PR #29 merged into main at
`57927938c24fd7fe076a5fe7fdf114b171b712b7`. Its reviewed head was
`72b7cc19c10d33c40c95b317322a30141296d235`. PR #30's pre-split head
`9bfe147bf38455ea462c425609e27395973c8036` passed all three jobs in CI run
`39785789857`: Ubuntu, Windows and PostgreSQL. These results apply to that head,
not automatically to the new split branches.

The owner explicitly selected a separate project-context PR. The context branch
`docs/project-context` starts at the merged main revision and carries only the
context integration originally recorded in 9bfe147. The transport documentation
link is excluded because the document belongs to PR #30. Runtime code, dependency
metadata and lockfile are unchanged on this branch. PR #30 removes the context
integration with a normal revert, incorporates updated main and targets main;
history is preserved without a force push. The historical context-integration
and pilot reports remain evidence, with current status reconciled in records.

The review distinguishes engineering review from live pilot acceptance. Existing
offline tests and the recorded normal private publication support bounded review
of transport recovery and logging. Exact-parent live publication, its destination
reply/button, and restart/no-duplicate behavior remain unverified for the second
pending submission. This reconciliation sends no Telegram message and gives no
publication approval. Issue #8 owns moderation; Issue #9 owns deployment
supervision and sustained reliability work. Remote source contents still require
GitHub/code verification rather than inference from context validation.

Post-split local WSL Python 3.11 verification reports 451 passed/61 skipped for
the transport branch and 429 passed/61 skipped for the independent context branch
on merged main. Ruff lint/format, byte compilation and whitespace checks passed
for both. Context validation and generated-output checks passed; the 12 focused
context tests also passed on Windows. These runs use the existing all-extras
environment; independent locked dependency installation and PostgreSQL execution
remain CI checks for each final head. No live delivery was attempted.

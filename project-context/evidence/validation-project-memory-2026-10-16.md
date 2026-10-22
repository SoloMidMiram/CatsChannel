# Project-memory validation — 2026-10-16–17

Scope: `feat/project-memory`, before commit and without live Telegram or YouTube
calls.

## Results

- WSL CPython 3.11.16: 94 passed, 1 skipped.
- WSL CPython 3.13.15: 94 passed, 1 skipped.
- Windows CPython 3.11.4: 93 passed, 2 skipped.
- Ruff lint and formatting checks: passed.
- Offline lock consistency: passed.
- Offline source-distribution and wheel builds: passed.
- Project-context validation and generated-output checks: passed.
- A focused selector smoke test preserved status, freshness, source, and
  verification references within its character budget.

The WSL suites used `pytest -s` because this local mounted-drive shell has an
external `/tmp` cleanup that removes pytest's file-descriptor capture file during
teardown. Collection and the full test suites pass when that unrelated capture
layer is disabled. Windows exercised pytest's default capture successfully.

## Safety

The context validator rejects current claims after their freshness window,
uncataloged evidence, repository-escaping or private local evidence paths, and
secret-like assignments without printing their values. The checked-in evidence
contains no credentials, cookies, session databases, phone numbers, or proxy
secrets.

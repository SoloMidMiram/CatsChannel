# Python 3.11 runtime-policy correction

The project owner clarified that Python 3.11 is the sole current supported runtime.
Python 3.13 was intended only as a future environment-upgrade target, not a current
compatibility promise or CI requirement.

PR #23 was updated at `1407d7693c5d2ddd1aeba07e75951cbbb1037263`:

- `requires-python` is `>=3.11,<3.12`;
- `.python-version` remains `3.11`;
- the lockfile is resolved for Python 3.11;
- the CI platform matrix runs Ubuntu and Windows on Python 3.11 only;
- disposable PostgreSQL integration also runs on Python 3.11;
- current environment, roadmap, status, TODO, and quickstart guidance distinguishes
  the future 3.13 migration rehearsal from present support.

Issue #2 was corrected to require Python 3.11 and to put Python 3.13 migration out
of scope. PR #23's description was reconciled with the same policy.

Exact-head CI run 39056666903 passed all three jobs. Local WSL Python 3.11 validation
reported 291 passed and 2 skipped; Ruff, formatting, lock consistency, offline
sdist/wheel builds, and whitespace checks passed. The initial mounted-drive pytest
invocation encountered the known temporary capture-file failure before collection;
the established `TMPDIR=/tmp` and capture-disabled invocation completed successfully.

Earlier Python 3.13 test results remain valid historical observations, but they do
not define the current support contract.

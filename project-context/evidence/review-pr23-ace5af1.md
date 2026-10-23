# PR #23 review corrections

Reviewed discussion comments 4303864306 and 4303864312 against the Python
3.11-only head 1407d7693c5d2ddd1aeba07e75951cbbb1037263. Fix committed and
pushed as ace5af178c67e9eb4f57c7032011e34d88570b8d.

- The all-zero token invalid-case issue was already corrected in bb6349d.
  Added a positive round-trip regression for the canonical uppercase A x 43
  token. Issuance and authorization remain the resolver's responsibility.
- Confirmed aiogram's delegated shutdown can replace the active polling error.
  ApplicationDispatcher now captures the active exception before shutdown and
  keeps it primary, chaining any simultaneous shutdown failure as its cause.
  Real polling tests cover ordinary failure and cancellation with successful
  and failing shutdown, exact-once resource closure and secret-safe logging.
- Confirmed the new polling regression fails when the fix is temporarily
  disabled; restored the committed source afterward.
- Targeted entry/lifecycle tests: 61 passed. Full Windows Python 3.11 suite:
  295 passed, 3 skipped (platform/opt-in PostgreSQL skips).
- Ruff, formatting, offline lock check, sdist/wheel builds and whitespace passed.
- Both requested GitHub review threads were replied to and resolved; confirmed
  through the GitHub API. PR remains open and mergeable; feature checkout clean.
- Exact-head CI run 39057289843: Ubuntu and Windows passed; PostgreSQL still
  initializing its disposable container at last verification.

Python 3.11 remains the sole supported runtime. No live Telegram, YouTube or
production-database calls were made. Project-context changes remain unstaged
and separate from the feature PR.

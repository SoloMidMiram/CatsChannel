# PR #28 flow-lease review correction

Review comment 4343982334 on head 9cf48d6 identified a valid race: video placement was read and provider lookup awaited before capturing the flow lease. A /cancel or replacement /post could finish during lookup, letting the old video adopt the new lease and clear newer state.

Fixed and pushed as 14d33d110ad3e9cc03e27f2e394802496178284a. Capture the lease before reading context/provider lookup and reject a superseded lease before process/acquisition. Two event-barrier real-dispatcher regressions cover cancel and replacement; both failed before and pass after the fix. They assert no process/acquisition, no pending acknowledgement and unchanged replacement state.

Focused dispatcher, persistence, entry and intake suites: 62 passed. Complete Windows Python 3.11 suite: 364 passed, 38 skipped (17.91s). Ruff, format (127 files) and diff whitespace checks passed. No live Telegram/YouTube or production database calls. Only post.py and its dispatcher regression file changed in the implementation commit. Review response 4344032711 posted and thread PRRT_kwDOU2eqSc6vBq9M resolved. PR remains open and mergeable; CI run 39712685401 was running at initial verification. Do not begin dependent #7 until #28 is reviewed and merged. Separate project-context edits remain unstaged.

Final verification: exact-head CI run 39712685401 completed successfully in all three jobs (Ubuntu, Windows, PostgreSQL). Feature checkout is clean and HEAD equals origin/feat/bot-submission-intake-v2 at 14d33d1.

# PR #24 UTC timestamp review correction

Review discussion 4304055557 correctly identified SQLite dropping non-UTC offsets
from token expiry writes. Added regressions first; all four SQLite cases failed.
Corrected and pushed as 8b58185df02ad74c36e23e133cde57afb388ff01.

The reply-chain service normalizes expiry before passing it to persistence and
returns UTC in IssuedReplyToken. The token repository independently validates
aware dates and normalizes creation, expiry and revocation writes to UTC. This
protects direct repository callers on both backends without a schema migration.

Shared SQLite/PostgreSQL cases cover positive and negative offsets, exact stored
instants, validity immediately before expiry and rejection at the exact expiry
instant. Local Windows Python 3.11 full suite: 334 passed, 36 skipped. Ruff,
formatting, whitespace, lock consistency and offline sdist/wheel builds passed.

CI run 39060865382 passed all three jobs on this exact head. The disposable
PostgreSQL job reports 68 passed. The review thread was replied to and resolved
after final CI verification; PR #24 is open and mergeable, and the feature checkout
is clean and synchronized. The earlier SQLite-first recommendation remains proposed;
this fix does not change database policy or CI. No Docker container or live
Telegram/YouTube/production database was used locally.

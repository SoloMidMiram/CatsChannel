# Aiogram application-core completion

Implemented in non-draft PR #23:
https://github.com/SoloMidMiram/CatsChannel/pull/23

- Branch: `feat/aiogram-entry-contracts`.
- Base: `3ba1b2baa09d6567815969bf0129564a62cda47b`.
- Head: `f8941e0af19f8d8abc59abe1a24686b1a8bf9fa2`.
- PR contains `Closes #3`; the issue closes on merge, not on this local record.
- CI: https://github.com/SoloMidMiram/CatsChannel/actions/runs/39054536111
- All five exact-head jobs passed: Ubuntu/Windows Python 3.11/3.13 and disposable
  PostgreSQL integration.

The remaining #3 acceptance items are implemented: network-free Bot composition,
owned lifecycle and reverse resource cleanup, accepted-update drain before FSM
storage closes, startup/teardown failure cleanup, repeated cancellation, canonical
opaque reply links with actor-aware target resolution contracts, internal-UUID
callback conventions, and private FSM entry/reset/replacement rules. Existing
commands, authorization, media gate, logging and error policies remain covered.

Fresh Windows Python 3.11 full suite: 286 passed, 3 skipped. The 53 new regression
cases exercise real Dispatcher.feed_update and polling with mocked transport.
Ruff lint/formatting, offline lock check, sdist/wheel builds, new module inclusion,
and whitespace checks passed. Feature worktree is clean after commit/push.

The default reply resolver rejects unavailable targets; actual graph/token mapping
is injected by the later reply-domain owner. Entry context stores internal IDs
only and accepts no media or moderation action. This satisfies the core convention
scope without claiming the later product workflows complete. No live Telegram,
YouTube or production database calls were made.

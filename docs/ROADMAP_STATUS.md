# Status

Current state: media-foundation feature branch plus an admin-only integration.

Completed:

- environment definition
- dependency baseline
- roadmap
- architecture boundaries
- CI skeleton
- Python 3.11 baseline and 3.13 CI target
- configuration template and YouTube probe/download example
- explicit Telegram publish command for a private test workflow
- shared CLI/Telegram media acquisition and validation service
- immutable source cookies and disposable extractor copies
- owned subprocess cancellation and bounded termination
- verified cache reuse and atomic media-library publication
- explicit secret-safe YouTube proxy configuration
- structured CLI error envelopes

The media-foundation implementation is offline-complete: Python 3.11 and 3.13 WSL
tests, Windows Python 3.11 tests, lint, formatting, lock consistency, and package
build checks pass. Private-channel Telegram publication remains a separate
authorized smoke test. Submission, moderation, and reply-chain work follows after
this branch is reviewed.

The sample is not the full submission, persistence, moderation, or reply-chain
implementation. Live service validation remains a separate smoke-test step.
See QUICKSTART.md for setup and upgrade phases.

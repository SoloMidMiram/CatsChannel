# Restricted private reply pilot — 2026-10-31

Status: observed download rejection; approval/publication acceptance incomplete.

PR #36 merged at `43db2b43e618f50d354d7327c6cd966fc947c7c8`.
Its head `928f24a` is an ancestor of main. PR #37 was retargeted to main;
the comparison still contains only the focused concurrency correction. No rebase
or history rewrite was required.

Before startup, process inspection found no running old poller. Read-only database
inspection found migration 0006, three confirmed publications and one confirmed,
approved review; there were no sending publications or approvals in progress.
One owned hidden poller was started with the PR #37 code, existing private-pilot
configuration/database, and separate ignored observer logs. An initial diagnostic
invocation from the new checkout had no environment file and failed configuration
validation; the poller explicitly loaded the existing pilot environment.

Two reply-link entries succeeded. Each subsequent video reached intake routing
and failed during Telegram file acquisition with `MediaError` caused by
`TelegramBadRequest`. Neither failure committed intake or queued a review.
Read-only Telethon history inspection identified two video attempts, each
23,220,422 bytes, following the reply prompts. No message was sent by that history
inspection and its connection cleanup completed.

Telegram's official `getFile` documentation states a 20 MB download limit for the
hosted Bot API: <https://core.telegram.org/bots/api#getfile>. Playwright navigation
and its saved accessibility snapshot verified that text during this observation.
The oversized files support a size-limit diagnosis; the generic application error
does not retain the raw Telegram error message, so that exact server description
was not independently recovered. Do not characterize this as a silent-ignore or
successful publication test.

The owner was asked to send a smaller video and then approve its review copy.
At the recorded checkpoint, polling had 113 successful reads, zero failed reads
and zero active updates; the selected private reply entry remained active. This
is a point-in-time observation, not a sustained availability guarantee. The live
poller was left running for the authorized interaction. No approval was simulated,
no previous media was resent, and no new publication is claimed.

This ordinary live interaction does not force the target-resolution race;
deterministic dispatcher tests remain the evidence for that interleaving.
Oversize error classification and download limits remain separate follow-up work.
No production transport, retry or public-deployment policy was changed.

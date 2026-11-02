# YouTube Shorts discovery investigation — 2026-11-03

Requested source: [HoneyTheGingerGirlCat Shorts](https://www.youtube.com/@HoneyTheGingerGirlCat/shorts).
Baseline: `2b347bc2c64c43e621723646411f483726c99f20`.

The heading uses the owner's Tehran date. Observations occurred on November 2
UTC (November 3 in Tehran); machine-validated context capture/verification dates
use that UTC observation date to remain valid on UTC CI runners.

## Verified result and live-access limitation

Current code can process an individual YouTube video URL through the existing
media path. It does not implement automatic channel scraping, a watchlist,
candidate pagination/ledger or a four-hour scheduler. Evidence:
[CLI parser](../cats_channel/cli.py), [single-video URL normalization](../cats_channel/media.py),
[MediaService](../cats_channel/services/media_service.py), [migrations](../alembic/versions/)
and the absence of a discover command in the inspected CLI.

Playwright navigated to the requested public channel Shorts page and reached the
YouTube consent screen. The first Reject all action encountered an automatic
approval timeout. One retry dispatched the click but timed out waiting for
navigation. The next snapshot showed chrome-error://chromewebdata/ with
ERR_CONNECTION_CLOSED: YouTube unexpectedly closed the connection.

Consequently no stable channel ID, video IDs/counts, dates, classification,
pagination behavior or download availability were verified. The handle is a
user-supplied discovery target, not a verified immutable identity. No extractor,
shell HTTP or alternate browser was substituted. No media was downloaded or
sent. Local Playwright snapshots remain untracked, outside evidence committed here.

Exact browser tools invoked: mcp__playwright_global__browser_navigate,
mcp__playwright_global__browser_snapshot, mcp__playwright_global__browser_click.

## Proposed automatic collection boundaries

The following is the existing issue plan, not implemented behavior or a claim
that a currently available provider API was live-qualified in this session.

| Slice | Responsibility / dependency | Acceptance evidence required |
| --- | --- | --- |
| [#18](https://github.com/SoloMidMiram/CatsChannel/issues/18) | Approved watchlist; resolve channel URL/handle to stable provider channel ID | alias/renamed/disabled-channel tests; no display-name identity |
| [#19](https://github.com/SoloMidMiram/CatsChannel/issues/19) | Metadata-only listing and classification; agree page/candidate result contract | empty/mixed/unknown metadata, pagination, rate limits and partial-page failure tests |
| [#20](https://github.com/SoloMidMiram/CatsChannel/issues/20) | Unique provider/video ledger, per-source safe checkpoints and bounded catch-up | duplicate/concurrent insertion, rollback, restart and outage-backfill tests |
| [#21](https://github.com/SoloMidMiram/CatsChannel/issues/21) | Six intended scans/day, four-hour interval; consumes #18–#20 | fake-clock overlap exclusion, one-channel failure isolation and missed-run catch-up |
| [#22](https://github.com/SoloMidMiram/CatsChannel/issues/22) | Opt-in rights/eligibility-gated acquisition, then durable submission and pending moderation | integration disabled by default; validated media only; idempotent handoff, no public sends |

Issue #19 proposes an official YouTube Data API metadata path and an explicitly
selected yt-dlp Shorts-tab listing path. Provider API capability, quota and current
access policy must be verified before selecting/implementing either adapter.
Duration alone is insufficient Shorts evidence; retain classification_unknown.
Channel listing must never call MediaService.acquire_async just to enumerate IDs.

## Honey channel investigation checklist

- [ ] Restore public page access through the normal approved browser route.
- [ ] Verify the immutable channel ID and bind the supplied handle as mutable metadata.
- [ ] Inspect a bounded metadata sample and pagination; do not assume latest 30 covers outages.
- [ ] Record actual available Shorts evidence and missing fields without guessing.
- [ ] Confirm owner-approved acquisition/redistribution policy before any #22 handoff.
- [ ] Exercise the provider contract using synthetic fixtures before an opt-in live smoke.

Source approval is not human publication approval. A discovered video is neither
downloaded nor validated nor moderated. Future normal intents must route by stable
source; choose the logical tail at approved finalization, not scan time. Exact-parent
interactive branches remain separate. Human approval is mandatory before product
publication, and ambiguous external sends never authorize automatic retries.

This task does not implement the discovery scheduler. Repository mapping and #8
audited rejection/isolation proceed independently; discovery #18 can be developed
separately once the channel identity contract is agreed. No public readiness claim.

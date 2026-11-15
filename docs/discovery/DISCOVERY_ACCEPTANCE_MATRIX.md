# Discovery acceptance matrix

Baseline main `ad653687a91e9b0a2c4c770bc23606fadebe5cbf`, verified November 15, 2026.
[PR #45](https://github.com/SoloMidMiram/CatsChannel/pull/45) merged the authorized watchlist and migration 0008.
[PR #46](https://github.com/SoloMidMiram/CatsChannel/pull/46) merged research contracts and offline fixture replay.
[Draft PR #47](https://github.com/SoloMidMiram/CatsChannel/pull/47) records verdict E, inconclusive/blocked, and a supervised diagnostic. Historical Honey observations (48 loaded Shorts links) show partial tab evidence at capture time. They provide neither a current reference set nor complete channel coverage. Direct WSL and configured proxy experiments have distinct scopes. Production access requires separate evidence from the deployment host.

| Milestone | Offline gate | Live gate | Current status |
| --- | --- | --- | --- |
| M1a known-video lookup | URL variants converge, returned ID matches, missing/error preserves source, zero acquisition | L1 returns metadata for Honey ID `jFITGy24prE` | Known-video lookup passes synthetic identity and missing/error fixtures. Live access gated |
| M1b channel enumeration | Resolver rename/mismatch/quota tests and two-page listing with nullable metadata, duplicates and bad cursors | L2 resolves the approved Honey handle and stable ID, L3 returns real IDs and observed continuation | Watchlist merged. Resolver and listing adapters pass synthetic tests |
| M2 Shorts-tab evidence | Keep uploads, candidate inference and direct observation distinct | L4 observes returned IDs on the verified channel tab and records provenance | Historical partial evidence. Offline UUSH harness prepared; live sample unqualified |
| M3 repeatable monitoring | Two channels and two pages, replay, new item, failed-page recovery, fenced ownership and zero duplicates | L5 repeats a real scan and verifies ledger/checkpoint behavior. Record actual new uploads only if observed | Synthetic one-shot and durable recovery passed on main at `ad65368` |
| Four-hour operation | Fake clock, exclusive ownership, bounded catch-up and failure isolation | Host operation and recovery qualification | Offline scheduler tests can proceed under #21. Live operation requires scanner and host qualification |

## Work packages

| Package | Owner | Result and dependency |
| --- | --- | --- |
| A Baseline | #1, #8, #17 | Reconcile merged evidence and current gates |
| B Known-video metadata | #19, supports #22 | Reuse URL normalization and audit durable source association before adding storage |
| C Channel resolver | #18 | Reuse the canonical registry and resolve the approved channel and uploads playlist |
| D Official uploads | #19 | Resolve, list and enrich candidates after B/C. No Shorts inference from duration alone |
| E Ledger and checkpoints | #20 | Develop alongside D after freezing the shared scan envelope |
| F Shorts-tab evidence | #19 | Optional provider after B/C, independently qualified from E |
| G One-shot scanner | #19/#20 | Combine D/E. Dry run by default, with an explicit durable mode. Candidate-only operation is possible without F |
| H Four-hour scheduling | #21 | Use offline fixtures from G to test one scheduler with bounded catch-up. Enable live operation only after host qualification |
| I Acquisition to review | #22 | After G and #7/#8 policy and recovery gates. Scheduling is independent |

Honey is the initial approved research source (`@HoneyTheGingerGirlCat`,
`UC0o-_FwPhZS5Xr0XTmwqwkw`). Keep scans disabled until qualified. Build a
reference set with historical Shorts observations, independently evidenced
ordinary uploads and ambiguous examples. Missing membership on an incomplete tab
leaves classification unknown. Preserve `shorts_tab`, `short_candidate` and
`unknown` with observation method, time, channel and adapter revision.

## Boundaries and evidence

- Use the [existing scan contract](AUTOMATION_ARCHITECTURE.md). Defaults are 30 enumerated items (including invalids/duplicates), two logical page attempts (including failures/retries), and 30 API requests (all outbound attempts). Legacy `ScanPolicy.page_budget` remains an item limit.
- Reuse `watched_channels.id` and the SQLAlchemy unit of work. Deduplicate on `(provider, video_id)` with immutable attribution. Commit a safe page cursor with its observations under fenced ownership. Advance the completed coverage watermark only on proven completion. Report incomplete coverage and backlog.
- Authorize L1–L5 separately. Retain sanitized evidence with revision, environment and route, provider version, budget and counts, IDs, membership evidence, cursor completeness and outcome. Direct WSL, configured proxy and production host results apply to their respective routes. Offline tests use fixtures. Discovery performs zero downloads, moderation decisions or Telegram sends.
- Preserve the requested source URL before acquisition. Source metadata can enrich the preview. Keep `source_identity_verified=false` for third-party downloader output unless the file identity is independently verified. The permission-gated bridge ends at human review.
- In parallel, #7/#8 own the publication-policy fence and review recovery. #9 owns exclusive poller supervision and production migration, restore and rollback. Merged audited rejection, startup isolation and disposable restore tests (#42–#44) are implementation or offline evidence. The bounded private receipt is separate from public release acceptance.

Production API-backed discovery requires [#51's policy and retention decision](YOUTUBE_API_POLICY_AND_RETENTION.md) and separately authorized live qualification. Offline resolver, provider and generic ledger work can proceed with synthetic fixtures. Issue #52 tracks a deferred link-only review workflow.

See the [design decisions](DESIGN_DECISIONS.md) and [weekly acceptance evidence](WEEKLY_ACCEPTANCE_2026-11-18.md).

The [bounded UUSH qualification package](UUSH_QUALIFICATION.md) is part of the
landed offline implementation. Its live evidence remains pending.

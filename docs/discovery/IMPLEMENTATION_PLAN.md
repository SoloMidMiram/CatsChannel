# Implementation plan

Research baseline `0d498a469f530eccd7b8b289a92334516f97d3a4` includes merged
watchlist PR #45. The [provider comparison](PROVIDER_COMPARISON.md) recommends the
Data API as the first identity/metadata adapter, subject to separately authorized
credential/quota qualification. [Experiments](EXTRACTION_EXPERIMENTS.md) distinguish
historical observations, offline replay and unexecuted live proposals.

| PR slice | Dependency | Reviewable acceptance |
| --- | --- | --- |
| #18 production resolver | D1 registry already merged | channels.list ID/forHandle normalization, strict returned identity, no arbitrary URL fetch; timeout/cancellation/quota/auth fixtures; authorization before provider calls |
| #19 provider protocol and API adapter | existing Entry/Candidate/PageResult; agree envelope with #20 | uploads playlist and metadata batching, bounded pagination, null preservation, classification unknown by default; explicit page/error semantics and no media calls |
| #20 ledger migration and repositories | existing watched_channels UUID and agreed #19 contracts | unique provider/video rows, immutable source, atomic observation/checkpoint CAS, actual SQLite/PostgreSQL migrations and rollback/restart tests |
| #19/#20 one-shot scanner integration | provider plus ledger | two-page success, second-page failure, expiry restart, duplicates, bounded backfill and partial observation commits without completed-watermark advancement |
| Optional #19 Shorts-tab adapter | explicit provider selection and approved metadata-only evidence | pinned yt-dlp output, ownership/timeout cleanup, known nulls, tab evidence, no automatic fallback; full pagination qualification before unattended use |
| #21 single-process orchestration | qualified scanner and durable run ownership | fake clock, overlap/stale-owner fencing, one-channel failure isolation, persisted retry budgets, backlog/reporting and dry-run side-effect checks |
| #21 host scheduling documentation | one-shot acceptance | one operator-reviewed four-hour scheduler, persistent state and host-offline recovery procedure; activation separately authorized |
| #22 acquisition bridge | future separate scope | explicit permissions, durable handoff and human moderation; discovery remains independently usable |

Each implementation PR must use current main, a precise diff, focused and supported
full tests, context validation/generation and Ubuntu/Windows/PostgreSQL CI on its
actual head. Preserve initial failures. Do not rerun live probes as a CI prerequisite.
Provider and ledger implementation can proceed independently after their envelope
and failure semantics are agreed. A production resolver and #19 adapter may share
a small transport/configuration boundary without creating a generic orchestration
framework or another source registry.

## Repository inspection and reconciliation

Current sources are [discovery](../../cats_channel/discovery/),
[SQLAlchemy registry](../../cats_channel/persistence/discovery_repositories.py),
[model owner](../../cats_channel/persistence/models.py),
[UoW](../../cats_channel/persistence/database.py),
[migration](../../alembic/versions/0008_discovery_watchlist.py) and
[tests](../../tests/test_discovery.py). Existing MediaService is single-video
acquisition and must not enumerate channels. Bot intake, review, publication and
their recovery owners remain independent of metadata discovery.

README accurately introduces D1 and defers live resolution/scans. Repository and
workflow maps retain earlier baseline tables plus a D1 correction; add a prominent
current-state view in a separate reconciliation slice rather than erasing evidence.
The historical YouTube investigation must retain its original dates and failures.
The roadmap and Issues #17-#22 contain October planning baselines. Before implementing
the next slices, update #18 to merged registry/remaining resolver, #19 to the agreed
provider semantics, and #20 to reuse watched_channels instead of creating a registry.
Keep #21/#22 open. This research PR does not alter their checklists or claim delivery.

## Remaining evidence gaps

No new channel/provider probes, API credentials or quota were used. Live resolver
behavior, provider pagination/expiry and unattended extraction remain unqualified.
Historical Honey evidence proves loaded tab membership only. API metadata does not
prove Shorts membership, rights or geometry. The next implementation must include
all synthetic cases in the experiment matrix before an opt-in live qualification.

The acceptance decision for this research is a documented design and replayable
offline evidence. It grants no scheduler activation, acquisition or release approval.

The [shared envelope and budget contract](AUTOMATION_ARCHITECTURE.md#shared-scan-envelope-acceptance-contract)
is frozen for D2/D3 implementation. The first integration acceptance is two synthetic
channels, two pages each, failed-page recovery, independent channel progress and
zero duplicates. Four-hour scheduler delivery follows this acceptance. The ordinary
pytest suite runs the historical fixture replay; this gate proves DTO compatibility
only. Live extraction and the recommended Data API adapter remain unqualified.

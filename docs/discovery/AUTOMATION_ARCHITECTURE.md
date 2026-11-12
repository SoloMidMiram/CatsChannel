# Discovery automation architecture

Baseline `0d498a4` implements [WatchlistService](../../cats_channel/discovery/service.py),
[domain DTOs](../../cats_channel/discovery/domain.py),
[repository protocols](../../cats_channel/discovery/contracts.py),
[SQLAlchemy registry](../../cats_channel/persistence/discovery_repositories.py) and
[migration 0008](../../alembic/versions/0008_discovery_watchlist.py).
The [D1 contract](../DISCOVERY_WATCHLIST.md) defines trusted-local authorization,
normalization, version checks, bounded history and scanner filtering. Provider
awaits occur outside database transactions. Registry writers serialize through the
existing UoW and control row. No production resolver, scanner, candidate ledger,
scan-run store, scheduler or acquisition bridge exists at this baseline.

```mermaid
flowchart TD
  Operator[Implemented trusted-local operator policy] --> Registry[Implemented D1 watchlist and migration 0008]
  Resolver[Implemented resolver protocol; planned production adapter] --> Registry
  Registry --> Inputs[Implemented resolved enabled unretired Entry snapshots]
  Inputs -.-> Provider[Planned D2 metadata provider]
  Provider --> Normalize[Planned candidate validation and classification]
  Normalize --> Ledger[Planned D3 deduplicated candidate ledger]
  Ledger --> Checkpoint[Planned atomic safe page checkpoint]
  Checkpoint --> Result[Planned observable scan outcome]
  Timer[Planned D4 four-hour scheduler] --> Claim[Planned exclusive scan claim]
  Claim --> Inputs
  Result --> Timer
  Ledger -. future rights gate .-> Bridge[Planned D5 acquisition then human moderation]
```

The scheduler triggers the scanner; it does not decide source identity or eligibility.
Observed outcomes determine the next eligible attempt time. No discovery component
chooses a Telegram reply parent or approves publication.

## Provider and normalization contract

Add a protocol beside the existing contracts in #19.

```python
async def list_page(
    entry: Entry, cursor: str | None, configuration: ProviderConfiguration
) -> PageResult: ...
```

Use existing Candidate, PageResult, Status and ProviderConfiguration DTOs. Every
candidate must match entry.channel_id, have a valid video ID and constructed URL,
bounded title/evidence, timezone-aware timestamps and finite optional duration.
Do not infer source identity from handles or titles. Map rendered membership to
shorts_tab, duration-based hints to short_candidate, and insufficient evidence to
unknown. Never infer not_short solely from missing membership in an incomplete tab.

Freeze three separate per-channel, per-run budgets for #19 and #20.

| Envelope field | Initial default | Accounting |
| --- | --- | --- |
| item_budget | 30 | every enumerated provider entry, including invalid and duplicate entries, before deduplication |
| page_budget | 2 | every logical listing-page attempt, including retries and failed pages |
| api_request_budget | 30 | every outbound API request attempt, including resolution, metadata batches and retries |

D1's persisted ScanPolicy.page_budget retains its documented legacy item meaning.
At the adapter boundary, map it to envelope.item_budget. Do not reinterpret that
stored column as a page count or silently migrate existing operator policy. The
new envelope page_budget is explicitly distinct from the legacy field. A future
rename must be a separate compatibility change. ProviderConfiguration.request_budget
supplies api_request_budget. Snapshot these limits in the configuration fingerprint.
Page/item limits and byte/runtime ceilings are separate execution configuration.
Counters span the entire invocation and never reset after retry or cursor expiry.
Budget exhaustion yields budget_exhausted, not completed; resumed invocations get
new bounded counters while retaining durable coverage/backlog state.

For flat extraction, entry limits do not prove a bound on internal HTTP requests.
Before approving a strict-request-budget live experiment or unattended adapter,
instrument/enforce those requests or record that the experiment cannot satisfy its
budget and leave it unexecuted. Do not claim an extractor entry cap is an API-call cap.

## Page completion and scan completion

PageResult.state=complete means one page was retrieved and validated completely.
It may still have next_cursor. The existing checkpoint_may_advance property permits
safe page progress only; it does not prove the entire scan is complete. A partial
page may contain usable observations but retains the cursor used to request it.
A failed page provides a bounded failure classification, never an empty success.
Cancellation propagates and leaves committed prior pages intact.

Proposed run outcomes are running, completed, budget_exhausted, partial, failed,
cancelled and interrupted. Mark completed only after a terminal provider page or a
documented safe coverage boundary. Budget exhaustion leaves catch-up pending.
Provider order and publication dates alone are insufficient completeness evidence.

Persist a scan envelope in #20 with registry UUID, immutable channel ID, adapter
and version, configuration/policy fingerprint, input and next cursor, page index,
coverage target, counts, owner/version, timestamps and bounded failure reason.
Bind opaque cursors to that envelope. Reject wrong-provider/source/version reuse.
Detect repeated cursor loops. On expiry, restart from a bounded overlapping window
and deduplicate; preserve the previous completed watermark until coverage is proven.
If the budget cannot reach the old boundary, expose backlog and request bounded
operator backfill. Never silently skip older unseen uploads.

Within one UoW, upsert validated page observations and advance its safe cursor
with owner/version CAS. A crash before commit replays the page; a crash after
commit resumes its saved next cursor. Failed/partial pages cannot move the completed
watermark. Terminal completion updates last_successful_full_scan separately.

## Ownership, storage and failures

| Issue | Sole responsibility |
| --- | --- |
| #18 | existing canonical registry plus production channel resolution |
| #19 | provider listing, normalization and classification |
| #20 | candidate/run/checkpoint tables referencing watched_channels.id |
| #21 | one-shot execution, exclusive claim, scheduling and observability |
| #22 | separately authorized rights/eligibility gate and acquisition handoff |

Candidate uniqueness is (provider, video_id). Preserve immutable source association;
conflicting channel attribution is ambiguous/quarantined, never reassigned silently.
Keep first_seen, last_seen, latest metadata and observation provenance distinct.
Preserve prior known metadata when later providers omit it, while recording the
new observation's nulls and timestamp. Do not create CatVideoSubmission at discovery.
Recheck enabled/retired state and identity before committing work or scheduling a
future handoff. A watchlist snapshot does not confer continuing authorization.

Map rate/quota to rate_limited, TLS/connection/timeout to temporary_failure,
unusable input to invalid_input, and identity conflicts to ambiguous. Unavailable
means inaccessible according to evidence; do not invent a private/deleted cause.
Keep authentication/configuration, cursor expiry, malformed output and quota subtype
as bounded scan reason codes. Unexpected exceptions are sanitized temporary failures.
One channel's failure does not discard other channels' committed pages.

Start with no automatic inline retries. #21 can persist an explicit bounded policy
for idempotent reads with request-budget accounting, capped attempts, jitter and
retry-after. Quota exhaustion waits for the provider's permitted retry window;
credential/configuration failures require operator correction. Never disable TLS
verification or silently change adapter. No DB transaction spans provider I/O.

## Eventual single-process execution

One scanner process uses the existing database and a short transactional run claim
with owner/version fencing. A single host lock prevents overlapping invocations;
restart marks abandoned owners interrupted before resuming safe boundaries. Any
future expiring lease requires fencing every checkpoint commit so a stale owner
cannot overwrite a newer run. Keep concurrency at one initially.

Propose one Windows Task Scheduler deployment for this Windows-oriented host,
invoking a future discover --once every four hours in UTC. The operator must supply
a persistent DB path, locked environment, logs and secret configuration before
activation. Host sleep/offline time creates backlog; next invocation performs
bounded catch-up, not one scan per missed tick. No schedule is created here.
Use structured run/source counts, failure categories, backlog and last-full-scan
age without credentials or unnecessary response bodies. dry-run may emit a report
but writes no candidate, checkpoint, queue or watchlist mutation.

## Shared scan envelope acceptance contract

The following is the agreed design boundary for subsequent feature PRs. It is not
an implemented production DTO or successful live-provider qualification.

| Field | Meaning |
| --- | --- |
| watchlist_id, channel_id | canonical watched_channels UUID and immutable provider channel ID; no duplicate registry |
| provider, adapter, adapter_version | youtube plus selected implementation/version; provider switching requires a new run |
| configuration_fingerprint | deterministic hash of nonsecret adapter settings, policy, coverage target and all budgets; exclude credentials |
| input_cursor, next_cursor | opaque provider-scoped page progress; no cursor means initial/terminal only in conjunction with page outcome |
| page_outcome | complete, partial or failed, using existing PageResult; absent before an attempt |
| run_outcome | running, completed, budget_exhausted, partial, failed, cancelled or interrupted |
| owner_id, ownership_version | exclusive attempt owner and monotonically fenced generation checked on every commit |
| item_budget, page_budget, api_request_budget | separately snapshotted limits with matching consumed counters |

Store run_id, page index, timestamps, bounded reason and retry-after alongside the
envelope. Cursor progress and completed coverage are separate records/fields.
last_successful_full_scan_at and its covered boundary change only on proven run
completion. Never derive them from PageResult.checkpoint_may_advance. Complete
pages with a next cursor may commit observations and page progress while the full
scan watermark remains unchanged. Partial/failed pages retain their input boundary.

The next acceptance target is two synthetic channels with two pages each. Fail
channel A's second page, complete B independently, then restart A and replay its
failed page. Assert one candidate per provider/video, prior-page durability,
unchanged A completion watermark until recovery, stale-owner CAS rejection and
zero media/Telegram calls. Exercise item, page and request budgets independently.

The opt-in YouTube channel resolver implements the existing watchlist port. It accepts an
application-owned aiohttp session and a runtime key, makes one bounded channels.list request,
and returns the stable channel identity and optional uploads playlist in its resolution.
The registry retains its existing schema and version checks. The uploads reference is transient.
Production wiring and use require #51 clearance and separately authorized live qualification.

The offline playlist adapter shares the resolver's fixed-endpoint transport. Each page
attempt permits at most one HTTP send, including aiohttp reconnect behavior. The
caller supplies the remaining item allowance capped at 50 and counts the raw
items_examined field before deduplication. Invalid or unverified items make a page
partial, so it cannot advance the checkpoint. The scan coordinator owns run-wide
request and page budgets, cursor binding, multi-page loop detection, and restart.

Uploads use the playlist returned by channel resolution. Experimental UUSH must
be selected explicitly and reports shorts_playlist evidence separately from
shorts_tab. Neither route is registered in runtime configuration. An empty page
is an observed response and does not qualify UUSH against known Shorts.

# Extraction experiments and offline evidence

The approved research source is HoneyTheGingerGirlCat, stable channel ID
`UC0o-_FwPhZS5Xr0XTmwqwkw`. Existing observations are dated evidence, not fresh
provider qualification. The [original investigation](../YOUTUBE_DISCOVERY_INVESTIGATION.md)
records browser identity agreement, 48 distinct loaded Shorts links, incomplete
pagination and a ten-entry flat extractor probe that returned zero entries after
TLS EOF. That failure is not an empty successful scan.

[Observed fixture](fixtures/honey-observed.json) preserves one real link and title
from the retained snapshot captured at 2026-11-02T22:49:58.898Z. That is the snapshot
capture time, not a provider publication time. The title's U+FFFC character is
retained. Date, duration and geometry remain null. Channel binding is inherited
from the original investigation's canonical-ID checks. The raw local browser
snapshot remains outside Git; the sanitized fixture and source-linked report are
the portable evidence. No claim of independent contemporary channel verification
is made. [Failure fixture](fixtures/honey-failure.json) retains the known failure
category and observation date without inventing an exact failure timestamp.

Replay the fixtures without network access from the repository root.

```powershell
.\.venv\Scripts\python.exe docs/discovery/fixtures/replay.py
```

The replay constructs current Candidate/PageResult DTOs, verifies nulls, canonical
URL and checkpoint eligibility, and constructs a synthetic partial-page case.
It validates the research evidence representation, not provider pagination.
`tests/test_discovery_research.py` executes this same script in the ordinary pytest
suite, including the existing Ubuntu and Windows CI jobs. DTO incompatibility or
fixture assertion failure therefore fails automated verification. These historical
observations do not qualify current live extraction or a production API adapter.

## Proposed opt-in live protocol

Each experiment needs separate operator authorization identifying adapter, channel,
request/runtime/output budgets and any credential/quota use. No new live channel
experiment was executed for this research. Use Honey first; add a second mixed
channel only after the operator supplies and approves its identity.

| Experiment | Proposed bounds | Pass condition |
| --- | --- | --- |
| API identity and metadata | one channel, at most 5 calls, 120 seconds, 2 playlist pages of at most 10 entries each, at most 20 normalized candidates | returned channel IDs agree; exact metadata or null; next token and stopping reason retained |
| Flat Shorts extractor | one canonical /channel/ID/shorts URL, 10 entries, 60-second process limit, 10-second socket timeout, zero retries | output identity checked; missing metadata remains null; failure is explicit |
| Rendered diagnostic | signed-out browser, 10 links, one continuation action, 90 seconds | channel and tab evidence recorded; loaded count clearly distinguished from completeness |

The API five-call budget allows one channels.list, two playlistItems.list and two
videos.list batches. Failed calls consume the same budget; no automatic retries.
Use snippet/contentDetails metadata only. Never request media, thumbnails,
subtitles, streams or owner-only file details. Never use cookies or bypass consent
or access restrictions. Browser experiments must block media/thumbnail requests
before channel navigation and verify that block in network evidence; otherwise do
not run them under this experiment's zero-media constraint.

The extractor must ignore local configuration, force flat extraction and simulation,
disable media/thumbnail/subtitle writing, cap entries and total process runtime,
and return only an allowlisted normalized JSON projection. Bound stdout/stderr
capture and kill/drain owned processes on timeout. Do not call MediaService.
Archive sanitized metadata and versions, never keys, cookies or raw private errors.

Record adapter/version, configuration fingerprint, UTC observed_at, canonical
channel ID, per-item evidence, requests, elapsed time, counts, cursor and stopping
reason. Zero media transfers, zero Telegram calls and zero production writes are
mandatory. Repeat a successful bounded observation once only under an approved
combined budget. Compare identities, nulls and duplicates; changing channel content
is not automatically a regression.

## Required synthetic qualification matrix

Add fixtures for two complete pages, a failed second page, mixed Shorts/ordinary
videos, missing duration/date/title, wrong channel, invalid video IDs, aliases,
duplicates, quota/rate limits, forbidden/missing videos, invalid/expired cursor,
changed extractor output, cancellation, oversized output and cursor loops.
Synthetic records must be labeled separately from Honey observations. Failure or
budget exhaustion never advances the completed-scan watermark. A successful empty
terminal page needs positive provider evidence, not merely zero parsed candidates.

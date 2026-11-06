# Provider test matrix

Statuses apply to demonstrated capabilities in this investigation, including
explicitly labeled historical evidence. Documentation alone does not establish PASS.

| Capability | Data API | yt-dlp Shorts | Browser inspection |
|---|---|---|---|
| Resolve channel identity | BLOCKED | FAIL | PARTIAL |
| Enumerate candidate video IDs | BLOCKED | FAIL | PARTIAL |
| Confirm Shorts-tab membership | NOT SUPPORTED | BLOCKED | PARTIAL |
| Retrieve exact publication dates | BLOCKED | BLOCKED | BLOCKED |
| Continue through multiple pages | BLOCKED | BLOCKED | BLOCKED |
| Detect new videos on repeat checks | BLOCKED | BLOCKED | BLOCKED |
| Recover from interrupted enumeration | BLOCKED | BLOCKED | BLOCKED |
| Operate without media downloads | BLOCKED | PARTIAL | BLOCKED |
| Suitable for four-hour unattended monitoring | BLOCKED | BLOCKED | BLOCKED |

Data API entries are BLOCKED because no approved credential/quota request was
executed. Current official documentation confirms ID/handle lookup, uploads
playlist traversal, page tokens, title/publication metadata and duration. It does
not prove all-public-upload completeness or stable incremental pagination for
Honey. The documented video resource has no authoritative Shorts membership flag,
so that capability is NOT SUPPORTED through the assessed resource. File geometry
is owner-only data; missing video metadata stays unknown. Public publication time
must not be conflated with original upload time or playlist insertion time.

yt-dlp identity and enumeration FAIL within the authorized ten-entry experiment:
exit 1, no entries, no returned channel identity. Metadata, membership, continuation
and repeat/recovery cases are BLOCKED by that failure. No-media operation is PARTIAL:
flat/simulation/download-writing protections were selected and no entries reached
processing, but independent transport/media-transfer accounting was not captured.
No end-to-end pagination or unattended-success claim follows from these flags.

Browser identity, enumeration and tab membership are PARTIAL historical evidence
from November 2 only. There were 48 distinct loaded links and canonical-ID agreement;
no complete pagination, dates, repeat checks or recovery was qualified. No fresh
channel-browser scope was authorized, and media blocking/traffic accounting was
not demonstrated historically. Therefore no-media operation remains BLOCKED.

All unattended entries are BLOCKED by missing live coverage, repeated checking,
durable recovery and operational acceptance. None is evidence of impossibility.

## Offline simulation evidence

`tests/test_discovery_feasibility.py` exercises current Candidate/PageResult DTOs
with synthetic, in-memory persistence. It covers terminal two-page completion,
failed second page with preserved first-page observations/input boundary,
service-view restart/replay, two independent channels, wrong identity rejection,
overlapping new IDs, reordered/absent IDs without false deletion, known-title
preservation on a later null, separate item/page/request/runtime exhaustion and
explicit synthetic cursor-expiry restart.

Every simulation is metadata-only. No provider object or network client is used.
Each synthetic page costs one simulated request, unlike real metadata enrichment.
Runtime exhaustion is injected deterministically, not an elapsed-time benchmark.
Dictionary deduplication demonstrates the contract, not concurrent database
uniqueness or durable recovery. Fencing, provider deletion semantics, real cursor
expiry, host downtime and throttling remain implementation/evidence gaps.

The simulation's provider pages are keyed by their input cursor. Its request log
asserts the sequence initial/page-2/page-2 across failure and restart, so recovery
must actually use the saved boundary. Page/request/runtime limits are checked
before reading another simulated provider page. An unavailable next page produces
partial status rather than synthetic terminal completion. These checks strengthen
the simulation without converting it into a live or durable-recovery claim.

Official references inspected with Playwright on November 6 are
[channels.list](https://developers.google.com/youtube/v3/docs/channels/list),
[playlistItems.list](https://developers.google.com/youtube/v3/docs/playlistItems/list)
and [videos](https://developers.google.com/youtube/v3/docs/videos). Channel and
playlist listing cost one unit per documented call; pages accept up to 50 items.
No API call was made. Provider docs are separate evidence from channel access.

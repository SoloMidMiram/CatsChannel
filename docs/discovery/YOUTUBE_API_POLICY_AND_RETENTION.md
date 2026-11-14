# YouTube API policy and retention

Reviewed 2026-11-12 against the published [YouTube API Developer Policies](https://developers.google.com/youtube/terms/developer-policies) and [API Services Terms](https://developers.google.com/youtube/terms/api-services-terms-of-service).

## Decision for #51

**Requires written clearance before production use.** Section III.E.2 limits aggregation to channels under the same YouTube-recognized content owner and limits visibility to that owner. CatsChannel proposes one operator queue spanning unrelated owners. Obtain written YouTube guidance on that exact flow before enabling it, including the operator audience and any proposed joins, ranking or classification. Creator media rights and API-data permissions require independent evidence. Private deployment, separate tables and hashed IDs do not establish permission.

Section III.E.4 requires limited public API data and ordinary authorized metadata to be refreshed or deleted within 30 calendar days. Approved statistics and reporting exceptions do not establish an exception for this pipeline. Section III.E.4 also restricts derived data. The policy gives applicable user deletion requests a seven-calendar-day limit and section III.D addresses revocation and deletion within 30 calendar days. Apply the earliest applicable deadline.

## Proposed data handling if approved

| Data | Storage and deletion design |
| --- | --- |
| API-returned channel and video IDs, handles, uploader IDs, uploads references and URLs made from them | Track API provenance and observation time. Refresh from the permitted source or delete at expiry, including indexes and dependent records. Preserve independently supplied references only with independent provenance and a documented basis. |
| Titles, descriptions, publication timestamps and playlist membership | Keep only needed fields. Expire each observation from its successful retrieval time. Refresh replaces the current value and does not renew historical copies. Omit descriptions unless required. |
| Derived classification, deduplication keys, hashes and tombstones | Require explicit review before storing derived fields. Until approved, design without permanent API-derived deduplication artifacts. |
| Pagination tokens | Keep opaque and restricted to the originating provider, channel, query and run. Discard on completion, invalidation or expiry. Recover with bounded overlap. |
| Logs and quota accounting | Use local run IDs and sanitized outcomes and counters. Exclude response bodies, resource identifiers, request URLs, credentials and cursors. |
| Caches, exports and backups | Include all copies in the deletion design. Suppress expired data on reads, purge on schedule, and enforce expiry and deletion before restored data becomes accessible. |

When an item becomes inaccessible or consent is withdrawn, stop serving the affected data, stop refresh where access is unavailable, and purge within the applicable deadline. Require expiry, request deletion, revocation and restore tests before real ingestion. The API-data policy decision remains open until these controls and the permitted flow are reviewed.

Offline engineering can use synthetic fixtures. Keep UUSH experimental and distinguish observed playlist membership from independent Shorts-tab evidence. A future live qualification needs a separately authorized request budget, source, route and evidence plan. The November 6 verdict remains historical. If the API route cannot be cleared, evaluate creator-provided originals or a properly licensed metadata provider. Issue #52 tracks link-only review independently.

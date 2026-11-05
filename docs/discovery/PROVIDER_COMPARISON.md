# Provider comparison

Research baseline `0d498a469f530eccd7b8b289a92334516f97d3a4`, verified on
2026-11-06 Tehran. PR #45 and migration 0008 are merged. These are design
recommendations; provider implementations have not been activated.

| Property | YouTube Data API v3 | Explicit yt-dlp Shorts adapter | Rendered Shorts page |
| --- | --- | --- | --- |
| Identity | channels.list by ID or forHandle; verify returned ID | validate canonical channel identity and every returned video identity | canonical channel URL plus loaded link evidence |
| Metadata | snippet title/publishedAt and contentDetails duration; uploads playlist | flat entries can omit title, dates, duration and geometry | visible title/URL; dates and duration often absent |
| Shorts evidence | no universal authoritative is_short field in inspected video schema | validated Shorts-tab membership supports shorts_tab | loaded Shorts-tab membership supports shorts_tab |
| Pagination | playlistItems nextPageToken; up to 50 items per page | extractor-owned continuations; public flat output may lack a durable cursor | loaded DOM is a partial observation; scrolling is not completeness proof |
| Authentication/cost | approved API project/key and quota; public reads need no channel-owner OAuth | no API key for public pages; network/compute and maintenance costs remain | signed-out browser, consent handling, substantial browser cost |
| Failure | classify quota/rate, forbidden, not found, malformed and transport separately | TLS EOF, throttling, changed output, unavailable pages; no empty-success masking | consent, connection closure, incomplete DOM and blocked navigation |
| Maintenance | documented resource and token contract | pin version and requalify output changes | fragile rendering and UI changes |
| Unattended suitability | preferred baseline for public metadata after qualification | opt-in specialist adapter after bounded pagination qualification | diagnostic evidence only |

Choose the Data API as the minimum viable provider for reliable identity and
metadata enumeration. Its first output is a candidate inventory, with uncertain
Shorts classification preserved. A requirement for confirmed Shorts-tab membership
requires a separately selected, qualified adapter. Never switch providers after a
failure or merge their cursors. Geometry from owner-only fileDetails or thumbnail
dimensions must not be presented as public video geometry.

Channel resolution, playlist enumeration and video metadata calls each have a
documented one-unit request cost. One channel lookup plus P playlist pages plus V
metadata batches costs 1 + P + V units, excluding retries. Six scans/day multiply
that request budget by six per enabled channel. Default quota allocation and
commercial operating cost are deployment inputs, not a throughput guarantee.
Avoid search.list for ordinary uploads enumeration. Partial field selection reduces
payload; it does not justify assuming a lower quota charge.

Duration at most 180 seconds supports short_candidate only. Preserve unknown when
duration or corroborating evidence is missing. A tab observation proves membership
at the observation time, not permanent membership or redistribution permission.
Approximate extractor dates remain provenance, not exact published_at timestamps.

Source references are [channels.list](https://developers.google.com/youtube/v3/docs/channels/list),
[playlistItems.list](https://developers.google.com/youtube/v3/docs/playlistItems/list),
[videos](https://developers.google.com/youtube/v3/docs/videos),
[videos.list](https://developers.google.com/youtube/v3/docs/videos/list) and
[yt-dlp options](https://github.com/yt-dlp/yt-dlp#usage-and-options).
Google references were inspected with Playwright in the preceding November 5
investigation. The refresh during this research returned an empty body; it adds
no new API evidence. The yt-dlp options were reread successfully. No provider
endpoint, channel probe, credential or quota-consuming request was executed.

See [experiments](EXTRACTION_EXPERIMENTS.md), [architecture](AUTOMATION_ARCHITECTURE.md)
and [implementation plan](IMPLEMENTATION_PLAN.md).

# Discovery design decisions

Decision record reviewed on 2026-11-12. The [policy and retention memo](YOUTUBE_API_POLICY_AND_RETENTION.md) defines the #51 gate.

| Decision | Current choice |
| --- | --- |
| Source identity | Reuse the canonical watchlist and stable YouTube channel ID. An uploads playlist is transient metadata returned by the resolver. |
| UUSH | Explicit experimental selection via the documented playlist-items endpoint. Live qualification requires written policy clearance and separate authorization. |
| Evidence | Keep observed UUSH membership, independent Shorts-tab evidence, and unknown uploads distinct. Use uploader identity and video publication time from the listing item. |
| API-data aggregation | Written clearance is required for the proposed operator queue spanning unrelated owners. |
| Retention | The offline ledger admits synthetic data with explicit expiry. Production retention, refresh, deletion, derived data and restore behavior require the approved field-level policy. |
| Cursor and coverage | Bind cursor progress to the provider, channel, cycle and configuration. Resume the safe boundary after failure. For an expired cursor or loop, use one bounded restart per invocation and deduplicate. Advance full coverage only on a terminal complete page. |
| Budgets | Count raw items, logical page attempts and request attempts separately. Defaults are 30 items, two page attempts and 30 request attempts per channel invocation. A listing attempt permits at most one HTTP send. |
| Acquisition | Keep discovery metadata-only. Creator-provided media uses independently approved intake. Issue #52 tracks link-only review independently. |

The historical November 6 feasibility verdict remains E. [Research PR #47](https://github.com/SoloMidMiram/CatsChannel/pull/47)

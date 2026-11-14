# Bounded UUSH qualification

The qualification package is offline-tested. Run on the deployment host only
after written policy clearance under #51 and separate approval for the source,
API project, route, budget and evidence handling. Preserve the historical
November 6 verdict E independently.

## Inputs and scope

- One independently verified stable channel ID, plus an ID or handle to resolve.
- Five independently selected known Shorts from the expected first two pages.
  Record the selection source and observation time before the API run.
- Whether independent evidence establishes that pagination should be present.
- An isolated aiohttp session with normal TLS verification, a dummy cookie jar,
  environment trust disabled, no authentication headers, and no proxy or custom
  connector unless the approved deployment route expressly calls for one.
  Keep the API key in runtime secret configuration.

The harness uses one channels.list request and at most two playlistItems.list
requests with ten items per page. It stays under the five-request ceiling and
does not spend the unused budget on enrichment. It performs no retries, media,
OAuth, cookies, or Telegram actions. It validates stable uploader identity and
video publication timestamps. Continuations are used only in the current call
and never included in the evidence report.

## Evidence and verdict

Call qualify_uush with the approved inputs. Record the deployment route and
observation time, request attempts and reserved quota units, observed HTTP
statuses, page sizes, continuation presence, and the sanitized outcome.
Reserved units are an upper bound for these one-unit read requests. A missing
HTTP status leaves receipt and billing unconfirmed.

If the outcome is manual_review_pending, an authorized reviewer checks the five
returned sample IDs against independent Shorts-tab evidence, including items
around the observed page boundary. Feed the five verdicts to review_sample.
This step performs no API calls. Record the observer, timestamp and provenance
under the approved evidence-retention policy. Keep identifiers and credentials
out of shared logs, issue bodies and CI artifacts.

A matching sample qualifies only the sampled source and route. An empty
playlist despite known Shorts or an uploader mismatch fails. An unavailable
playlist is inconclusive. A malformed or partial page is incomplete. Missing
expected pagination or no distinct second page leaves pagination unqualified.
A known Short outside the bounded sample is incomplete when more pages exist.

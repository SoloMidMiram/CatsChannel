# TriblettMarkou metadata pilot

**Verdict: BLOCKED at synthetic preflight.** The research baseline is
`148cc4ae906c79f3d42377e991ca7f5a630cfc2d`.
The [input fixture](fixtures/triblettmarkou-input.json) preserves the channel page
and three supplied videos. The [result fixture](fixtures/triblettmarkou-result.json)
records the preflight and the three unattempted lookups.

The Playwright MCP browser-code tool created a fresh context with zero initial
cookies, Service Workers blocked and downloads disabled. Synthetic HTML and its
script loaded metadata. The route handler blocked the thumbnail, media and
subtitle requests. Of eight request events, seven entered the route handler.
The redirected request was visible in request events and bypassed interception.
Its synthetic loopback destination failed. CDP Fetch could be enabled, but
complete coverage of redirects and child targets was not verified.

Execution controls are `request_budget_unverified`. YouTube navigations and
requests were zero. Tab enumeration, per-video metadata and uploader identity
were unattempted. Membership remains null for all three IDs.

The intended run has four top-level navigations, one scroll, a 90-second
deadline, a 150-attempt ceiling, zero authorized media bytes and an 8 MiB
observed non-media stop threshold. In-flight transfers can overshoot that
threshold. These are declared limits, not measurements from a YouTube run.

A future preflight needs interception coverage across redirects and child
targets before the live pilot. The pilot would enumerate the Shorts tab before
comparing supplied IDs, then verify video identity and field provenance from
the watch pages. Keep tab observation, video identity, uploader attribution
and execution-control verdicts separate.

Related [#17](https://github.com/SoloMidMiram/CatsChannel/issues/17),
[#19](https://github.com/SoloMidMiram/CatsChannel/issues/19), and
[draft PR #47](https://github.com/SoloMidMiram/CatsChannel/pull/47).

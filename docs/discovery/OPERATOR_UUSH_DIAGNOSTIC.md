# Operator-run UUSH diagnostic

The standalone `tools/uush_diagnostic.py` requires Linux, Python 3.11 or newer,
and only the standard library. It is research tooling, not a discovery adapter.
PR #47 retains verdict E; production monitoring and four-hour operation remain
unqualified. The accepted WSL observation is preserved separately in
[the historical fixture](fixtures/honey-uush-wsl-2026-11-06.json).

## Offline verification

Run on the operator's approved server only through the operator's own approved
access procedure. The agent has no authorization to connect or deploy tooling.
The default command runs synthetic checks and makes no public network requests:

```sh
python3.11 tools/uush_diagnostic.py
```

Its bounded JSON reports PASS/FAILED and test/error counts. Existing pytest CI
also invokes this default command. Self-checks include real isolated workers
stalled at DNS, TCP, TLS, HTTP and XML, with shortened supervisor deadlines.

## Separately authorized live run

Only after the operator approves the actual host, access method and this single
test, the operator may run the following once. The flag asserts that approval;
it does not grant it. No live run has been performed using this tool.

```sh
python3.11 tools/uush_diagnostic.py --live --operator-authorized --output honey-uush-server.json
```

Omit `--output` for stdout-only operation. Exit 0 means extraction PASS and a
reaped worker (or offline self-check PASS). Exit 1 means the evidence requires
inspection; exit 2 means invalid invocation. File-write errors return a fixed
error without disclosing paths. JSON and IPC each have a 64 KiB ceiling.

The fixed Honey endpoint is
`https://www.youtube.com/feeds/videos.xml?playlist_id=UUSH0o-_FwPhZS5Xr0XTmwqwkw`.
There is one DNS operation, one selected TCP attempt, verified TLS with SNI,
and at most one GET. IPv4 is preferred; there is no retry, fallback, proxy use,
cookie/session handling or redirect follow. Redirect destination values and raw
resolved addresses are never reported. No linked resource is requested.

The parent starts its clock before spawning the worker. The worker has 25
seconds; the parent sends termination at 26 seconds and kill at 27 seconds,
with reaping/reporting reserved before the 30-second overall target. Scheduler
delays or an OS process that cannot be reaped are reported, never treated as a
successful bounded run. Stage outcomes are SUCCESS, FAILED, TIMEOUT or
NOT_ATTEMPTED; a supervisor timeout retains earlier confirmed stages. Stage
durations use monotonic time. UTC timestamps describe the observation interval.
If the supervisor kills an HTTP-stage worker, the exact received byte count is
unknown: `response_bytes` is null and `response_bytes_confirmed_min` preserves
the last confirmed minimum. It never substitutes a stale zero for that unknown.

The receiver charges HTTP headers, framing and body together against 256 KiB
during reads. Unexpected compression, DTDs, custom entities and unsafe framing
are rejected. The parser validates the complete XML structure while collecting
at most ten entry records. Each collected record must explicitly match Honey's
channel ID and have a valid video ID; canonical links are constructed from those
IDs. Optional metadata stays null when absent. Titles are limited to 512
characters with a truncation indicator. No response bodies or arbitrary headers
are persisted. Only a safe content-type category is exposed.

## Reading the result

- Connectivity PASS means a verified TLS connection returned a valid HTTP
  response, including a redirect/error response. It does not imply extraction.
- Extraction PASS requires valid Atom/XML and at least one independently
  attributable record. Empty, malformed, mismatched or interrupted results do
  not pass. Structurally valid XML with rejected record metadata retains
  `xml_valid=true` while its XML stage fails.
- Shorts membership remains UNQUALIFIED. Neither UUSH naming, canonical watch
  links nor video duration proves membership. No duration is inferred.
- Pagination completeness, outage recovery, repeated monitoring and unattended
  operation remain unqualified after any successful result.
- DNS/TCP/TLS failure directs the next investigation toward infrastructure.
  HTTP success permits assessing the endpoint's behavior. Failures and empty
  feeds never establish that Honey has no Shorts.

Return the bounded JSON to the reviewer. It contains no raw IPs, private host
names, proxy values, credentials or certificate identities. Distribution IDs,
tool versions, selected address family and public video metadata are retained.
The tool does not independently measure public egress identity or guarantee
absence of transparent network routing.

# Live probe evidence

## Follow-up: bounded WSL UUSH diagnostic

The separately authorized [November 6 WSL result](fixtures/honey-uush-wsl-2026-11-06.json)
is **INCONCLUSIVE / ACCESS NOT QUALIFIED**, not Linux production PASS. Ubuntu
26.04 WSL2, Python 3.14.4 and OpenSSL 3.5.5 attempted the exact approved public
UUSH XML endpoint once. A 30-second signal deadline stopped the attempt; measured
elapsed time was 30.001 seconds including handling/cleanup. No HTTP status,
content type, redirect, response bytes or records were observed. XML validity,
identity, timestamps and Shorts membership are therefore unknown. The failure
phase (DNS/TCP/TLS/request/response) was not localized; the attempt count does not
prove an HTTP request reached YouTube. This is not evidence of an empty channel
or universal UUSH failure.

The standalone stdlib transport ignores proxy environment settings, uses verified
TLS, sends no cookies/authentication, retains no sessions and makes no retries or
media requests. It restricts requests to the exact approved HTTPS feed URL, counts
redirects against three requests, caps cumulative decrypted response reads at
256 KiB, and reports at most ten entries. No redirect was observed. WSL had a
default route and generated DNS configuration; public egress and transparent
host/VPN routing were not measured. Python 3.14 here is diagnostic tooling, not
qualification of the application's Python 3.11 runtime policy.

PR #47 remains E. Recent monitoring, historical enumeration and unattended
operation are all unqualified. UUSH's small implementation surface does not
qualify provider stability, pagination or completeness. Even a successful finite
recent feed would need an independent catch-up and recovery strategy. Naming a
playlist UUSH would not alone establish verified Shorts membership.

The smallest next experiment is the same bounded direct-HTTPS feed test on the
actual deployment server, after separate host/access and test authorization,
with stage timing to distinguish DNS, TCP, TLS and HTTP waits. No SSH, deployment,
server probe, additional WSL probe, API/quota call or library extractor is
authorized by this result. Retain nulls on failure and do not invent ten IDs.

## Earlier extractor and documentation evidence

One new yt-dlp probe was explicitly authorized and executed. No Data API probe or
new Honey browser probe was authorized or executed. Official documentation reads
used Playwright and are not API credential/quota experiments.

The [sanitized result](fixtures/honey-probe-2026-11-06.json) records observation start
2026-11-06T08:00:47.394964+00:00, yt-dlp 2026.8.19, Windows, exit 1 and 38.62 seconds.
There were zero entries and no returned identity, so neither Shorts membership nor
metadata nor pagination was verified. The only retained error marker was
Unable to download. Its classification is network_or_extractor_failure, with
root cause undetermined. Raw output was temporary and not retained; that limits
further diagnosis without separately authorized reproduction.

The equivalent extractor invocation below is a reproduction specification only.
The executed wrapper also removed proxy environment variables, bounded combined
stdout/stderr to 1 MiB, enforced a 60-second wall-clock deadline and sanitized the
result. It selected a canonical URL, no cookies, zero retries and no TLS bypass.

```text
python -m yt_dlp --ignore-config --flat-playlist --simulate --skip-download
  --no-write-thumbnail --no-write-subs --no-write-auto-subs --playlist-end 10
  --socket-timeout 10 --retries 0 --extractor-retries 0 --proxy ""
  --dump-single-json https://www.youtube.com/channel/UC0o-_FwPhZS5Xr0XTmwqwkw/shorts
```

The process completed before budget termination. No media-writing options were
enabled and there were no entries to process. Independent network/media byte
accounting was not collected, so zero-media transfers is not presented as a
measured result. No configured proxies, credentials, cookies or Telegram resources
were used. Historical fixtures and their facts were left unchanged.

Current official channels.list, playlistItems.list and videos documentation loaded
successfully. Inspected evidence includes ID/forHandle selection, uploads-playlist
pagination examples, nextPageToken, one-unit listing costs, publication fields,
duration and owner-only file metadata. No authoritative Shorts flag appeared in
the documented video resource. Read access to these docs is not API access proof.
Browser tools invoked were mcp__playwright_global__browser_navigate and
mcp__playwright_global__browser_evaluate.

Outstanding scopes are API credentials/quota (five total requests) and a new
signed-out channel diagnostic (ten links, one continuation, 90 seconds). Browser
media and thumbnail blocking must be established before channel navigation. No
additional channel is approved. The single successful future bounded experiment
would qualify its observed scope only, never complete unattended monitoring.

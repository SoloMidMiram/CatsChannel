# Bot API proxy diagnosis — 2026-10-25

## Observed failure

The configured Windows Xray listener at `127.0.0.1:10808` accepts both HTTP CONNECT
and SOCKS5 tunnels for `api.telegram.org:443`. Certificate-verified TLS then fails:
HTTP aborts and SOCKS resets. Restricting TLS to 1.2 also fails. These probes use
no bot token and send no Telegram messages, so this failure precedes bot identity,
authorization, polling, file download and publication.

Windows system DNS returned `10.10.34.35` and
`2001:4188:2:600:10:10:34:35` for `api.telegram.org`. Google's public DNS JSON API,
read with Playwright during this run, returned `149.154.166.110`.

Connecting through each same proxy protocol to that public IP while retaining
`api.telegram.org` as the TLS server name completed verified TLS 1.3 successfully.
Certificate verification remained enabled. This isolates the failure to the
hostname-dependent DNS/routing path rather than a generally broken proxy or
unsupported aiogram proxy protocol. The local private-address DNS result strongly
suggests DNS interference; the active Xray configuration was not inspected, so
proxy-side DNS resolution and domain-specific routing remain alternative causes.
The successful public-IP experiment is a diagnostic comparison, not a permanent
Telegram IP mapping or a completed Bot API identity check.

Earlier read-only Bot API identity checks failed from Windows and WSL. Direct
Windows access was refused. Turning off the application proxy therefore does not
currently establish a working direct route.

## Operator action

Inspect the Windows v2rayN/Xray DNS and routing configuration for
`api.telegram.org`. Ensure its DNS resolution uses a reachable trusted resolver
and its domain rule selects the intended working outbound. Xray can resolve a
domain during either routing or outbound processing; SOCKS remote DNS alone does
not guarantee a correct answer. Prefer correcting that path to hardcoding a
Telegram address, whose public DNS answer can change.

After correcting the route, run `python -m cats_channel --bot-diagnose` from the
pilot checkout and require `private_pilot_ready=true` before resuming its saved
downloader response. No live media or publication was sent during this diagnosis.

## Application proxy switch

In the ignored pilot `.env`:

```dotenv
BOT_API_PROXY=http://127.0.0.1:10808
BOT_API_PROXY_ENABLED=true
```

Set `BOT_API_PROXY_ENABLED=false` to select direct connections without removing
the saved address. Restart the bot after changes. The switch applies to all
aiogram Bot API operations and leaves Telethon and yt-dlp settings independent.
It does not disable an operating-system VPN or TUN route. Shell proxy variables
are not implicitly used by this session. No automatic fallback was added.

The pilot profile now explicitly contains `BOT_API_PROXY_ENABLED=true`. A live
read-only diagnostic with an environment override of `false` reported
`proxy_configured=true`, `proxy_enabled=false`, `proxy_in_use=false`, and
`proxy_scheme=null`; the direct network request still failed.

Validation: full Windows suite **458 passed, 62 skipped**; WSL transport suite
**32 passed**; Ruff lint, format and Git whitespace checks passed. A regression makes a real local Bot API request with the switch
off, a saved unusable proxy, and unusable shell proxy variables. Existing SOCKS
handshake regressions retain coverage of proxy-on routing and remote DNS.

## Sources and local evidence

- [aiogram AiohttpSession proxy documentation](https://docs.aiogram.dev/en/latest/api/session/aiohttp.html)
- [aiohttp proxy and environment behavior](https://docs.aiohttp.org/en/v3.13.2/client_advanced.html#proxy-support)
- [Xray built-in DNS](https://xtls.github.io/en/config/dns.html)
- [Xray routing](https://xtls.github.io/en/config/routing.html)
- [Google DNS query used in the comparison](https://dns.google/resolve?name=api.telegram.org&type=A)
- Ignored token-free probe evidence: `.runtime/proxy-tls-diagnosis.json` and
  `.runtime/proxy-tls-public-ip.json`.

Browser tools invoked: `mcp__playwright_global__browser_navigate`,
`mcp__playwright_global__browser_snapshot`.

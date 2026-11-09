# Synthetic browser preflight controls

Run `tools/discovery_browser_preflight.js` as the code argument of
`mcp__playwright_global__browser_run_code_unsafe`. The function creates and
closes a fresh context and uses synthetic loopback URLs with CDP-fulfilled
responses. It has no configurable live destination. Run it only as a
synthetic regression.

The recorded run loaded the document, script and metadata, denied the
thumbnail, subtitle and media requests, and denied same-origin and
cross-origin redirect targets at Fetch interception. The synthetic document
CSP prevented child-frame navigation and popup creation. After five
fulfilled requests, the handler denied an otherwise allowed overflow
request. The context closed with a request deliberately held at interception.

The [result fixture](fixtures/browser-cdp-preflight.json) keeps Playwright
observed request events separate from CDP policy decisions. All twelve
Playwright events had a corresponding CDP decision. CDP also blocked a
favicon request absent from the Playwright event stream. The five-request
test caps admitted requests, while the attempted count includes blocked
requests.

The live pilot remains blocked. The synthetic document's CSP provides its
child-target restriction. Coverage for arbitrary YouTube child targets,
full attempted-request accounting and live transfer accounting still need
qualification. Context closure confirms cleanup of the synthetic context.
No external transfer was authorized by the harness.

Historical [PR #49](https://github.com/SoloMidMiram/CatsChannel/pull/49)
evidence remains separate. Related [#19](https://github.com/SoloMidMiram/CatsChannel/issues/19).

# Final MCP integration review — 2026-10-24

PR #34 remains a narrow compatibility/privacy correction, separate from PR #33.
The initial head `9742c4b3eb92ff79f4674022c4bd4738edd041b7` passed handshake and
inventory but final review found a real tool-call compatibility gap. Do not merge
that checkpoint as proof that actual Context7 calls work.

Actual Codex app-server `mcpServer/tool/call` requests attach both
`_meta.threadId` (36-byte UUID string) and `_meta.progressToken` (integer).
The initial guard rejects those requests with `invalid_params` / `-32602`.
Serena `find_symbol` and `find_referencing_symbols` succeed in the same session.
The [sanitized evidence](mcp-final-review-2026-10-24.json) retains that failure,
the subsequent successful calls, field shapes, result hashes and cleanup results.
No model turn was started by either manual verification session.

## Correction and privacy boundary

Tool-call metadata may now contain only a bounded, correctly typed progress token
and an optional canonical UUID-shaped thread ID. Unknown fields, malformed types,
oversized strings/numbers, private content in progress tokens and private query
arguments still fail closed. A thread ID without a progress token is rejected.
After validation the guard strips the entire tool-call `_meta` object before
forwarding; neither the thread ID nor its token is sent to Context7. The audit
contains only the original request digest and fixed decision metadata, never the
raw thread ID. Discovery behavior, normalized capability negotiation and the
base-ID allowlist are unchanged.

Negative controls and same-connection tests verify that accepted correlation
metadata cannot hide a private query or unknown field; the backend receives only
the public tool arguments, valid request IDs and newline framing. Successful
public calls continue after invalid metadata and policy rejection.

## Actual calls after the correction

- Serena `find_symbol` resolves `SubmissionIntakeService` at one-based line 42 in
  `cats_channel/intake/service.py`.
- Serena `find_referencing_symbols` returns 19 highlighted reference locations.
  Every returned highlight was independently matched to the exact source line,
  converting zero-based coordinates to one-based citations.
- Context7 `resolve-library-id` returns the permitted `/aiogram/aiogram` base ID.
- Context7 `query-docs` returns Router nesting, single-parent and cycle constraints,
  plus the Dispatcher attachment example, with four upstream aiogram source links.

The evaluator separately inspected the
[rendered primary Router source](https://docs.aiogram.dev/en/latest/_modules/aiogram/dispatcher/router.html)
using `mcp__playwright_global__browser_navigate`, confirming `include_router`,
single-parent, self-reference and cycle checks. Context7 returned dev-3.x source
links; that response does not establish exact-version retrieval. No raw repository
source or raw protocol identifiers are included in committed evidence.

Both sessions cleaned up all observed owned processes. Earlier startup timeouts
and Context7 upstream fetch failures remain in the initial report. The later
successful read-only retrieval is one observation; external availability remains
an independent limitation. None of these manual calls counts as natural selection
or evidence of adoption benefit.

## Validation and integration readiness

- Windows handshake/privacy module: 66 passed.
- Linux MCP plus context suite: 143 passed, 3 skipped.
- Ruff/format, context validation/regeneration and final-head CI are checked before
  requesting approval. Exact head and CI outcomes are recorded in the PR.
- Final human approval remains required by the owner's integration instruction;
  no GitHub approval is fabricated and no merge is inferred from green CI.

PR #33 reconciliation is rehearsed in a separate worktree. Preserve both JSONL
record sets, regenerate the conflicting overview, validate and test; after #34
actually merges, reconcile against its real merge SHA before pushing #33.
The four-session post-merge comparison is prepared separately, with identical
prompts across conditions and completion, accuracy, citations, tool selection and
time scored independently. It has not run and is not a merge requirement.

# Codex / guarded MCP compatibility — 2026-10-24

Initial checkpoint: **PASS for Codex negotiation and inventory** with
`codex-cli 0.146.0-alpha.3`; public retrieval was blocked by upstream fetch
failures. [Final review](mcp-final-review-2026-10-24.md) subsequently found and
fixed tool-call metadata rejection, then verified successful actual Serena and
Context7 calls. Earlier failures remain recorded below. Adoption benefit remains
**UNESTABLISHED**; one later retrieval does not establish ongoing availability.

The clean worktree starts at merged main
`b12b50c36e7b72812496d53998d517817a372c87`. PR #33's guidance branch is not
included or modified. No runtime code, dependencies, authentication, library-ID
allowlist, Telegram, YouTube, production database or publishing operation changed.

## Actual protocol capture and policy

[Sanitized machine-readable evidence](mcp-handshake-2026-10-24.json) contains
actual client field shapes, baseline policy decisions, inventories, prompt hashes,
source-tree hashes, cleanup results and hashes of external artifacts. Client string
values are replaced by their UTF-8 lengths. Query arguments and server response
bodies are absent from transport captures and committed evidence.

The actual Codex initialize capabilities are
`{"elicitation":{"form":{},"url":{}}}`. Its discovery parameters are
`{"_meta":{"progressToken":<integer>}}`. Evaluating these incoming requests
against the guard from `b12b50c` reproduces `invalid_protocol_params` for both.
The updated guard accepts both; it validates before normalization and forwards
initialize with `capabilities: {}`. Thus Context7 is never told that roots,
sampling or elicitation are available through this transport. All backend-initiated
requests are answered locally with `-32601`; backend notifications are suppressed.

Only the known empty `form`/`url` objects are accepted inside elicitation. Discovery
metadata must contain exactly one `progressToken`: a nonempty string of at most
128 UTF-8 bytes or a finite number with absolute value at most `2**53 - 1`.
Booleans are rejected. Existing privacy scanning and the 800-byte protocol/public
query limit still apply, as does the 64 KiB frame limit. Unknown metadata,
envelope fields, tool fields and arguments are rejected rather than forwarded.
The base-ID allowlist is unchanged.

Regression coverage includes malformed capabilities, unknown metadata, token type
and size boundaries, nonfinite numbers, synthetic private canaries, unsupported
methods, unchanged version-ID denial, integer/string IDs, complete newline
framing, oversized-frame recovery, and successful subsequent discovery/public
calls on the same connection. Interactive backend tests verify local rejection of
elicitation, roots and sampling requests. Output and backend writes are serialized
so concurrent replies cannot corrupt framing. The existing closed-backend test
now waits for actual child exit instead of relying on a 300 ms scheduling race.

## Inventory gate before neutral sessions

An actual Codex app-server session called `initialize`, `thread/start` and
`mcpServerStatus/list` without calling `turn/start`. Both required servers
completed initialize, initialized notification and tool discovery:

| Server | Advertised tools |
| --- | --- |
| Serena | `find_declaration`, `find_implementations`, `find_referencing_symbols`, `find_symbol`, `get_symbols_overview` |
| Context7 | `resolve-library-id`, `query-docs` |

No model turn was started by this gate. An initial exploratory inventory also
exposed inherited Codex app tools; it is retained separately and excluded from
the isolated inventory. The successful gate disabled unrelated apps. The server
settings use `required=true`, explicit enabled-tool lists and bounded timeouts,
as described in the [official Codex MCP documentation](https://learn.chatgpt.com/docs/extend/mcp?surface=cli).
Neither elicitation feature flag was disabled.

## Unchanged neutral prompts in fresh sessions

Only after the isolated inventory passed, each previously approved prompt ran in
a fresh ephemeral, read-only Codex process with independent server state. No
selection guidance from PR #33 was added. Prompts were copied from the prior
approved artifact files; their hashes are in the JSON evidence. Each process had
a 240-second observation limit. The initial repository harness attempt stopped
before Codex launch because Windows' worktree reference was not WSL-compatible;
only the new worktree's reference was made relative before running the session.

| Observation | Repository review | Documentation question |
| --- | --- | --- |
| Handshake / inventory | Success, both servers | Success, both servers |
| Model turns reached | One started and completed | One started, not completed |
| Actual Serena selections | 0 | 0 |
| Actual Context7 selections | 0 | 0 |
| Successful MCP tool calls / MCP evidence used | 0 / none | 0 / none |
| Evidence actually used | Local shell reads with source-line citations | Web searches / page opens; no completed answer |
| Outcome | Exit 0, completed | Observation timeout, terminated with SIGTERM |
| Guard / policy failures | None | None |
| Tracked source content unchanged | Yes | Yes |
| Observed owned processes remaining | None | None |

The repository answer cites the intake composition root, post router, intake,
submission and reply-chain services, flow ownership, persistence models and UoW.
Raw local-source output and the incomplete documentation search transcript remain
outside Git. Source hashes before/after agree. The guard hash in both session
snapshots equals the initial-checkpoint implementation hash in the JSON; these runs occurred before
committing the reviewed patch, while HEAD still identified the baseline.

These two observations establish that the model ran after successful startup.
They do not establish performance benefit, a stable tool preference, successful
documentation retrieval, or exact-version coverage. Earlier PR #33 startup
failures remain startup failures and are not reclassified as nonselection.

## Separate public-query diagnostic

The first health check timed out after 60 seconds waiting for initialization;
the audit recorded the initialize request as allowed. No successful call or
retrieval is inferred from that failure. A single bounded diagnostic retry with
transport capture completed initialize and tools/list, then received Context7
upstream `fetch failed` errors for resolve, query and query-after-policy-denial.
The version-qualified ID was rejected with `-32001`, and the next public query
received an upstream tool-error response on the same connection. Transport
recovery succeeded; documentation retrieval did not. No source URL or useful
documentation evidence was returned. The retry exited 0 at the process level
while the health verdict correctly remained false. Both attempts are retained.

## Validation and cleanup

- Full offline Linux suite: 625 passed, 64 skipped before the final two
  server-request parameter cases were added; final-head CI is recorded on the PR.
- Linux MCP suite: 107 passed, 3 skipped at that checkpoint.
- Windows MCP suite: 97 passed, 12 skipped, 1 deselected; the deselected existing
  resolver-symlink test requires a local privilege. The first unrestricted attempt
  failed that privilege check and exposed the closed-backend timing race. After
  making the race test deterministic, the supported local cases passed.
- Final new handshake test module: 55 passed on Windows.
- Final Linux MCP plus context suite: 132 passed, 3 skipped.
- Ruff checks/format and whitespace pass. Context validation and generated-file
  checks are run before commit; final checks and CI are reported on the PR.

All observed owned Codex/server processes were identified by PID plus process
start time, terminated/reaped as necessary and checked absent. A separate process
inspection after both public-query diagnostics found no surviving command for
this worktree or its Context7/Serena launchers. Existing processes were not killed.
The dirty original checkout and PR #33 remain independent. Raw evidence and
runtime state are retained externally under the sibling `mcp-handshake-evidence`
directory; no credential or user configuration was copied or changed.

The subsequent final-review correction and its new implementation hash are
recorded separately in `mcp-final-review-2026-10-24.json`; do not attribute the
historical neutral sessions to that later implementation.

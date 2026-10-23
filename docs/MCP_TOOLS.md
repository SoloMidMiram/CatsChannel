# Optional MCP developer tools

These helpers make two MCP servers available for explicit development sessions:
Context7 for generic public documentation and Serena for read-only semantic source
navigation. They are not CatsChannel dependencies, are not loaded by the bot, and
do not start after cloning the repository.

The tested isolation path is Linux/WSL with `bubblewrap` (`bwrap`). Native Windows
can run the offline tests but has no claimed equivalent sandbox; invoke the tools
inside WSL instead. Missing prerequisites and version mismatches fail closed.

## Boundaries

- Context7 receives no source mount. Its environment is cleared, its anonymous
  public queries pass through `guard.py`, and only base IDs for aiogram and
  SQLAlchemy are accepted. The server needs network access. If the system resolver
  is a symlink outside `/etc` (as on WSL), only that resolver target is added to the
  sandbox.
- Serena receives project entries under `/workspace` as individual read-only
  mounts, while `/workspace/.serena` is backed by ignored
  `.runtime/mcp/serena-project/`. It runs with network and memories disabled;
  cache/index state uses the separate bounded state home. Codex exposes only the
  five tools in the example config.
- Serena's external uv environment and every managed-Python alias root needed by
  its interpreter symlink chain are mounted read-only. They remain outside the bot
  environment and checkout.
- Package trees and indexes stay outside the checkout. Small runtime metadata and
  digest-only audit records go under ignored `.runtime/mcp/`.
- No helper copies Codex authentication, accepts an API key, prints an environment
  dump, or edits the user's Codex configuration.

Filtering is defense in depth, not proof that every encoding of private material
can be recognized. Send only generic public-library questions to Context7.
The guard rejects unsupported methods. It permits typed initialization,
initialized/cancelled notifications, ping, and paginated tool/resource/prompt
discovery only; negotiation extensions with arbitrary payloads are not forwarded.

## External installation

Use an explicit cache location outside this checkout. The following is an example;
review it before running it and adapt paths to the machine:

```bash
MCP_TOOL_ROOT="${XDG_CACHE_HOME:-$HOME/.cache}/cats-channel/mcp"
mkdir -p "$MCP_TOOL_ROOT/context7" "$MCP_TOOL_ROOT/uv-tools" "$MCP_TOOL_ROOT/bin"

npm install --prefix "$MCP_TOOL_ROOT/context7" --ignore-scripts \
  @upstash/context7-mcp@4.4.4

UV_TOOL_DIR="$MCP_TOOL_ROOT/uv-tools" \
UV_TOOL_BIN_DIR="$MCP_TOOL_ROOT/bin" \
uv tool install --python 3.13 'serena-agent==2.1.0'
```

The top-level server versions are pinned in `tools/mcp/versions.json`. This is
reproducibility metadata, not a transitive lock. Serena's separate Python 3.13 tool
environment does not change CatsChannel's Python 3.11 policy or `uv.lock`.

The launcher expects Context7's package root (the directory containing
`node_modules`) and Serena's specific uv tool environment, normally
`$MCP_TOOL_ROOT/uv-tools/serena-agent`. It verifies package metadata before launch.

## Explicit Codex activation

Copy only the desired sections from `tools/mcp/codex.example.toml` into the Codex
configuration described by the current Codex MCP documentation. Replace every
`/ABSOLUTE/...` placeholder. The example is inert and deliberately contains no
personal path or credential.

The launch commands may also be exercised directly:

```bash
python tools/mcp/launch.py context7 \
  --package-root "$MCP_TOOL_ROOT/context7"

python tools/mcp/launch.py serena \
  --tool-environment "$MCP_TOOL_ROOT/uv-tools/serena-agent" \
  --project-root "$PWD"
```

Stdio is the MCP transport. Closing stdin is the ordinary shutdown path. The
launcher supervises a dedicated child process group and reaps it after EOF,
SIGINT, SIGTERM, or a bounded forced shutdown. Bubblewrap reports the actual
sandbox child PID through its private info descriptor; termination targets that
server session before falling back to the wrapper. The launcher does not use
bubblewrap's `--die-with-parent` because that tied server lifetime to a transient
spawning thread in the experiment.

## Manual Context7 health check

This is opt-in and makes real network calls. Ordinary pytest and CI do not:

```bash
python tools/mcp/check.py \
  --verify-policy-recovery \
  --output .runtime/mcp/context7-health.json \
  -- python tools/mcp/launch.py context7 \
  --package-root "$MCP_TOOL_ROOT/context7"
```

The check initializes the connection, verifies the tool inventory, resolves
aiogram, idles, retrieves actual documentation, confirms that a version-qualified
ID is promptly rejected by local policy, and confirms a valid query still works on
the same connection. Initialization and inventory protocol rows participate in the
final verdict alongside retrieval rows. Each call has its own status. A clean
process exit cannot hide a protocol or tool failure, and successful retrieval
requires the negotiated protocol version, server information and tools capability,
the expected `/aiogram/aiogram` resolution, and documentation carrying a matching
official aiogram or aiogram-repository source reference. Arbitrary nonempty text
and unrelated URLs fail. Source references are validated structurally; the check
does not independently fetch those pages or establish exact-version coverage.

The latest real Serena semantic acceptance check reached the packaged server but
failed Python language-server initialization: the sandbox PATH did not contain
`uv`/`uvx`. Host installation alone does not satisfy that sandbox prerequisite.
Keep semantic readiness unconfirmed until the prerequisite is supplied and a real
symbol call succeeds; initialization or an advertised tool list is insufficient.

## Offline validation

```bash
uv run --frozen pytest -q tests/test_mcp_tools.py
uv run --frozen ruff check tools/mcp tests/test_mcp_tools.py
uv run --frozen ruff format --check tools/mcp tests/test_mcp_tools.py
git diff --check
```

On WSL mounted drives, set `TMPDIR=/tmp` if pytest's capture temporary file is
removed by host-side temp cleanup before collection.

## Removal

Remove the selected `mcp_servers.cats_context7` and/or
`mcp_servers.cats_serena` sections from the user's Codex configuration. After no
client is using them, remove the external package/cache directories and the local
`.runtime/mcp/` directory. No bot package, database migration, application hook, or
tracked index needs rollback.

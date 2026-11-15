# Project context guidance

Start with `project-context/overview.md`. For focused history, run:

```bash
uv run --frozen python tools/project_context.py select "<question>"
```

Treat memory as a recall layer, not proof of current state. For status or readiness
questions, verify selected records against their source plus current code, tests,
Git history, or GitHub state.

Record material facts, decisions, proposals, blockers, and tasks in
`project-context/records.jsonl`; catalog new evidence in `sources.jsonl`. Preserve
`source`, `status`, and `freshness`, and never record secrets or raw credentials.
Do not edit generated briefs or decision pages directly. After record changes run:

```bash
uv run --frozen python tools/project_context.py validate
uv run --frozen python tools/project_context.py generate
```

## Coding tool selection

For non-trivial coding tasks, select tools according to the evidence needed.

### Serena: local repository intelligence

Prefer the `cats_serena` MCP server when investigating existing implementations,
references and callers across modules, component dependencies, ownership of state
changes, transactions or cancellations, architectural refactoring or behavior
tracing. Use `find_symbol`, `find_referencing_symbols`, `find_declaration`,
`find_implementations` or `get_symbols_overview` as appropriate. Prefer semantic
navigation over repeated broad text searches when symbol identity matters.

Verify returned references against actual source. Normalize Serena's zero-based
line coordinates to one-based source citations. Do not force Serena for simple
single-file changes. See `docs/MCP_TOOLS.md` for explicit setup; configuration alone
does not prove a server or semantic call works.

### Context7: external library intelligence

Prefer `cats_context7` when an API/framework signature is uncertain, implementing
unfamiliar aiogram or SQLAlchemy functionality, evaluating external library
patterns/compatibility or checking documentation against assumptions. Use
`resolve-library-id` followed by `query-docs`, unless a permitted library ID is
already known.

Only send generic public-library documentation questions. Never send repository
source, private filenames, internal identifiers, credentials or application data.
The current guard permits base library IDs only. Do not imply version-specific
documentation was verified unless independent evidence establishes that.

### Verification and reporting

At completion, report which MCP tools actually succeeded, what they returned that
materially influenced the answer, verified source symbols or documentation links,
any transport/policy/tool failures, and available tools left unused when relevant.
Never claim MCP usage merely because a server was configured. Use ordinary shell
inspection and tests when they provide stronger or simpler verification. Do not
make MCP calls solely to increase tool-use counts.

## Source integration

Follow the [solo-maintainer review policy](docs/MAINTAINER_REVIEW_POLICY.md).
Collect technical review and applicable verification for the integration
candidate, then present a recommendation to SoloMidMiram. The owner records
acceptance and authorizes the source merge. Check the policy for separate
operational authorization and qualification requirements.

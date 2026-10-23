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

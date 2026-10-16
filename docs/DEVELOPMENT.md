# Development Workflow

Install:

```bash
uv sync --locked
```

Validate:

```bash
uv run --frozen pytest
uv run --frozen ruff check .
uv run --frozen ruff format --check .
```

Before production:

- refresh and review uv.lock through the upgrade workflow in QUICKSTART.md
- configure secrets
- add deployment workflow

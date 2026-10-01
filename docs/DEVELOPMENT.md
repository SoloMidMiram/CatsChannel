# Development Workflow

Install:

```bash
uv sync
```

Validate:

```bash
uv run pytest
uv run ruff check .
```

Before production:

- generate real uv.lock
- configure secrets
- add deployment workflow

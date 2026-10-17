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

Persistence work uses the optional async database dependencies:

```bash
uv sync --locked --extra persistence
uv run --locked --extra persistence alembic upgrade head
```

Use `Database.create_schema_for_tests()` only in isolated contract tests. Runtime
schemas are advanced through Alembic. See DATABASE.md for transaction ownership
and identity invariants.

Before production:

- refresh and review uv.lock through the upgrade workflow in QUICKSTART.md
- configure secrets
- add deployment workflow

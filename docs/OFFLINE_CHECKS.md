# Repeatable offline checks

These tools are developer checks, not a bot supervisor or a delivery-retry policy.
They make no live Telegram, YouTube or GitHub requests. Use the current locked
Python 3.11 environment and run them from the repository root.

```bash
uv run --frozen python tools/regress.py run --profile context --repeat 3
uv run --frozen python tools/regress.py run --profile lifecycle --repeat 3
uv run --frozen python tools/regress.py run --profile all --repeat 1 --timeout 180
```

`context` checks the context data, generated output and offline-tool regressions.
`lifecycle` checks transport, startup/shutdown, intake, publication and Telethon
cleanup contracts with fakes and local loopback sockets. `all` runs the complete
pytest suite; opt-in PostgreSQL tests still need the existing disposable-service
configuration. These profiles introduce no live service configuration or retries.

Repetitions are explicit independent checks, bounded to 1–10, with a per-run
timeout of 5–600 seconds. Every run retains its exit category, code, duration and
stdout/stderr under a unique ignored `.runtime/regress/<run-id>/` directory. A
failed run keeps the aggregate result failed even if later runs pass. Timeout
or interruption terminates the owned test process tree and reaps its parent;
unconfirmed cleanup stops further repetitions and fails the report. Cancellation
is reported with CLI exit 130; other failures return 1, successful checks return 0.
No pytest process is restarted as an automatic response to a failure.

Reports are checkpointed after each invocation using a same-directory atomic
replace. An unfinished report remains `running` rather than implying success.
Raw test output can contain local details or synthetic secret sentinels: keep it
local and ignored. Only sanitized summaries belong in shared evidence.

## Audit structured logs

Supply an already sanitized CatsChannel JSONL diagnostic file explicitly. The
tool never searches runtime folders, opens a session/database or consumes updates.

```bash
uv run --frozen python tools/regress.py logs .runtime/sanitized-events.jsonl
uv run --frozen python tools/regress.py run --profile lifecycle --repeat 2 \
  --log .runtime/sanitized-events.jsonl
```

The auditor checks correlated bot failures/completions in either log order,
success logged after failure, mismatched categories, duplicate completions,
intake/publication outcome fields, and polling phase/consecutive counters. It also
recognizes startup/lifecycle/CLI failure phases. Service-level publication events
and unrelated library messages are not paired as bot completions. Plain-text
lines, malformed JSON, empty/unsupported input, and known private payload fields
fail the audit. Input is bounded to 20 MiB total and 256 KiB per line. Reports
contain fixed categories and line numbers, never log values or exception text.

For a deliberately truncated log window, `--allow-incomplete` allows a failure
without its completion. It does not excuse duplicates, category/outcome mismatch,
malformed data or private fields. A passing audit means the supported diagnostic
contracts agree; `error_events` can still be nonzero. It does not prove application
health, verified media identity, successful delivery, production readiness, or
that every possible secret pattern was detected.

## Context module boundaries

- `tools/context_store.py`: loading, local evidence and record validation.
- `tools/context_render.py`: generated documents and per-file atomic replacement.
- `tools/context_select.py`: bounded retrieval and source-preserving formatting.
- `tools/project_context.py`: compatible CLI and import facade.
- `tools/log_checks.py`: read-only JSONL diagnostic checks.
- `tools/regress.py`: bounded process ownership, repeated checks and reports.

Both `python tools/project_context.py ...` and `python -m tools.project_context ...`
remain supported. Generation is atomic per file; it is not a transaction over all
generated files. If generation stops partway, `generate --check` exposes the stale
set before review. Expected I/O/data errors return nonzero without raw exception
bodies; programming errors retain their traceback instead of being silently caught.

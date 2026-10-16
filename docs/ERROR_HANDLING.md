# Error handling and structured logging

CatsChannel uses deterministic ordered regular expressions rather than statistical
regression or an ML model. Error strings and exception types are a small evolving
protocol surface; operators need stable, auditable decisions and must be able to
explain why one retry policy was selected.

## Classification algorithm

`cats_channel/diagnostics.py` provides the shared mechanics:

1. Walk `__cause__` or `__context__` iteratively, stopping at eight exceptions,
   repeated objects, or the end of the chain.
2. Keep exception class names only. Never copy exception messages into analysis.
3. Evaluate regex rules in declared order. Earlier rules have higher priority.
4. Return the first match as `primary`, while retaining every matched stable code
   in `signals` for diagnosis.
5. Use a low-confidence explicit fallback when no rule matches.
6. Let `ERROR_POLICIES` map the stable code to a safe message, operator action and
   retry policy.

The yt-dlp adapter applies the same ordered-rule model to subprocess stderr. It
keeps only counts, allowlisted status/exception names and a hash of a redacted
terminal line. The Telethon adapter classifies the bounded exception-type chain.
Neither path returns or logs raw third-party text.

`TelethonConnectionMiddleware` additionally labels operations by phase:
`connection`, `authorization`, `login`, `account`, `bot_resolution`, `request`,
`response`, `transfer`, `conversation`, and `disconnect`. It owns exactly one
connection lifecycle, records connection/operation attempts, performs zero
automatic retries, and waits for disconnect cleanup without replacing the primary
failure. Nested exceptions are classified from the complete bounded type chain.

## Try/except boundaries

- Adapters catch expected failures where transport-specific meaning is available
  and raise `MediaError` with a stable code and safe analysis.
- Services preserve cancellation and cleanup semantics; they do not convert every
  failure into success or automatically retry it.
- CLI and bot entry points are the final containment boundaries. They render safe
  user output and emit one structured failure event.
- Cleanup warnings are attached to the original error. A cleanup or logging error
  must not replace the primary operational failure.

Automatic retries remain disabled for login, authentication, flood-wait, proxy,
rate-limit and ambiguous Telegram publication failures. “Iterative” means walking
the evidence and evaluating rules; it does not mean repeatedly contacting an
external service.

## Logger contract

`configure_logging()` installs one idempotent CatsChannel handler. `log_failure()`
writes one JSON object to stderr. CLI result JSON remains on stdout. Set the minimum
level with:

```dotenv
LOG_LEVEL=WARNING
```

Logged fields are allowlisted: timestamp, event, operation, stable code, safe
analysis tokens, and cleanup warning codes. Raw exception messages, tracebacks,
URLs, proxy credentials, cookies, API hashes, bot tokens, phone numbers, login
codes and arbitrary analysis keys are excluded. If the logging destination itself
fails, the logger returns without altering the original operation result.

## Adding or changing a rule

1. Capture the exception class or aggressively redacted diagnostic fixture. Never
   commit a raw production log.
2. Add a regression covering the stable code, priority, all expected signals and
   `raw_log_included=false`.
3. Add the narrowest case-insensitive regex to the relevant ordered rule table.
4. Test a nearby non-match so a generic word does not over-classify errors.
5. Update `ERROR_POLICIES` and operator documentation when introducing a new code.
6. Run the full offline suite and lint/format checks before a single live attempt.

Unknown errors intentionally retain a safe low-confidence fallback and exception
class list. Add a new rule only from evidence; do not guess or create a retry loop.

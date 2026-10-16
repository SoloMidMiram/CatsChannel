# Foundation review and first branch plan

Reviewed 2026-10-16 against the current Windows checkout. This is a review and
proposed implementation scope; application code was not changed by this review.

> **Resolution note (2026-10-16):** This document preserves the findings and
> validation state from the original review. The implementation and follow-up
> process-lifecycle findings have since been resolved with regression coverage.
> Current offline readiness is recorded in `ROADMAP_STATUS.md`; authorized live
> YouTube and private-channel Telegram smoke tests remain separate.

## Decision

The downloader is a useful integration spike with unusually good attention to
cookie isolation, safe diagnostics and validated local publication. It is not yet
a consistent application service: the CLI and Telegram bot have different download
guarantees. Make the first feature branch a tested media foundation, then build
submissions, moderation and reply chains on that foundation.

Suggested branch name: `feat/media-foundation`. This review did not create a
branch, stage files, commit, or contact Telegram/YouTube.

## Findings

### 1. High: the bot bypasses persistent validation

`cats_channel/bot.py:54-59` calls `media.download()` into a temporary directory and
uploads the result. Only `library.store_download()` checks the metadata ID, runs
FFprobe, performs a full FFmpeg decode and records a manifest. A successful bot
download therefore has weaker guarantees than the same CLI operation.

Have both entry points call one `MediaService.acquire()` operation. Return a typed
validated library item and let the Telegram adapter upload that item's path.
Keep explicit publishing separate from acquisition. If ephemeral storage is later
required, make retention a policy, not a separate validation implementation.

Acceptance: a failed decode prevents a Telegram upload and leaves no library item;
a repeated valid acquisition uses the same stored file without contacting YouTube.

### 2. High: cancellation does not stop the downloader thread

`bot.py:55` awaits `asyncio.to_thread(download, ...)` inside `TemporaryDirectory`.
Cancelling that await does not stop the running thread. The context can remove its
directory while the worker continues. The lock can also be released before the
underlying operation actually ends. `subprocess.run()` supplies a deadline for its
direct child, but the application does not own termination of child processes
such as a merge process as a group.

Introduce an owned process runner with timeout/cancellation termination, bounded
graceful shutdown, forced termination when necessary, and a wait/reap step before
staging cleanup. Specify Windows and Linux behavior independently. Keep the
concurrency permit until work actually stops. For the initial single-user branch,
an application-owned single worker is sufficient; a distributed queue is unnecessary.

Acceptance: cancel during transfer and merge; no worker continues writing after
cleanup, no child survives, and the next operation is admitted only after shutdown.
This finding is from control-flow review, not a live cancellation reproduction.

### 3. Medium: corrupt cached files are accepted as completed downloads

`library.py:180-186` returns `existing` after `_read_manifest()` checks structure and
file existence. It does not compare current file size/hash with the recorded values.

Reproduced offline: create a mocked valid item, change its media bytes, call
`store_download()` again. The result remains `existing`.

Before reuse, validate the manifest and verify size and SHA-256. A matching hash
allows reuse of the stored decode record without decoding on every cache hit.
Report `cache_corrupt` for a mismatch. Offer explicit quarantine/redownload rather
than silently overwriting a completed directory. Check manifest source/video ID
against the requested ID as well.

### 4. Medium: valid JSON of the wrong shape escapes the error boundary

`media.py:709-713` parses JSON then calls `info.get()` without checking for an object.
Reproduced with mocked successful yt-dlp output `[]`: `probe()` raises
`AttributeError`, which normal CLI probe and bot handlers do not translate.

Parse external metadata into a validated model. Check object shape, video ID,
finite positive duration when required, live status and relevant field types.
Convert schema failures to `metadata_invalid`; do not repair this by swallowing
every exception around the entire application.

### 5. Medium: NaN duration can pass playback validation

`library.py:110-123` accepts `float('nan')`; both the positivity check and duration
difference comparison fail to reject it. An offline mocked FFprobe response with
duration `nan` and successful decoder exit produced `status=passed` and a NaN
duration. Python JSON serialization can then emit nonstandard `NaN`.

Require finite numeric durations for both expected and measured values, enforce
the configured maximum on actual output, and serialize manifests with
`allow_nan=False`. Validate stream dimensions/types and the selected output policy
at this same boundary. Silent videos may be legitimate; make audio requirements
an explicit policy rather than assuming every file needs an audio stream.

### 6. Medium: the cookie test assumes Linux newline conversion

`tests/test_example.py:198-209` writes a text fixture using platform-default newline
translation and always expects LF. On Windows the detector correctly reports CRLF.

Use byte fixtures for LF, CRLF and mixed-newline cases. If Windows remains a
supported workflow, include a Windows test job. Keep independent Windows and WSL
venvs. This is a test portability failure, not evidence that the cookie detector
misclassifies the file.

### 7. Medium: error output and codes are not a complete public contract

`__main__.py:63-64` prints raw exception strings for ValueError/OSError, whereas
MediaError and diagnose failures use structured, safe records. New error codes
such as `media_validation`, `download_output` and `upload_limit` have no dedicated
action/retry mapping. Errors can therefore fall back to irrelevant extractor advice.

Define one error-code registry with safe message, category and recovery policy.
Render the same JSON error envelope for every non-interactive command. Translate
exceptions where their meaning is known, and have one final CLI/Telegram boundary
for unexpected failures. Never expose arbitrary exception messages or process
arguments; log only allowlisted context and an operation ID.

### 8. Medium: publication races and cleanup need explicit behavior

`library.py:228-229` handles FileExistsError only. On Linux, renaming onto an
existing nonempty directory can instead raise OSError with ENOTEMPTY. Both
processes can also perform an expensive download before this race is resolved.
`rmtree(ignore_errors=True)` hides cleanup failures, so an operation cannot promise
that staging was removed merely because it returned.

Serialize acquisition per video ID, recheck the destination after taking the lock,
and handle the documented destination-exists error cases without treating every
OSError as a successful race. Verify the winning item. Report cleanup failures as
safe warnings without replacing the original operational failure. Define stale
lock and stale staging inspection; do not recursively delete unknown paths.

This finding is from code review. A real multi-process WSL race was not reproduced.

## Proposed module boundaries

Keep the current package location initially; moving everything under `src/` at the
same time would add packaging churn without fixing the main defects.

```text
cats_channel/
  __main__.py              # tiny entry point
  cli.py                   # argument parsing and output rendering
  config.py                # Settings and validated configuration
  models.py                # VideoMetadata, MediaPolicy, LibraryItem, Manifest
  errors.py                # stable error codes and recovery policies
  services/
    media_service.py       # acquisition, cache checks, validation, publication
  adapters/
    youtube.py             # canonical URLs, format/profile arguments, extraction
    process.py             # process execution, deadlines and cancellation
    cookies.py             # immutable source / disposable working copy
    validation.py          # FFprobe and FFmpeg validation
    library.py             # local manifest/file storage and atomic publication
  diagnostics/
    classifier.py          # pure regex classification and safe fingerprints
    runtime.py             # offline capabilities and configuration checks
  telegram/
    app.py                 # lifecycle, dependency wiring, admin/private filters
    handlers.py            # thin translation to service calls
    publishing.py          # explicit Telegram send/copy operations
```

Extract coherent responsibilities as they become useful. Avoid empty base classes,
one-function wrapper modules and speculative abstractions. A small downloader
interface is enough to inject a fake into service tests. Persistence adapters can
be added when a real database use case exists.

Replace `metadata_out` mutation with a returned DownloadArtifact. Use typed
manifests at the storage boundary and JSON only for serialization. Retain current
CLI flags, stable error codes and the existing library layout. Preserve temporary
import facades if needed so module moves do not obscure behavior changes.

## Fallback policy

| Failure | First branch behavior |
| --- | --- |
| TLS, proxy, DNS, connection | Stop; retain the configured route and await a network change |
| Timeout or interrupted transfer | Clean up only after process shutdown; permit an explicit later retry |
| HTTP 429 | Stop and return cooldown guidance |
| Login/cookie requirement | Return an authentication action; do not refresh cookies automatically |
| PO-token requirement | Offer the explicitly selected provider profile; no silent profile switching |
| No suitable format | Return format policy failure; a later explicit lower-quality policy can be added |
| Final file over limit | Reject; preserve policy rather than repeatedly redownloading/transcoding |
| Invalid metadata, decode or hash | Do not publish or upload; preserve a precise failure code |
| Existing corrupt library item | Report/quarantine explicitly; do not claim a cache hit |
| Telegram ambiguous send/copy failure | Do not blindly resend; the remote side may already have accepted it |
| Cleanup failure | Preserve original failure and emit a safe cleanup warning |
| Unexpected programming failure | Contain at the entry-point boundary, return internal_error and nonzero exit |

Keep diagnosis at one extractor attempt with zero automatic retries. Ordinary
downloads can gain a separate bounded retry policy later, after transient-failure
rules and operation accounting are tested. The first branch does not need a
generic fallback chain or alternate download engine.

The successful explicit SOCKS route is user-reported evidence from the prior live
test, not a network test repeated in this review. Add a validated, secret-safe
project proxy setting so it is reproducible for both CLI and bot. Child processes
should receive explicit proxy configuration without changing global environment
state. Preserve supported ambient proxy settings for compatibility and document
precedence. Do not silently fall back to a direct connection when the proxy fails.

## First branch implementation order

1. Add regression tests for wrong-shaped metadata, non-finite durations, corrupt
   cache reuse, Windows newlines, failed-validation cleanup and publication races.
2. Fix those behaviors in the existing modules, preserving CLI and manifest schema
   compatibility. Define how older manifests are verified/migrated; do not silently
   bless unvalidated older entries or require network access for a migration.
3. Extract error registry, metadata models, classifier, cookie handling and media
   validation in small moves. Keep expected output contracts covered throughout.
4. Introduce the shared acquisition service. Route CLI and bot through it, and add
   mocked Telegram adapter tests for authorization, validation failures, uploads,
   publish failures and cancellation. No real tokens are required for those tests.
5. Add explicit proxy configuration and process lifecycle ownership. Test timeout,
   cancellation, cleanup and shutdown using controlled local child processes.
6. Refresh ARCHITECTURE.md, ROADMAP_STATUS.md and the documentation index to match
   actual code. Consolidate bootstrap markers/checklists into historical notes;
   do not let multiple documents imply conflicting completion status.

Suggested internal commits: regression fixes; data/error contracts; module moves;
shared service and Telegram adapter; process/proxy lifecycle; CI/docs. These are
review units within one feature branch, not a demand for separate infrastructure.

## Branch acceptance gate

- Locked install/build works from a clean environment with baseline dependencies.
- Offline tests pass under Python 3.11 and 3.13; Windows checks cover supported use.
- Both baseline and optional PO-token dependency configurations have clear coverage.
- CLI and bot acquire through the same validation/cache service.
- Corrupt, partial, invalid or interrupted media never becomes a successful item.
- Cancellation terminates owned work before cleanup and lock release.
- Successful cache hits require no YouTube request and validate local integrity.
- Cookie-source immutability and secret-safe outputs remain covered by tests.
- Current flags, error codes and documented manifest compatibility are preserved.
- One controlled live smoke test uses the known explicit proxy and permitted media;
  publishing is separately checked in a private test channel when authorized.

Exclude from this branch: Telethon activation, new downloader engines, recommendation
systems, moderation/reply-chain implementation, databases/Redis and production
Docker deployment. The branch should establish a dependable media foundation.

## Validation performed during this review

- Windows `.venv` Python: 3.11.4.
- Offline pytest rerun outside the sandbox with workspace-local test data:
  **47 passed, 1 failed**; the remaining failure is the LF/CRLF fixture assumption.
- Three initial rename PermissionErrors disappeared outside the sandbox; they were
  not counted as reproduced project defects.
- Ruff lint passed; Ruff format check passed (42 files).
- Mocked reproductions confirmed wrong-shaped probe JSON, corrupt cache reuse,
  and non-finite duration acceptance.
- No actual cookies or `.env` contents were read, and no media was downloaded.
- WSL/Python 3.13, cancellation, concurrency and live services were not verified.
- Existing changes are extensive and unstaged on `main`; the review adds only this
  document. Review the intended staging list before creating the first commit.

Historical readiness at the time of this review: **BLOCKED for the proposed
media-foundation completion gate**, pending the findings above. Creating a
work-in-progress feature branch was still reasonable; branch creation and merge
readiness were separate decisions. See the resolution note at the top for the
current status.

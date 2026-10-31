# Reply-entry admission correction

Parent: `928f24aff183db39da7847bc0a51e0921adbe025` (PR #36, still open).
The separate PR targets that branch so its diff excludes the existing review
feature. Do not merge or deploy automatically.

## Reproduced failure

`test_video_during_reply_resolution_is_processed_once` failed on the parent:
`Expected process to have been awaited once. Awaited 0 times.` The real
`Dispatcher.feed_update()` started `/start catreply_<opaque token>`, suspended the
resolver, delivered one video, then released resolution. No second delivery,
xfail, live transport, or routing bypass was used. The repository implements reply
links through `/start`; it does not implement a literal `/reply` command.

## Correction

An authorized entry reserves a future on its flow generation before target lookup.
Resolution has a 30-second deadline. Video arrival captures its generation before
asynchronous routing filters, and the authenticated video route admits at most one
video for that transition. A pending video waits at most 30 seconds outside the
transition lock. Successful entry selection releases the resolved context;
failure, cancellation or replacement releases a rejection. Admission rechecks the
captured generation before using the original exact parent. Existing flow lease,
provider checks and durable commit guard remain the intake authority.

A second regression initially exposed late generation capture after asynchronous
filters: replacement with `/post` admitted an old video. Capturing at outer video
arrival corrected that interleaving. This failed run is retained as part of the
development evidence, not overwritten by the subsequent passing suite.

The pending future and media claim are process-local and released with transition
ownership. They contain no durable acceptance. Restart before intake commit can
lose the deferred update; no exactly-once restart claim is made. Existing durable
intake replay applies only once persistence has committed. Rejected videos receive
an explicit response; operation outcomes use `deferred`/`rejected` or existing
pending/error categories without logging tokens, file IDs or message contents.

## Validation and limits

- Parent regression: 1 failed as expected.
- Affected intake, persistence, approval and publication suites: 62 passed,
  41 skipped before the final deadline/isolation test additions.
- Windows full suite: 651 passed, 91 skipped, 1 existing symlink privilege failure
  (`WinError 1314`). A validation attempt also failed because the temporary-root
  parent was absent; that setup error was corrected rather than hidden.
- Sandbox test attempts produced no output and were interrupted; runnable tests
  required execution outside the sandbox.
- WSL full suite: 663 passed, 81 skipped. Three separate concurrency runs each
  passed all 10 tests (3.88s, 3.74s, 3.52s); every run's output and exit code is
  retained in ignored `.runtime/entry-repeat/`. No local PostgreSQL service or
  live Telegram was used. Exact-head hosted CI remains a separate gate.

The new tests cover original delivery once, cancellation after deferral,
replacement by `/post` and a new reply link, rejected/failed resolution, actual
deadline expiry, concurrent duplicate and replay, and unauthorized actor isolation.
Existing intake tests retain cancellation during provider lookup, handoff and
commit, plus durable replay. Multi-user admission remains subject to the unchanged
admin-only policy. No public-deployment, retry, supervision or moderation-policy
expansion is included.

# Next phase: authenticated bot submission intake

## Reconciled baseline

- Main: `a6a0c8574239121006342d37f3b6e9fbe68d0ff7`.
- PR #23 merged at `c9f2b20`; issue #3 is closed.
- PR #24 merged at `2f6f370`; issue #6 is closed and the durable reply graph is
  implemented.
- Documentation/contract PR #25 merged at `a6a0c85`; merge CI run 39085655919
  passed Ubuntu Python 3.11, Windows Python 3.11, and disposable PostgreSQL.
- Issue #5 remains open specifically for authenticated bot intake and durable
  intent integration. Issue #7 follows it with external delivery state.

A clean implementation worktree was created at
`/mnt/f/Git/CatsCh/CatsChannel-bot-intake` on branch
`feat/bot-submission-intake`, tracking merged `origin/main` exactly. No source
changes or commits were made on that branch during preparation.

Fresh local Python 3.11 baseline validation from an isolated temporary environment:

- full all-extras suite: 335 passed, 35 skipped;
- Ruff lint and formatting passed;
- frozen lock consistency passed;
- offline sdist and wheel builds passed;
- `git diff --check` passed.

No live Telegram, YouTube, or production-database calls were made.

## Focused architecture

```text
authorized private aiogram update
        ↓
TelegramSubmissionAdapter
  download actual bytes → shared full validation → trusted media evidence
        ↓
BotSubmissionIntakeService
  SubmissionService → ReplyChainService.create_*_intent
        ↓
pending intake acknowledgement
```

Handlers translate updates only. The adapter owns Telegram byte acquisition. The
intake service owns orchestration and replay recovery. Existing submission and
reply-chain services retain source and graph decisions.

This phase creates a validated submission and exactly one immutable placement
intent. It does not call `finalize_intent()`, send to the destination channel,
approve/reject moderation, or issue public reply buttons.

## Trust and source-selection rules

1. Keep the current admin/private pilot restriction.
2. Treat Bot API size, MIME, duration, filename, caption, and forwarded attribution
   as untrusted hints. Download the actual bytes into owned temporary storage and
   run size, duration, stream, hash, and full-decode validation before constructing
   `ValidatedTelegramMedia`.
3. Use Telegram `file_unique_id` as provider-scoped media identity. Never infer a
   stable source channel from a third-party downloader caption, button, username,
   or sender label.
4. For unverified Telegram-native media, select the logical thread before the
   expensive transfer. A normal `/submit` flow first stores an internal thread ID,
   then awaits media. An opaque reply entry already supplies the exact internal
   thread and parent. This avoids retaining raw Telegram coordinates or temporary
   files across a user-selection pause and avoids asking the user to download the
   same media twice.
5. FSM data contains only internal thread/parent/submission identifiers and the
   existing versioned reset state. It never stores file IDs, message text, raw
   tokens, captions, paths, or validation evidence.

## Replay and partial-failure algorithm

Media acquisition is deliberately outside database transactions. After validated
evidence exists, the durable steps are recoverable:

1. Bind one-use handoff state to actor, private conversation, and operation.
2. Before creating anything, query the private inbound `TelegramMessageRef`. If it
   already maps to a submission, load that submission instead of creating another.
3. Otherwise call `SubmissionService.submit()`, which atomically stores the
   submission, its private projection, and handoff consumption.
4. Query the placement intent by `submission_id`.
5. If absent, create `normal_append` or `interactive_reply` from the already
   authorized internal context.
6. If present, verify that its thread, mode, and exact parent match the requested
   operation and return an existing result. A mismatch is a typed conflict.
7. If submission commit succeeded but intent creation failed, replay resumes at
   step 4. It must not reacquire or duplicate the submission.
8. If commit success is ambiguous, reconcile the handoff/private projection before
   one explicit retry. Do not guess from exception text.

The repository currently needs an application-facing intent lookup by submission.
The existing unique submission constraint on `post_intents` supports this without
a new table. A safe submission/private-reference reconciliation method should hide
repository details from handlers. The admin-only pilot makes same-media recovery
unambiguous; any future multi-user access expansion must add explicit ownership
authorization before returning an existing submission.

## Implementation order

1. Add failing service/dispatcher regressions for normal intake, exact-parent
   intake, replay after each durable boundary, cancellation, and reset replacement.
2. Add intent-by-submission and safe private-reference reconciliation queries.
3. Implement the Telegram byte adapter with bounded download, temporary-file
   ownership, shared validation, cancellation, cleanup, and secret-safe errors.
4. Implement `BotSubmissionIntakeService` orchestration and stable result/error
   types. Preserve the primary failure if cleanup also fails.
5. Add normal source/thread selection and awaiting-media FSM states; reuse the
   existing exact-parent entry context and versioned replacement rules.
6. Wire thin aiogram handlers and dependencies through the application composition
   root. Keep `/download` and `/publish` as explicitly separate pilot utilities.
7. Run SQLite and disposable PostgreSQL recovery/concurrency coverage, real
   `Dispatcher.feed_update()` tests with fake Bot transport, Python 3.11 Linux and
   Windows CI, lint, lock, builds, artifact safety, and whitespace checks.
8. Update #5 acceptance and documentation. Do not close #7 or claim publication.

## Completion gate

- actual Telegram bytes are validated before trusted evidence exists;
- normal and exact-parent entries create the correct immutable intent without
  finalizing it;
- unverified media requires explicit internal thread selection;
- replay after submission commit but before intent commit recovers without a
  second submission, transfer, or conflicting intent;
- cancellation/reset cannot leave a later operation overwritten by stale work;
- handlers contain no source, graph, persistence, or delivery decisions;
- no destination-channel send, moderation decision, or live service call is part
  of this PR.

After this gate, implement #7's already documented durable publication states and
confirmed-parent delivery, then #8 moderation, then an explicitly authorized
private-channel pilot.

## Later owner review amendment

Before implementing this handoff, see bot-posting-review-2026-10-18.md and plan PR #26. The owner retained per-source automatic chains and authorized cross-provider exact replies with truthful provenance. Reopened #6 must separate provider identity from authorized placement first; selecting a target must not fabricate source metadata. Primary `/post` and deep-link entry share one modular intake flow. The prepared checkout remains untouched.

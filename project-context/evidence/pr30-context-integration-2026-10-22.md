# PR #30 project-context integration

Date: 2026-10-22

The previously unstaged project-context implementation and sanitized evidence from
the `feat/project-memory` checkout are integrated into `feat/bot-api-transport-pilot`,
starting at `5e144baa848b94e9fe6d7d45502486c1f324b52a`. This includes the source
catalog, typed records, taxonomy and schemas, generated brief/decision pages,
standard-library selector/validator, regression tests and AGENTS.md guidance.
README and documentation links introduce the context layer without replacing the
existing operational documents. CI validates records and generated output on both
Ubuntu and Windows; the existing PostgreSQL job is retained.

GitHub metadata verified during integration shows PR #28 merged at
`5f5ddfe19f1c73906e487023e5983377512b9e0c` and issue #5 closed. PR #29 remains an
open draft at `72b7cc19c10d33c40c95b317322a30141296d235`; PR #30 remains an open
draft stacked on it. Intake is merged; publication is implemented on the stack;
Issue #8 moderation remains pending. The startup decision now points to its
committed PR #30 implementation rather than claiming it is still uncommitted.

Current code also corrects an earlier handoff claim: a local operator recovery
entry point already exists in `cats_channel/publication/admin.py`, including
status, confirmation, proven non-delivery, explicit requeue and markup repair.
It requires `--bot-stopped` and exclusive operator ownership. This integration
does not run it or infer delivery from Bot API history.

The generated overview now honors supersedes links, matching focused selection,
so resolved network/pilot blockers do not appear as current open work. Original
incident records and evidence remain available. Revision sources use GitHub commit
links so offline validation does not depend on historical objects being present
in a shallow CI checkout. Validation checks local evidence and record structure;
it does not fetch remote links or independently verify historical test claims.

The private-pilot timings and delivery observations are preserved as dated
evidence, not re-executed here. No poller, Telegram send, runtime database, session,
credential or local environment profile is changed by this integration. Local
editor settings and parent-folder planning drafts are excluded. The original
checkout retains its unstaged files for safety.

## Integration validation

- WSL Python 3.11 full suite: `python -m pytest --capture=sys -q` — 463 passed,
  61 skipped. PostgreSQL remains opt-in; no local live PostgreSQL check was run.
- Focused project-context suite: 12 passed on WSL and 12 passed on Windows.
- Ruff lint, formatting and byte compilation passed on both platforms.
- Record validation, regeneration and generated-output checks passed on both
  platforms. Staged whitespace checks passed after LF normalization.
- A supplementary full Windows run produced no result and was interrupted;
  only its focused context suite is claimed here. CI must verify the final head.

These checks use the existing environments and do not rerun the private pilot.
Historical evidence test counts retain their original revision/platform scope.

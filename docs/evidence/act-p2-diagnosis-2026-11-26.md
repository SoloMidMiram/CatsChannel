# ACT-P2 diagnosis and implementation plan — 2026-11-26

GitHub main and the isolated implementation base both resolve to
`1d066c1e30b91798f642c2b28666ed72f5e56bdf`. Issue #61 is open.
Independent JSONL/date arithmetic reproduces 48 expired current records and
118 expired current sources at 2026-11-26 under the unchanged 30-day policy.
The previous 106-entry ACT-P2A reconciliation is retained as dated work, not
present acceptance. Its metadata-only diff is being extended on this branch.

Root causes: dated test/merge/pilot observations were labeled current; mixed
decisions combined enduring contracts with implementation snapshots; fact-028's
October board observation outlived issue #5's closure. Internal validation already
supports `today=`, but CLI replay cannot specify it. Receipt paths are checked
for existence without digest verification. Source-reference existence does not
establish evidentiary support or live readiness. Stale/unknown dependencies need
explicit rejection for current claims. Current freshness is intentionally strict.

Plan before validator changes: inventory all 166 IDs with originals, dependencies,
dispositions and evidence; preserve earlier reconciliation and original receipts;
scope dated artifacts individually; preserve fact-028 and its supported successor;
expose explicit CLI as-of replay without changing the default clock; add optional
canonical-text receipt digests, dependency and supersession diagnostics; extend
deterministic regression tests; regenerate source-derived pages; run scoped and
full checks and record missing platform evidence as blocked. Do not change
application code, CI workflows, dependencies or production policy.

Fresh hosted CI and independent technical review remain acceptance requirements.
The browser session could not view the private issue (GitHub not-found page);
the authorized GitHub connector read issue #61, main, open PRs and recent runs.
Latest hosted success is still the November 15 baseline, not this candidate.

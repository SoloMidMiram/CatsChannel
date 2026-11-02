# Two-path media decision and merge reconciliation — 2026-11-02

PR #39 merged at `645229aa3b150fed3231358c44c1d8209c5c5a74` after explicit
owner authorization, using the normal merge API pinned to reviewed head
`3b3101070cc59180c2ebc78a8802188ea63c33dc`. All three head CI jobs passed in
run `41339863014`. No administrator bypass or fabricated review was used.
Earlier policy API HTTP 403 responses and the earlier rejected merge attempt
remain historical evidence; the authorized normal merge subsequently succeeded.

PR #40 incorporates this main baseline. JSONL conflicts retain both source-144 /
fact-064 (the pilot receipt) and source-145 / fact-065 (earlier reconciliation).
The overview and decision files are regenerated from the combined records.
Fact-065 is historical and superseded by fact-066; its earlier observations and
the failed experiments are preserved. No new live Telegram operation occurred.

## Superseding decision-002

The original universal MediaService/library acquisition requirement is historical.
Decision-024 explicitly supersedes it with the two paths implemented in PR #38:

| Input path | Required evidence and handling |
| --- | --- |
| Local-library acquisition | MediaService validation, full decode, manifest integrity and SHA-256 checks remain mandatory |
| Telegram-hosted video | Reported metadata policy bound to receiving bot; telegram_metadata, full_decode=false, sha256=null; bot-specific file_id reuse without getFile, download, hashing or decoding |

Both paths converge on durable submission, review and publication services.
Metadata acceptance is not byte-integrity or safety verification. Identity and
placement provenance remain distinct. Publication retains duplicate/unknown-send
guards and exact-parent confirmation requirements.

Sources: [hosted policy](../TELEGRAM_HOSTED_REUSE.md),
[PR #38](https://github.com/SoloMidMiram/CatsChannel/pull/38),
[merged pilot receipt](telegram-hosted-private-acceptance-2026-11-01.md),
`tests/test_telegram_hosted_reuse.py`, `tests/test_aiogram_publisher.py` and
`tests/test_library.py`. This correction changes no runtime behavior.

PR #40 remains open for review; its earlier head CI run 41484223894 does not
qualify this revised head. New exact-head checks are required. Issue #8 audited
rejection remains next, followed by enforced private-inspection/publication
separation; public deployment is not authorized.

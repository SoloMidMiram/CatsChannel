# Telegram-hosted private acceptance — 2026-11-01

Result: **passed for the bounded private pilot**, not public production acceptance.

Tested merged main `54e88b0ec80ee0538c5b9cf673c2c96d73cd0dff`, the merge of
PR #38. Its reviewed head `6dfbbe8` passed Ubuntu, Windows and PostgreSQL CI in
run `41324682815`. No new formal GitHub review was manufactured. GitHub reported
clean mergeability and no outstanding review threads. Protection/rules API reads
returned a plan-restriction error; normal head-pinned merge succeeded without an
admin bypass.

## Reconciliation and bounded ownership

Before handover the existing poller was confirmed alive, then stopped gracefully
with zero active updates. Database migration was 0006, with four submissions,
three confirmed publications and one confirmed/approved review. There were no
in-progress send/approval records. A SQLite backup and baseline IDs were saved
locally before startup. The existing failed oversized attempts were not resent.

The new observer verified the configured destination was the known restricted
private pilot channel, with no public username. One owned poller used the merged
code, existing configuration and database. The observer allowed one successful
intake and had a 900-second maximum lifetime. It guarded/counts `getFile`, byte
download and decoder calls. No approval click or publication command was simulated.

## Observed receipt

- Owner submitted **23,220,422 bytes**, duration **171 seconds**, above both 20 MB
  and 20 MiB. Durable submission: `a8dab22d-c333-46bc-8539-72b4e398459e`.
- Evidence is `telegram_metadata`, `full_decode=false`, `sha256=null`, with the
  receiving bot ID persisted. No stream count or byte-validation claim is made.
- Review delivery was confirmed at private message 1231. The configured admin
  approved it at 18:56:41 UTC; stored reviewer identity matches the configuration.
- Publication `dbe4e337-277f-4dc6-8916-2dc4e6d16f1d` is confirmed with exactly
  **one publication attempt**. There is exactly one new submission/publication
  relative to baseline.
- Read-only Telethon read-back verified published message **1232** actually replies
  to selected parent **1230**, and that review/published messages reference the
  same Telegram document. The published video reports 23,220,422 bytes.
- Review caption is now `Approved. Published to the channel.`; its Approve button
  is removed. The published message has its reply button.
- Final observer counters: **0 getFile calls, 0 byte-download calls, 0 decoder
  calls**, one successful intake, 80 successful polls and zero polling failures.
  No media-byte digest was produced; metadata evidence retains a null SHA-256.
- After success a later video was rejected with `intake_unavailable` by the
  temporary **one-item observer guard**. This was not a production intake failure
  or an additional publication. The owner should not interpret that harness
  restriction as the application's normal multi-submission policy.
- The observer stopped gracefully at 18:58:57 UTC with zero active updates, and
  both owned Python processes were confirmed absent. Read-back used no sends or
  media download and completed connection cleanup without pending ownership.

Ignored local evidence lives under `.runtime/hosted-live-20261101/`: baseline,
pre-pilot backup, status/counters, sanitized operation log, durable audit and
Telegram read-back. No credentials, file IDs, private message bodies or media
bytes are included in this receipt.

## Remaining boundaries

Metadata does not establish media-byte integrity or safety. This run does not
force the target-resolution race or establish restart durability before intake
commit. It does not establish sustained availability. The private experiment
uses the same inspection/publication destination; public deployment still requires
enforced separation and complete moderation acceptance. **Issue #8 remains open.**

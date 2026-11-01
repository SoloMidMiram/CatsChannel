# Telegram-hosted video intake

The default bot video intake uses Telegram's hosted media reference. It checks
reported file size, positive duration/dimensions, and the configured size/duration
policy without `getFile`, downloading bytes, hashing, FFprobe or FFmpeg. A missing
file size is rejected. `MAX_DOWNLOAD_MB` continues to bound the reported size;
it does not require a download or impose Telegram's smaller download limit.

Accepted submissions persist `telegram_metadata` evidence: receiving bot ID,
reported size/duration, timestamp, `full_decode: false` and `sha256: null`. There
is no invented stream count, codec, digest or byte-validation claim. Metadata
acceptance is not proof that the file is decodable or safe; the reviewer must
inspect the preview. The review caption explicitly says that bytes were not
decoded. Source identity remains independent and may be unresolved.

Review and approval still use the durable review/publication services. The
publisher validates metadata evidence, current limits, media origin and receiving
bot ID, then calls `sendVideo` with the stored bot-specific `file_id`. It never
uses `file_unique_id` to send: that identifier remains the deduplication key.
The review copy and confirmed destination post are separate messages. The latter
retains the exact parent's confirmed projection and disallows reply fallback.
Repeated approval and unknown-send reconciliation retain their existing guards.

Metadata evidence cannot authorize local-library publication. YouTube/local items
retain full decode, manifest integrity and digest requirements. Existing decoded
Telegram submissions remain readable and publishable, but no longer call
`getFile` before sending. An invalid/unusable hosted ID is rejected by the send
API; transport ambiguity remains `unknown`, not an automatic retry.

No schema migration is needed: validation evidence already uses JSON. Existing
rows are not rewritten, and stored full-decode evidence is not fabricated for new
hosted submissions. Moving to a different bot requires new bot-specific file
references; metadata evidence bound to another bot fails before dispatch.

Tests in `test_telegram_hosted_reuse.py` forbid `getFile`, download and decoding,
exercise a 30 MB file, reject malformed/oversized metadata and forged evidence,
and cover real dispatcher intake -> durable pending review -> approval -> exact
parent publication with repeat approval and unchanged normal tail. Existing local
library and publication incident suites remain required gates.

This PR is separate from #36 and #37. It does not change public intake access,
moderation authorization, channel-isolation safeguards, retry policy, or the live
pilot process. No live approval/publication acceptance is claimed by offline tests.

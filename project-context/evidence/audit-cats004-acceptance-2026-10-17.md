# CATS-004 acceptance and trusted-entry audit

Issue #5's service-level acceptance criteria are implemented in merged PR #16 at
main revision `3ba1b2baa09d6567815969bf0129564a62cda47b` with final feature tree
`c2998a24a7b9bdac27b09d977e5379b868c9a4a7`.

Verified scope includes:

- internal submission identity and lifecycle state;
- normalized source metadata, validation evidence, and provenance;
- explicit local-file and Telegram-native input contracts;
- atomic, bound, one-use handoff consumption;
- repository and unit-of-work persistence;
- typed service errors and conservative source resolution;
- no use of usernames, message IDs, captions, or filenames as internal identity;
- unit, integration, migration, rollback, uniqueness, and concurrency coverage.

The remaining trust boundary is deliberate rather than an exposed acceptance
defect. `ValidatedTelegramMedia` is a trusted internal assertion; it is not a wire
model and must not be constructed from untrusted external payloads. No current
submission handler exposes that constructor. A future Telegram-native adapter must
authenticate the transport, fetch the actual bytes, validate them through the
shared media path, use Telegram `file_unique_id` in the provider namespace, and
only then construct the trusted evidence object.

Consequently, the merged source-aware service can be accepted independently, but
a live submission handler must remain gated on that bounded adapter. Parent
selection belongs to issue #6 and Bot API publication belongs to issue #7; neither
should be folded into issue #5 merely to close it.

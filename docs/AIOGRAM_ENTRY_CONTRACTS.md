# Aiogram entry and lifecycle contracts

This completes issue #3's transport/application-core acceptance. It reuses the
merged media, submission, persistence, logging and error policies.

## Ownership and shutdown

`create_bot_application()` constructs a Bot and dispatcher without opening a
network connection. Injected `bot` and `storage` transfer lifecycle ownership to
the application when `start_polling()` runs. Settings, the media service and reply
resolver are ordinary borrowed dependencies. Optional `resources` are factories
for async context managers: creation/entry happens at startup and successful
entries are unwound in reverse order. No persistence dependency is mandatory.

An application runs once. Normal stop or caller cancellation finishes polling,
cancels and drains accepted updates, emits shutdown once, closes FSM storage,
unwinds resources and finally closes its owned bot session. Failed startup also
unwinds acquired resources. Repeated cancellation cannot abandon cleanup; cleanup
must finish before ownership is reported released. Cleanup failure is logged
through secret-safe diagnostics and remains visible without replacing an earlier
startup or operation failure; caller cancellation still propagates. Shutdown may
wait for a media worker's existing cancellation drain.
The dispatcher preserves the active polling failure before aiogram delegates
shutdown from its `finally`; a simultaneous shutdown failure is chained as its
cause, rather than becoming the primary error.

The old `start_polling(other_bot)` form is supported: that separate bot is
borrowed and the caller closes it. The factory's own bot is still closed here.
For the normal CLI path, call `start_polling()` without overriding the bot.

## Public reply entry

`new_reply_token()` generates 256 random bits encoded as 43 canonical base64url
characters. `build_reply_link(username, token)` emits
`https://t.me/<bot>?start=catreply_<opaque-token>`, within Telegram's 64-character
payload limit. Parsing rejects malformed, noncanonical, coordinate-derived, or
other token namespaces. Tokens must be randomly issued, never encoded IDs.

`ReplyTargetResolver.resolve(token, actor_id=...)` owns availability, expiry and
actor authorization checks, and returns a `ReplyTarget(post_id, thread_id)` of
canonical internal UUIDs or `None`. The core validates syntax before calling it
and stores no raw token in FSM state or logs. Unavailable and malformed links get
the same safe response. Baseline resolution fails closed. The reply-chain domain
now supplies a database-backed mapping through explicit persistent composition;
see [reply-chain setup and policy](REPLY_CHAIN_DOMAIN.md). Public reply links are
not one-use submission handoffs.

After authorized resolution, `/start` records only the selected internal context
and acknowledges it. It does not request or accept media. Bare `/start` retains
the help behavior. Existing private-chat/admin restrictions apply before resolver
invocation or state mutation. The public URL convention does not itself grant
public access to the current admin-only pilot.

## Private state and command replacement

`PrivateEntryContext` contains only `thread_id`, `parent_post_id`, and optional
`submission_id`, all internal UUIDs. Built-in FSM storage keys still route by chat
and user as required by aiogram; those coordinates never become domain IDs in
the state data. Private text, captions, tokens and raw Telegram payloads are not
stored. Invalid legacy entry data is rejected and cleared.

Every recognized authorized command clears the prior private flow before its
handler runs. `/cancel` explicitly clears it. Commands addressed to another bot,
unknown messages and unauthorized/group input do not replace a flow. A slower
reply lookup cannot overwrite state after a newer command replaces it. Small
state transitions are serialized; acquisition work remains concurrent enough for
the existing media gate to return its busy response. A failed or cancelled entry
confirmation clears its own partial state. If that clear also fails, the original
failure or cancellation remains primary and the cleanup failure is chained.

Default state is in-memory and ephemeral. Durable product workflow state, if
needed later, belongs to its application/persistence owner rather than raw FSM
message dumps. Injected persistent storage must obey the same ownership contract.

## Intake ownership at persistence boundaries

Source selection increments the flow version, invalidating downloads for the
previous source. Capture the lease before reading entry state or awaiting source
lookups. A slow selection lookup cannot adopt a newer command's lease.

Intake rechecks ownership after handoff issuance. Both media handlers pass a
commit guard that validates the lease and serializes submission/intent persistence
and recovery against command or source replacement. Acquisition and handoff
issuance run outside that guard. If replacement wins before the guard, the old
operation cannot submit. Once the guarded commit starts, replacement waits until
it finishes; cancellation cannot retroactively undo committed intake. Successful
intake reports pending even if a newer command runs before acknowledgement, and
its stale clear cannot erase the new state. Task cancellation still propagates and
releases the guard. Non-bot callers without replaceable flow ownership may omit
the guard; a standalone boolean ownership check does not serialize replacement.

## Callback convention

`ModerationCallback` packs/unpacks `catmod:<approve|reject>:<internal-submission-uuid>`
and stays under the 64-byte callback limit. Raw Telegram coordinates, unknown
actions and malformed IDs are rejected. No approval/rejection handler is
registered by this core PR; moderation authorization and state changes remain #8.

## Evidence

The real dispatcher and polling lifecycle are exercised with mocked Bot API
transport. Tests cover parser/callback round trips and hostile inputs, authorized
lookup before state entry, unavailable targets, state reset, cancellation,
replacement races, partial startup failure, teardown failure, reverse cleanup,
borrowed-versus-owned sessions, and draining active updates before storage close.
Existing command, media gate, safe logging and error-category tests remain in the
full suite. No live Telegram or YouTube call is needed for these core contracts.

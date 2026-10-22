# Live end-to-end private publication pilot

Date: 2026-10-22

The corrected aiogram poller accepted one fresh `/post` in 2.7 seconds. Telethon
selected the existing pilot source and forwarded the previously stored downloader
response exactly once. The Bot API file transfer and full decode completed in
67.1 seconds, proving the new 180-second file budget resolves the observed
30-second default-timeout failure.

Durable intake created one validated Telegram-native submission and one normal
placement intent. Full decode evidence is true and source identity is explicitly
`user_selected`; the downloader source was not independently verified as a
YouTube identity.

After durable reconciliation, Telethon sent `/pilot_publish` exactly once. The
running bot invoked PR #29's publication service, which recorded one attempt and
transitioned `sending` to `confirmed`. Final database counts are one submission,
one intent, one logical post, one publication, one confirmed attempt, and two
message references with purposes `private` and `destination`. No alternate sender
or automatic media/publication retry was used.

The configured destination is the authorized private pilot channel. This is not
evidence of publication to the public production channel, and it does not
implement Issue #8's separate moderation queue. The poller remained running after
confirmation.

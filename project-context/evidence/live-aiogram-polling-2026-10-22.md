# Live aiogram polling verification

Date: 2026-10-22

The real application was started directly with the configured Bot API route and
a 180-second request budget, without gating startup on the one-shot preflight.
The process completed `getMe`, entered `getUpdates`, and remained alive after a
`TelegramNetworkError`. Aiogram logged its built-in one-second polling backoff and
continued running. This verifies that the bounded identity bootstrap and existing
long-poll recovery are operating at their intended separate boundaries.

At the observation point there was one Python bot process, zero durable
submissions/posts/publications, and no media forward or publication by the test
harness. The poller was intentionally left running for the authorized user to
continue the private `/post` interaction.

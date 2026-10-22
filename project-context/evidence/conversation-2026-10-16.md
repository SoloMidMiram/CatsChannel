# Conversation evidence extract — 2026-10-16

This is a redacted, checked-in extract of project-shaping statements from the
local Codex conversation. The chat remains the original source; this extract gives
important statements stable repository anchors without copying credentials,
phone numbers, cookie contents, session material, or raw operational logs.

The message IDs below were assigned when this evidence was captured because the
chat export did not expose stable platform message identifiers.

## message-001 — environment separation

> Keep Windows and WSL virtual environments separate.

## message-002 — media backend motivation

The user reported that direct yt-dlp reliability had remained unsuccessful over
an extended period and proposed an optional Telethon user-account backend that
asks a third-party Telegram downloader bot for the video instead of using YouTube
cookies.

## message-003 — session safety

The user explicitly asked whether the Telethon session was safe and excluded from
commits. The implemented policy stores the session outside the repository and
keeps runtime session files ignored.

## message-004 — review and readiness discipline

Repeated reviews required current code, offline reproductions, Windows and WSL
tests, secret-safe output, and GitHub CI evidence before a branch could be called
ready. A cancelled disconnect was specifically required to retain the external
session lock unless resource closure was confirmed.

## message-005 — durable project memory objective

> Give the project a durable, inspectable memory.

The requested four layers are original evidence, structured records, a current
project brief, and focused context selection. The source, status, and freshness of
records are mandatory. Narrative output must be generated from records so there
are not two competing accounts. Keyword and explicit-tag retrieval comes first;
semantic retrieval is deferred until vocabulary differences cause demonstrated
misses.

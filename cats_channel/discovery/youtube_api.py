"""Opt-in YouTube Data API adapter for the watchlist's ChannelResolver port."""

import asyncio
import json
import re

from aiohttp import ClientError, ClientSession

from .domain import Resolution, Status, normalize

_CHANNELS_URL = "https://www.googleapis.com/youtube/v3/channels"
_MAX_RESPONSE_BYTES = 64 * 1024


class YouTubeChannelResolver:
    def __init__(self, session: ClientSession, *, api_key: str):
        self._session = session
        self._api_key = api_key

    async def resolve(self, reference: str) -> Resolution:
        try:
            reference = normalize(reference)
        except ValueError:
            return Resolution(Status.INVALID_INPUT)
        if not self._api_key:
            return Resolution(Status.CONFIGURATION_ERROR)

        by_handle = reference.startswith("@")
        params = {
            "part": "snippet,contentDetails",
            "fields": "items(id,snippet(title,customUrl),contentDetails(relatedPlaylists(uploads)))",
            "forHandle" if by_handle else "id": reference,
        }
        try:
            async with (
                asyncio.timeout(10),
                self._session.get(
                    _CHANNELS_URL,
                    params=params,
                    headers={"X-Goog-Api-Key": self._api_key},
                    allow_redirects=False,
                ) as response,
            ):
                if response.status == 429:
                    return Resolution(Status.RATE_LIMITED)
                if response.status == 404:
                    return Resolution(Status.UNAVAILABLE, evidence="provider_unavailable")
                status = response.status
                if status not in {200, 401, 403}:
                    return Resolution(Status.TEMPORARY_FAILURE)
                data = bytearray()
                async for chunk in response.content.iter_chunked(8192):
                    data.extend(chunk)
                    if len(data) > _MAX_RESPONSE_BYTES:
                        return Resolution(Status.TEMPORARY_FAILURE)
                try:
                    payload = json.loads(data)
                except ValueError:
                    payload = None
        except (ClientError, TimeoutError, ValueError):
            return Resolution(Status.TEMPORARY_FAILURE)

        if status != 200:
            error = payload.get("error") if isinstance(payload, dict) else None
            errors = error.get("errors") if isinstance(error, dict) else None
            if isinstance(errors, list) and any(
                isinstance(item, dict)
                and item.get("reason")
                in ("quotaExceeded", "dailyLimitExceeded", "rateLimitExceeded")
                for item in errors
            ):
                return Resolution(Status.RATE_LIMITED)
            return Resolution(Status.CONFIGURATION_ERROR)
        return _parse_channel(payload, reference, by_handle)


def _parse_channel(payload: object, reference: str, by_handle: bool) -> Resolution:
    items = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        return Resolution(Status.TEMPORARY_FAILURE)
    if not items:
        return Resolution(Status.UNAVAILABLE, evidence="provider_unavailable")
    if len(items) != 1:
        return Resolution(Status.AMBIGUOUS)

    item = items[0]
    if not isinstance(item, dict):
        return Resolution(Status.TEMPORARY_FAILURE)
    channel_id = item.get("id")
    if not isinstance(channel_id, str) or not re.fullmatch(r"UC[A-Za-z0-9_-]{22}", channel_id):
        return Resolution(Status.TEMPORARY_FAILURE)
    if not by_handle and channel_id != reference:
        return Resolution(Status.AMBIGUOUS)

    snippet = item.get("snippet")
    snippet = snippet if isinstance(snippet, dict) else {}
    handle = snippet.get("customUrl")
    handle = (
        handle.lower()
        if isinstance(handle, str) and re.fullmatch(r"@[A-Za-z0-9][A-Za-z0-9_.-]{2,29}", handle)
        else None
    )
    if by_handle and handle is not None and handle != reference:
        return Resolution(Status.AMBIGUOUS)

    title = snippet.get("title")
    details = item.get("contentDetails")
    playlists = details.get("relatedPlaylists") if isinstance(details, dict) else None
    uploads = playlists.get("uploads") if isinstance(playlists, dict) else None
    try:
        return Resolution(
            Status.RESOLVED,
            channel_id=channel_id,
            handle=handle or (reference if by_handle else None),
            display_name=title if isinstance(title, str) else None,
            evidence="provider_channel_id",
            uploads_playlist_id=uploads,
        )
    except ValueError:
        return Resolution(Status.TEMPORARY_FAILURE)

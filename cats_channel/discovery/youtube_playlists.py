"""Offline-testable YouTube playlist adapter. Each page consumes at most one request."""

import re
from datetime import UTC, datetime

from aiohttp import ClientSession

from .domain import Candidate, PageResult, Status
from .youtube_api import _YouTubeAPI


class YouTubePlaylistProvider:
    def __init__(
        self,
        session: ClientSession,
        *,
        api_key: str,
        channel_id: str,
        uploads_playlist_id: str | None = None,
        experimental_shorts: bool = False,
    ):
        if not re.fullmatch(r"UC[A-Za-z0-9_-]{22}", channel_id):
            raise ValueError("invalid_channel_identity")
        if experimental_shorts:
            if uploads_playlist_id is not None:
                raise ValueError("ambiguous_playlist")
            playlist_id = "UUSH" + channel_id[2:]
        elif uploads_playlist_id and re.fullmatch(r"[A-Za-z0-9_-]{1,128}", uploads_playlist_id):
            playlist_id = uploads_playlist_id
        else:
            raise ValueError("invalid_uploads_playlist_id")

        self._api = _YouTubeAPI(session, api_key=api_key)
        self._channel_id = channel_id
        self._playlist_id = playlist_id
        self._classification = "shorts_playlist" if experimental_shorts else "unknown"
        self._method = "youtube_uush" if experimental_shorts else "youtube_uploads"

    async def page(self, cursor: str | None = None, *, limit: int = 10) -> PageResult:
        if type(limit) is not int or not 1 <= limit <= 50:
            return PageResult((), "failed", failure=Status.INVALID_INPUT, items_examined=0)
        if cursor is not None and not _valid_cursor(cursor):
            return PageResult((), "failed", failure=Status.INVALID_INPUT, items_examined=0)
        params = {
            "part": "snippet,contentDetails",
            "fields": (
                "nextPageToken,items(snippet(title,videoOwnerChannelId),"
                "contentDetails(videoId,videoPublishedAt))"
            ),
            "playlistId": self._playlist_id,
            "maxResults": str(limit),
        }
        if cursor is not None:
            params["pageToken"] = cursor
        payload, failure = await self._api.get("playlistItems", params)
        if failure is not None:
            return PageResult((), "failed", failure=failure, items_examined=0)
        items = payload.get("items") if isinstance(payload, dict) else None
        if not isinstance(items, list):
            return PageResult((), "failed", failure=Status.TEMPORARY_FAILURE, items_examined=0)
        if len(items) > limit:
            return PageResult(
                (), "failed", failure=Status.TEMPORARY_FAILURE, items_examined=len(items)
            )
        next_cursor = payload.get("nextPageToken")
        if next_cursor is not None and (not _valid_cursor(next_cursor) or next_cursor == cursor):
            return PageResult(
                (), "failed", failure=Status.CURSOR_EXPIRED, items_examined=len(items)
            )

        observed_at = datetime.now(UTC)
        candidates = {}
        malformed = False
        for item in items:
            candidate = self._candidate(item, observed_at)
            if candidate is None:
                malformed = True
            else:
                candidates.setdefault(candidate.video_id, candidate)
        return PageResult(
            tuple(candidates.values()),
            "partial" if malformed else "complete",
            next_cursor=None if malformed else next_cursor,
            failure=Status.TEMPORARY_FAILURE if malformed else None,
            items_examined=len(items),
        )

    def _candidate(self, item: object, observed_at: datetime) -> Candidate | None:
        if not isinstance(item, dict):
            return None
        snippet = item.get("snippet")
        details = item.get("contentDetails")
        if not isinstance(snippet, dict) or not isinstance(details, dict):
            return None
        if snippet.get("videoOwnerChannelId") != self._channel_id:
            return None
        video_id = details.get("videoId")
        title = snippet.get("title")
        published = details.get("videoPublishedAt")
        if not isinstance(video_id, str) or (title is not None and not isinstance(title, str)):
            return None
        if published is not None and not isinstance(published, str):
            return None
        try:
            return Candidate(
                channel_id=self._channel_id,
                video_id=video_id,
                observed_at=observed_at,
                discovery_method=self._method,
                title=title,
                published_at=datetime.fromisoformat(published) if published else None,
                classification=self._classification,
                evidence=("playlist_item", "video_owner_channel_id"),
            )
        except ValueError:
            return None


def _valid_cursor(value: object) -> bool:
    return (
        isinstance(value, str)
        and 0 < len(value) <= 2048
        and all(33 <= ord(character) < 127 for character in value)
    )

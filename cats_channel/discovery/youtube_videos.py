"""Explicit known-video metadata lookup, independent of playlist membership."""

import re
from dataclasses import dataclass
from datetime import datetime

from aiohttp import ClientSession

from ..youtube_urls import youtube_url
from .domain import Status
from .youtube_api import _YouTubeAPI


@dataclass(frozen=True)
class VideoLookup:
    status: Status
    video_id: str | None = None
    channel_id: str | None = None
    title: str | None = None
    published_at: datetime | None = None


class YouTubeVideoLookup:
    def __init__(self, session: ClientSession, *, api_key: str):
        self._api = _YouTubeAPI(session, api_key=api_key)

    async def lookup(
        self, reference: str, *, expected_channel_id: str | None = None
    ) -> VideoLookup:
        if not isinstance(reference, str) or len(reference) > 2048:
            return VideoLookup(Status.INVALID_INPUT)
        try:
            video_id = (
                reference
                if re.fullmatch(r"[A-Za-z0-9_-]{11}", reference)
                else youtube_url(reference).rsplit("=", 1)[1]
            )
        except ValueError:
            return VideoLookup(Status.INVALID_INPUT)
        if expected_channel_id is not None and not _valid_channel(expected_channel_id):
            return VideoLookup(Status.INVALID_INPUT, video_id)

        payload, failure = await self._api.get(
            "videos",
            {
                "part": "snippet",
                "fields": "items(id,snippet(channelId,title,publishedAt))",
                "id": video_id,
            },
        )
        if failure is not None:
            return VideoLookup(failure, video_id)
        items = payload.get("items") if isinstance(payload, dict) else None
        if not isinstance(items, list):
            return VideoLookup(Status.TEMPORARY_FAILURE, video_id)
        if not items:
            return VideoLookup(Status.UNAVAILABLE, video_id)
        if len(items) != 1:
            return VideoLookup(Status.AMBIGUOUS, video_id)
        item = items[0]
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            return VideoLookup(Status.TEMPORARY_FAILURE, video_id)
        if item["id"] != video_id:
            return VideoLookup(Status.AMBIGUOUS, video_id)
        snippet = item.get("snippet")
        if not isinstance(snippet, dict):
            return VideoLookup(Status.TEMPORARY_FAILURE, video_id)
        channel_id = snippet.get("channelId")
        if not _valid_channel(channel_id):
            return VideoLookup(Status.TEMPORARY_FAILURE, video_id)
        if expected_channel_id is not None and expected_channel_id != channel_id:
            return VideoLookup(Status.AMBIGUOUS, video_id)
        title = snippet.get("title")
        raw_date = snippet.get("publishedAt")
        if title is not None and (not isinstance(title, str) or len(title) > 500):
            return VideoLookup(Status.TEMPORARY_FAILURE, video_id)
        try:
            published_at = datetime.fromisoformat(raw_date) if raw_date is not None else None
        except (TypeError, ValueError):
            return VideoLookup(Status.TEMPORARY_FAILURE, video_id)
        if published_at is not None and published_at.tzinfo is None:
            return VideoLookup(Status.TEMPORARY_FAILURE, video_id)
        return VideoLookup(Status.RESOLVED, video_id, channel_id, title, published_at)


def _valid_channel(value: object) -> bool:
    return isinstance(value, str) and bool(re.fullmatch(r"UC[A-Za-z0-9_-]{22}", value))

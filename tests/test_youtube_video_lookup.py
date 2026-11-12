import asyncio
from datetime import UTC, datetime

import pytest
from test_youtube_channel_resolver import CHANNEL, FakeSession

from cats_channel.discovery.domain import Status
from cats_channel.discovery.youtube_videos import YouTubeVideoLookup

VIDEO = "abcdefghijk"


def item(*, video=VIDEO, owner=CHANNEL):
    return {"id": video, "snippet": {"channelId": owner, "publishedAt": "2026-11-08T10:00:00Z"}}


@pytest.mark.parametrize(
    "reference",
    [
        VIDEO,
        f"https://www.youtube.com/watch?v={VIDEO}",
        f"https://youtube.com/shorts/{VIDEO}",
        f"https://youtu.be/{VIDEO}",
    ],
)
async def test_video_references_converge_to_one_fixed_endpoint(reference):
    session = FakeSession({"items": [item()]})
    result = await YouTubeVideoLookup(session, api_key="fixture-key").lookup(
        reference, expected_channel_id=CHANNEL
    )
    assert (result.status, result.video_id, result.channel_id) == (Status.RESOLVED, VIDEO, CHANNEL)
    assert result.title is None and result.published_at == datetime(2026, 11, 8, 10, tzinfo=UTC)
    [(url, args)] = session.calls
    assert url == "https://www.googleapis.com/youtube/v3/videos"
    assert args["params"]["id"] == VIDEO
    assert "fixture-key" not in repr(result)


@pytest.mark.parametrize(
    ("payload", "http_status", "expected"),
    [
        ({"items": []}, 200, Status.UNAVAILABLE),
        ({"items": [item(video="bcdefghijkl")]}, 200, Status.AMBIGUOUS),
        ({"items": [item(owner="UC" + "z" * 22)]}, 200, Status.AMBIGUOUS),
        ({"items": [None]}, 200, Status.TEMPORARY_FAILURE),
        ({}, 429, Status.RATE_LIMITED),
    ],
)
async def test_lookup_failure_preserves_requested_identity(payload, http_status, expected):
    session = FakeSession(payload, status=http_status)
    result = await YouTubeVideoLookup(session, api_key="fixture-key").lookup(
        VIDEO, expected_channel_id=CHANNEL
    )
    assert result.status == expected and result.video_id == VIDEO
    assert result.channel_id is None and len(session.calls) == 1


async def test_invalid_input_and_cancellation():
    session = FakeSession(failure=asyncio.CancelledError())
    lookup = YouTubeVideoLookup(session, api_key="fixture-key")
    assert (
        await lookup.lookup("https://example.com/watch?v=" + VIDEO)
    ).status == Status.INVALID_INPUT
    assert not session.calls
    with pytest.raises(asyncio.CancelledError):
        await lookup.lookup(VIDEO)

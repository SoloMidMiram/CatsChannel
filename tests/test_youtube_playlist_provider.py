import asyncio
from datetime import UTC, datetime

import pytest
from test_youtube_channel_resolver import CHANNEL, UPLOADS, FakeSession

from cats_channel.discovery.domain import Status
from cats_channel.discovery.youtube_playlists import YouTubePlaylistProvider


def item(video="abcdefghijk", *, owner=CHANNEL):
    return {
        "snippet": {
            "title": None,
            "videoOwnerChannelId": owner,
            "channelId": "UC" + "b" * 22,
            "publishedAt": "2026-11-10T10:00:00Z",
        },
        "contentDetails": {"videoId": video, "videoPublishedAt": "2026-11-08T10:00:00Z"},
    }


def provider(session, *, experimental=False):
    return YouTubePlaylistProvider(
        session,
        api_key="fixture-key",
        channel_id=CHANNEL,
        uploads_playlist_id=None if experimental else UPLOADS,
        experimental_shorts=experimental,
    )


@pytest.mark.parametrize("experimental", [False, True])
async def test_two_pages_preserve_provenance_and_raw_item_count(experimental):
    session = FakeSession({"items": [item(), item()], "nextPageToken": "page-2"})
    listing = provider(session, experimental=experimental)
    first = await listing.page(limit=2)
    assert first.checkpoint_may_advance
    assert first.items_examined == 2
    [candidate] = first.candidates
    assert candidate.classification == ("shorts_playlist" if experimental else "unknown")
    assert candidate.published_at == datetime(2026, 11, 8, 10, tzinfo=UTC)
    assert candidate.title is None

    session.payload = {"items": [item("bcdefghijkl")]}
    second = await listing.page(first.next_cursor, limit=1)
    assert second.checkpoint_may_advance and second.next_cursor is None
    assert second.items_examined == 1
    first_call, second_call = session.calls
    assert first_call[0].endswith("/playlistItems")
    assert first_call[1]["params"]["playlistId"] == (
        "UUSH" + CHANNEL[2:] if experimental else UPLOADS
    )
    assert second_call[1]["params"]["pageToken"] == "page-2"
    assert second_call[1]["params"]["maxResults"] == "1"


async def test_partial_page_keeps_valid_candidates_without_advancing():
    session = FakeSession(
        {"items": [item(), item(owner=None), {"unavailable": True}], "nextPageToken": "page-2"}
    )
    page = await provider(session).page()
    assert page.state == "partial"
    assert page.items_examined == 3 and len(page.candidates) == 1
    assert not page.checkpoint_may_advance and page.next_cursor is None


@pytest.mark.parametrize(
    ("http_status", "payload", "cursor", "failure"),
    [
        (404, {}, None, Status.UNAVAILABLE),
        (200, {}, None, Status.TEMPORARY_FAILURE),
        (200, {"items": [], "nextPageToken": "loop"}, "loop", Status.CURSOR_EXPIRED),
        (400, {"error": {"errors": [{"reason": "invalidPageToken"}]}}, "x", Status.CURSOR_EXPIRED),
        (403, {}, None, Status.CONFIGURATION_ERROR),
        (429, {}, None, Status.RATE_LIMITED),
    ],
)
async def test_failed_page_never_advances(http_status, payload, cursor, failure):
    session = FakeSession(payload, status=http_status)
    page = await provider(session).page(cursor)
    assert page.failure == failure and not page.checkpoint_may_advance
    assert len(session.calls) == 1


async def test_empty_playlist_and_invalid_budgets():
    session = FakeSession({"items": []})
    listing = provider(session)
    assert (await listing.page(limit=0)).failure == Status.INVALID_INPUT
    assert (await listing.page("bad token")).failure == Status.INVALID_INPUT
    assert not session.calls
    page = await listing.page()
    assert page.checkpoint_may_advance and page.items_examined == 0


async def test_timeout_and_cancellation():
    session = FakeSession(failure=TimeoutError())
    listing = provider(session)
    assert (await listing.page()).failure == Status.TEMPORARY_FAILURE
    session.failure = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await listing.page()


async def test_transport_middleware_blocks_implicit_retry():
    from aiohttp import ClientError, ServerDisconnectedError

    session = FakeSession({"items": []})
    assert (await provider(session).page()).checkpoint_may_advance
    (middleware,) = session.calls[0][1]["middlewares"]
    calls = 0

    async def disconnect(request):
        nonlocal calls
        calls += 1
        raise ServerDisconnectedError()

    with pytest.raises(ServerDisconnectedError):
        await middleware(None, disconnect)
    with pytest.raises(ClientError, match="request_budget_exhausted"):
        await middleware(None, disconnect)
    assert calls == 1

import asyncio
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from aiohttp import ClientConnectionError

from cats_channel.discovery.domain import Status
from cats_channel.discovery.youtube_api import YouTubeChannelResolver

CHANNEL = "UC" + "a" * 22
UPLOADS = "UU" + "a" * 22


class FakeSession:
    def __init__(self, payload=None, *, status=200, failure=None):
        self.payload = payload
        self.status = status
        self.failure = failure
        self.calls = []

    @asynccontextmanager
    async def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if self.failure is not None:
            raise self.failure

        async def chunks(size):
            data = json.dumps(self.payload).encode()
            for offset in range(0, len(data), size):
                yield data[offset : offset + size]

        yield SimpleNamespace(status=self.status, content=SimpleNamespace(iter_chunked=chunks))


def channel(handle="@newname"):
    return {
        "id": CHANNEL,
        "snippet": {"title": "Renamed channel", "customUrl": handle},
        "contentDetails": {"relatedPlaylists": {"uploads": UPLOADS}},
    }


@pytest.mark.parametrize(
    ("reference", "parameter"),
    [(CHANNEL, "id"), ("https://www.youtube.com/@NEWNAME/shorts", "forHandle")],
)
async def test_resolution_returns_stable_identity_and_uploads(reference, parameter):
    session = FakeSession({"items": [channel()]})
    result = await YouTubeChannelResolver(session, api_key="synthetic-key").resolve(reference)
    assert (result.status, result.channel_id, result.handle, result.uploads_playlist_id) == (
        Status.RESOLVED,
        CHANNEL,
        "@newname",
        UPLOADS,
    )
    [(url, request)] = session.calls
    assert url == "https://www.googleapis.com/youtube/v3/channels"
    assert request["params"][parameter] == (CHANNEL if parameter == "id" else "@newname")
    assert "key" not in request["params"]
    assert request["allow_redirects"] is False


@pytest.mark.parametrize(
    ("status", "payload", "expected"),
    [
        (200, {"items": []}, Status.UNAVAILABLE),
        (200, {"items": [channel(), channel()]}, Status.AMBIGUOUS),
        (200, {"items": [dict(channel(), id="UC" + "b" * 22)]}, Status.AMBIGUOUS),
        (200, {"items": ["malformed"]}, Status.TEMPORARY_FAILURE),
        pytest.param(200, "x" * 65536, Status.TEMPORARY_FAILURE, id="oversize"),
        (403, {"error": {"errors": [{"reason": "quotaExceeded"}]}}, Status.RATE_LIMITED),
        (403, {"error": {"message": "synthetic-key"}}, Status.CONFIGURATION_ERROR),
        (429, {}, Status.RATE_LIMITED),
        (503, {}, Status.TEMPORARY_FAILURE),
        (302, {}, Status.TEMPORARY_FAILURE),
    ],
)
async def test_failures_are_bounded_and_sanitized(status, payload, expected):
    session = FakeSession(payload, status=status)
    result = await YouTubeChannelResolver(session, api_key="synthetic-key").resolve(CHANNEL)
    assert result.status == expected
    assert result.channel_id is None
    assert "synthetic-key" not in repr(result)
    assert len(session.calls) == 1


async def test_rejects_handle_mismatch_and_arbitrary_url():
    session = FakeSession({"items": [channel()]})
    resolver = YouTubeChannelResolver(session, api_key="synthetic-key")
    assert (await resolver.resolve("@oldname")).status == Status.AMBIGUOUS
    assert (await resolver.resolve("https://example.com/@newname")).status == Status.INVALID_INPUT
    assert len(session.calls) == 1


@pytest.mark.parametrize("failure", [TimeoutError(), ClientConnectionError("synthetic-key")])
async def test_transport_failure_is_sanitized(failure):
    resolver = YouTubeChannelResolver(FakeSession(failure=failure), api_key="synthetic-key")
    assert (await resolver.resolve(CHANNEL)).status == Status.TEMPORARY_FAILURE


async def test_cancellation_propagates():
    session = FakeSession(failure=asyncio.CancelledError())
    with pytest.raises(asyncio.CancelledError):
        await YouTubeChannelResolver(session, api_key="synthetic-key").resolve(CHANNEL)

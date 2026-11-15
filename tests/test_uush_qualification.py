from contextlib import asynccontextmanager

import pytest
from test_youtube_channel_resolver import CHANNEL, FakeSession, channel
from test_youtube_playlist_provider import item

from cats_channel.discovery.uush_qualification import qualify_uush, review_sample

VIDEOS = tuple(f"{i:011d}" for i in range(20))


class Responses(FakeSession):
    def __init__(self, *responses):
        super().__init__()
        self.responses = iter(((200, {"items": [channel()]}), *responses))

    @asynccontextmanager
    async def get(self, url, **kwargs):
        self.status, self.payload = next(self.responses)
        async with super().get(url, **kwargs) as response:
            yield response


async def collect(session, *, pagination_expected=True):
    return await qualify_uush(
        session,
        api_key="fixture-key",
        reference=CHANNEL,
        expected_channel_id=CHANNEL,
        known_shorts=VIDEOS[:5],
        pagination_expected=pagination_expected,
    )


async def test_bounded_collection_and_separate_manual_evaluation():
    session = Responses(
        (200, {"items": [item(video) for video in VIDEOS[:10]], "nextPageToken": "private-1"}),
        (200, {"items": [item(video) for video in VIDEOS[10:]], "nextPageToken": "private-2"}),
    )
    result = await collect(session)
    assert result.outcome == "manual_review_pending"
    assert result.page_sizes == (10, 10) and result.continuation_seen
    assert result.calls == (("channels", 200), ("playlistItems", 200), ("playlistItems", 200))
    assert {VIDEOS[9], VIDEOS[10]} <= set(result.sample_ids)
    assert "private-" not in repr(result) and "fixture-key" not in repr(result)
    assert session.calls[2][1]["params"]["pageToken"] == "private-1"
    assert all(call[1]["params"]["maxResults"] == "10" for call in session.calls[1:])
    checked = dict.fromkeys(result.sample_ids, True)
    assert review_sample(result, checked).outcome == "pass"
    checked[result.sample_ids[0]] = False
    assert review_sample(result, checked).outcome == "fail"
    with pytest.raises(ValueError, match="sample_incomplete"):
        review_sample(result, {})
    assert len(session.calls) == 3


@pytest.mark.parametrize(
    ("response", "outcome", "reason"),
    [
        ((404, {}), "inconclusive", "playlist_unavailable"),
        ((200, {"items": []}), "fail", "empty_playlist_with_known_shorts"),
        ((200, {"items": [item(VIDEOS[0], owner="UC" + "z" * 22)]}), "fail", "uploader_mismatch"),
        ((200, {"items": [{}]}), "incomplete", "temporary_failure"),
        (
            (200, {"items": [item(video) for video in VIDEOS[:5]]}),
            "pagination_unqualified",
            "missing_distinct_second_page",
        ),
    ],
)
async def test_qualification_failures_do_not_retry(response, outcome, reason):
    session = Responses(response)
    result = await collect(session)
    assert (result.outcome, result.reason) == (outcome, reason)
    assert len(session.calls) == 2


async def test_rejects_cookie_enabled_session_before_any_request():
    from aiohttp import ClientSession

    async with ClientSession() as session:
        with pytest.raises(ValueError, match="requires_isolated_session"):
            await collect(session)


@pytest.mark.parametrize("second_page", [None, VIDEOS[:5], VIDEOS[5:6]])
async def test_optional_pagination_validates_observed_continuation(second_page):
    first = {"items": [item(video) for video in VIDEOS[:5]]}
    responses = [(200, first)]
    if second_page is not None:
        first["nextPageToken"] = "next"
        responses.append((200, {"items": [item(video) for video in second_page]}))
    session = Responses(*responses)
    result = await collect(session, pagination_expected=False)
    if second_page == VIDEOS[:5]:
        assert (result.outcome, result.reason) == (
            "pagination_unqualified",
            "missing_distinct_second_page",
        )
        with pytest.raises(ValueError, match="not_pending"):
            review_sample(result, dict.fromkeys(VIDEOS[:5], True))
    else:
        assert result.outcome == "manual_review_pending"
        if second_page:
            assert VIDEOS[5] in result.sample_ids
    assert len(session.calls) == (2 if second_page is None else 3)

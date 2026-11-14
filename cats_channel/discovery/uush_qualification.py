"""Bounded UUSH evidence collection and offline manual-sample evaluation."""

import re
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace

from aiohttp import ClientSession, DummyCookieJar

from .domain import Status, normalize
from .youtube_api import YouTubeChannelResolver
from .youtube_playlists import YouTubePlaylistProvider

_BASE = "https://www.googleapis.com/youtube/v3/"


@dataclass(frozen=True)
class Qualification:
    outcome: str
    reason: str
    calls: tuple[tuple[str, int | None], ...]
    page_sizes: tuple[int, ...] = ()
    continuation_seen: bool = False
    sample_ids: tuple[str, ...] = ()

    @property
    def reserved_quota_units(self) -> int:
        return len(self.calls)


class _QualificationTransport:
    def __init__(self, session):
        self.session = session
        self.calls = []

    @asynccontextmanager
    async def get(self, url, **kwargs):
        endpoint = url.removeprefix(_BASE)
        if url != _BASE + endpoint or endpoint not in {"channels", "playlistItems"}:
            raise ValueError("qualification_endpoint_rejected")
        if len(self.calls) >= 3:
            raise ValueError("qualification_request_budget_exhausted")
        self.calls.append((endpoint, None))
        async with self.session.get(url, **kwargs) as response:
            self.calls[-1] = (endpoint, response.status)
            yield response


async def qualify_uush(
    session,
    *,
    api_key: str,
    reference: str,
    expected_channel_id: str,
    known_shorts: tuple[str, ...],
    pagination_expected: bool = True,
) -> Qualification:
    """Use one resolution and at most two listing calls. Keep evidence in memory."""
    if (
        not re.fullmatch(r"UC[A-Za-z0-9_-]{22}", expected_channel_id)
        or len(known_shorts) != 5
        or len(set(known_shorts)) != 5
        or any(not re.fullmatch(r"[A-Za-z0-9_-]{11}", video) for video in known_shorts)
    ):
        raise ValueError("invalid_qualification_input")
    if isinstance(session, ClientSession) and (
        not isinstance(session.cookie_jar, DummyCookieJar)
        or session.trust_env
        or session.auth is not None
        or any(header in session.headers for header in ("Authorization", "Cookie"))
    ):
        raise ValueError("qualification_requires_isolated_session")
    reference = normalize(reference)
    transport = _QualificationTransport(session)
    pages = []
    continuation_seen = False

    def report(outcome, reason, sample=()):
        return Qualification(
            outcome,
            reason,
            tuple(transport.calls),
            tuple(page.items_examined or 0 for page in pages),
            continuation_seen,
            sample,
        )

    resolution = await YouTubeChannelResolver(transport, api_key=api_key).resolve(reference)
    if resolution.status == Status.AMBIGUOUS or (
        resolution.status == Status.RESOLVED and resolution.channel_id != expected_channel_id
    ):
        return report("fail", "channel_identity_mismatch")
    if resolution.status != Status.RESOLVED:
        return report("inconclusive", f"resolution_{resolution.status.value}")

    provider = YouTubePlaylistProvider(
        transport, api_key=api_key, channel_id=expected_channel_id, experimental_shorts=True
    )
    cursor = None
    for _ in range(2):
        page = await provider.page(cursor, limit=10)
        pages.append(page)
        if page.failure == Status.AMBIGUOUS:
            return report("fail", "uploader_mismatch")
        if page.failure == Status.UNAVAILABLE:
            return report("inconclusive", "playlist_unavailable")
        if not page.checkpoint_may_advance:
            reason = page.failure.value if page.failure else "partial_page"
            return report("incomplete", reason)
        if any(candidate.published_at is None for candidate in page.candidates):
            return report("incomplete", "publication_timestamp_missing")
        cursor = page.next_cursor
        if cursor is None:
            break
        continuation_seen = True

    first = tuple(candidate.video_id for candidate in pages[0].candidates)
    second = (
        tuple(candidate.video_id for candidate in pages[1].candidates) if len(pages) == 2 else ()
    )
    observed = tuple(dict.fromkeys(first + second))
    if not observed:
        return report("fail", "empty_playlist_with_known_shorts")
    second_only = next((video for video in second if video not in first), None)
    if (pagination_expected or continuation_seen) and (not first or second_only is None):
        return report("pagination_unqualified", "missing_distinct_second_page")
    if not set(known_shorts).issubset(observed):
        outcome = "incomplete" if cursor else "fail"
        return report(outcome, "known_shorts_not_in_sample")

    # Include both sides of the observed boundary before filling from the first page.
    boundary = (first[0], first[-1], second_only) if first and second_only else ()
    sample = tuple(dict.fromkeys(boundary + observed))[:5]
    return report("manual_review_pending", "shorts_tab_sample_required", sample)


def review_sample(evidence: Qualification, checked_sample: dict[str, bool]) -> Qualification:
    """Record independent manual checks without issuing additional API requests."""
    if evidence.outcome != "manual_review_pending":
        raise ValueError("qualification_not_pending_manual_review")
    if len(evidence.sample_ids) != 5 or set(checked_sample) != set(evidence.sample_ids):
        raise ValueError("qualification_sample_incomplete")
    if not all(checked_sample[video] is True for video in evidence.sample_ids):
        return replace(evidence, outcome="fail", reason="shorts_tab_sample_mismatch")
    return replace(evidence, outcome="pass", reason="sample_agrees")

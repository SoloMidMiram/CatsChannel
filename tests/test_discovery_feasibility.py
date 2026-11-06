"""In-memory contract simulations, not a provider or durable recovery implementation."""

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime

import pytest

from cats_channel.discovery.domain import Candidate, PageResult, Status

NOW = datetime(2026, 11, 6, tzinfo=UTC)
CHANNEL_A = "UC0o-_FwPhZS5Xr0XTmwqwkw"
CHANNEL_B = "UC" + "b" * 22


def candidate(number, channel=CHANNEL_A, title="fixture"):
    return Candidate(
        channel_id=channel,
        video_id=f"{number:011d}",
        observed_at=NOW,
        discovery_method="synthetic",
        title=title,
    )


@dataclass
class MemoryScan:
    channel_id: str
    rows: dict = field(default_factory=dict)
    cursor: str | None = None
    completed_watermark: datetime | None = None
    outcome: str = "running"
    failure: Status | None = None
    backlog: bool = True
    requests: list = field(default_factory=list)

    def run(self, pages, *, item_budget=30, page_budget=2, api_request_budget=30, expired=False):
        """Each synthetic page costs one request; actual API enrichment costs more."""
        seen_items = 0
        new_ids = []
        self.outcome, self.failure = "running", None
        index = 0
        while True:
            if expired or index >= min(page_budget, api_request_budget):
                self.outcome = "budget_exhausted"
                break
            if self.cursor not in pages:
                self.outcome = "partial"
                break
            self.requests.append(self.cursor)
            page = pages[self.cursor]
            index += 1
            if any(item.channel_id != self.channel_id for item in page.candidates):
                self.outcome, self.failure = "failed", Status.AMBIGUOUS
                break
            remaining = item_budget - seen_items
            for item in page.candidates[:remaining]:
                key = (item.provider, item.video_id)
                previous = self.rows.get(key)
                if previous is None:
                    new_ids.append(item.video_id)
                elif item.title is None:
                    item = replace(item, title=previous.title)
                self.rows[key] = item
            seen_items += len(page.candidates)
            if seen_items > item_budget:
                # Partial-page observations survive; its input cursor remains safe.
                self.outcome = "budget_exhausted"
                break
            if not page.checkpoint_may_advance:
                self.outcome, self.failure = page.state, page.failure
                break
            self.cursor = page.next_cursor
            if page.next_cursor is None:
                self.outcome, self.backlog = "completed", False
                self.completed_watermark = NOW
                return new_ids
        self.backlog = True
        return new_ids


def two_pages(channel=CHANNEL_A):
    return {
        None: PageResult((candidate(1, channel), candidate(2, channel)), "complete", "page-2"),
        "page-2": PageResult((candidate(3, channel), candidate(4, channel)), "complete"),
    }


def test_two_page_success_requires_terminal_evidence():
    scan = MemoryScan(CHANNEL_A)
    scan.run({None: two_pages()[None]})
    assert scan.cursor == "page-2" and scan.completed_watermark is None
    assert scan.outcome == "partial" and scan.backlog
    scan.run({"page-2": two_pages()["page-2"]})
    assert len(scan.rows) == 4 and scan.outcome == "completed"
    assert scan.completed_watermark == NOW and not scan.backlog


def test_failed_second_page_and_recovery_keep_safe_boundary():
    scan = MemoryScan(CHANNEL_A)
    failure = PageResult((), "failed", failure=Status.TEMPORARY_FAILURE)
    scan.run({None: two_pages()[None], "page-2": failure})
    assert len(scan.rows) == 2 and scan.cursor == "page-2"
    assert scan.failure == Status.TEMPORARY_FAILURE and scan.completed_watermark is None
    assert scan.backlog and scan.outcome == "failed"
    # Recreate the service view using only saved in-memory state.
    recovered = replace(scan, rows=scan.rows.copy(), requests=scan.requests.copy())
    recovered.run({"page-2": two_pages()["page-2"]})
    assert recovered.requests == [None, "page-2", "page-2"]
    assert len(recovered.rows) == 4 and recovered.outcome == "completed"
    assert recovered.run(two_pages()) == []


def test_channels_progress_independently_and_reject_wrong_identity():
    a, b = MemoryScan(CHANNEL_A), MemoryScan(CHANNEL_B)
    a.run(
        {None: two_pages()[None], "page-2": PageResult((), "failed", failure=Status.RATE_LIMITED)}
    )
    b.run(two_pages(CHANNEL_B))
    assert a.completed_watermark is None and len(a.rows) == 2
    assert b.outcome == "completed" and len(b.rows) == 4
    a.run(two_pages(CHANNEL_B))
    assert a.failure == Status.AMBIGUOUS and len(a.rows) == 2


def test_repeat_polling_reports_new_once_and_preserves_known_metadata():
    scan = MemoryScan(CHANNEL_A)
    assert len(scan.run(two_pages())) == 4
    scan.cursor = None
    repeated = PageResult((candidate(4, title=None), candidate(1), candidate(5)), "complete")
    assert scan.run({None: repeated}) == [candidate(5).video_id]
    assert scan.run({None: repeated}) == [] and len(scan.rows) == 5
    assert scan.rows[("youtube", candidate(4).video_id)].title == "fixture"
    # Absence/reordering does not prove deletion or authorize removing prior observations.
    assert ("youtube", candidate(2).video_id) in scan.rows


@pytest.mark.parametrize(
    "limits", [{"item_budget": 3}, {"page_budget": 1}, {"api_request_budget": 1}, {"expired": True}]
)
def test_exhausted_budget_never_marks_scan_complete(limits):
    scan = MemoryScan(CHANNEL_A)
    scan.run(two_pages(), **limits)
    assert scan.outcome == "budget_exhausted" and scan.backlog
    assert scan.completed_watermark is None
    assert len(scan.requests) <= min(
        limits.get("page_budget", 2), limits.get("api_request_budget", 30)
    )
    if limits.get("expired"):
        assert scan.requests == []


def test_expired_cursor_can_restart_with_overlap_without_duplicates():
    scan = MemoryScan(CHANNEL_A)
    scan.run({None: two_pages()[None]})
    scan.cursor = None  # Synthetic explicit expiry recovery, not provider expiry evidence.
    scan.run(two_pages())
    assert len(scan.rows) == 4 and scan.outcome == "completed"

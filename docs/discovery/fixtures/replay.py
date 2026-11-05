"""Replay sanitized research evidence against current DTOs without provider I/O."""

import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from cats_channel.discovery.domain import Candidate, PageResult, Status


def main():
    fixtures = Path(__file__).resolve().parent
    observation = json.loads((fixtures / "honey-observed.json").read_text(encoding="utf-8"))
    fields = observation["candidate"].copy()
    canonical_url = fields.pop("canonical_url")
    fields["observed_at"] = datetime.fromisoformat(fields["observed_at"])
    fields["evidence"] = tuple(fields["evidence"])
    candidate = Candidate(**fields)
    assert candidate.canonical_url == canonical_url
    assert candidate.duration_seconds is None and candidate.published_at is None
    assert candidate.classification == "shorts_tab"

    failed = json.loads((fixtures / "honey-failure.json").read_text(encoding="utf-8"))
    page_fields = failed["page"].copy()
    page_fields["candidates"] = tuple(page_fields["candidates"])
    page_fields["failure"] = Status(page_fields["failure"])
    assert not PageResult(**page_fields).checkpoint_may_advance

    # Synthetic protocol examples are deliberately separate from observed evidence.
    complete = PageResult((candidate,), "complete", next_cursor="synthetic-next-page")
    partial = PageResult((candidate,), "partial", failure=Status.TEMPORARY_FAILURE)
    assert complete.checkpoint_may_advance and complete.next_cursor is not None
    assert not partial.checkpoint_may_advance
    print("Replayed historical observation/failure and synthetic page boundaries.")


if __name__ == "__main__":
    main()

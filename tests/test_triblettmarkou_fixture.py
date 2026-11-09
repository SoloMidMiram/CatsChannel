"""Check the research fixtures without opening a browser or calling a provider."""

import json
from datetime import datetime
from pathlib import Path

from cats_channel.media import youtube_url

FIXTURES = Path(__file__).resolve().parents[1] / "docs" / "discovery" / "fixtures"


def fixture(kind):
    return json.loads((FIXTURES / f"triblettmarkou-{kind}.json").read_text(encoding="utf-8"))


def test_input_urls_normalize_to_distinct_video_ids():
    inputs = fixture("input")
    assert inputs["channel_page_url"] == "https://www.youtube.com/@TriblettMarkou/shorts"
    assert [v["requested_id"] for v in inputs["videos"]] == [
        "jrKzQg_-p3c",
        "CYby8efzWOc",
        "YWXVezN5T-k",
    ]
    for video in inputs["videos"]:
        assert youtube_url(video["requested_url"]) == video["canonical_url"]
        assert video["canonical_url"].endswith(f"?v={video['requested_id']}")


def test_blocked_preflight_preserves_unknowns_and_input_identity():
    inputs, result = fixture("input"), fixture("result")
    assert datetime.fromisoformat(result["observed_at"]).utcoffset().total_seconds() == 0
    assert result["source"]["page_url"] == inputs["channel_page_url"]
    assert result["source"]["channel_id"] is None
    assert result["verdict"] == "BLOCKED"
    assert result["controls"]["status"] == "blocked_preflight"
    assert result["controls"]["request_accounting"] == "request_budget_unverified"
    assert result["controls"]["youtube_navigations"] == 0
    assert result["controls"]["youtube_requests_attempted"] == 0
    assert result["tab"]["status"] == "not_run"
    assert result["tab"]["complete_listing"] is False
    observed_ids = set(result["tab"]["observed_video_ids"])
    supplied_ids = {v["requested_id"] for v in inputs["videos"]}
    assert set(result["tab"]["supplied_id_matches"]) == observed_ids & supplied_ids
    assert not observed_ids
    for requested, row in zip(inputs["videos"], result["videos"], strict=True):
        assert all(row[key] == value for key, value in requested.items())
        assert row["identity_status"] == row["metadata_status"] == "not_checked"
        assert row["shorts_tab_observed"] is None
        assert row["failure_reason"] == "blocked_preflight"
        for field, source in row["field_sources"].items():
            assert row[field] is source is None


def test_recorded_redirect_accounting_gap():
    result = fixture("result")
    preflight = result["preflight"]
    assert preflight["metadata_loaded"]
    assert preflight["initial_cookie_count"] == preflight["active_service_workers"] == 0
    assert preflight["attempted"] == preflight["completed"] + preflight["failed"]
    assert preflight["attempted"] - preflight["intercepted"] == 1
    assert preflight["blocked"] == len(preflight["blocked_resource_kinds"])
    assert preflight["unintercepted_request_kind"] == "redirect_target"
    assert not preflight["cdp_full_coverage_verified"]

from copy import deepcopy
from datetime import date
from pathlib import Path

from tools.project_context import (
    _local_locator_error,
    _sensitive_memory_locations,
    _validate_freshness,
    check_generated,
    load_context,
    render_overview,
    render_selection,
    select_records,
    validate_repository,
)

ROOT = Path(__file__).resolve().parents[1]


def test_repository_context_is_valid_and_generated_output_is_current():
    assert validate_repository(ROOT) == []
    assert check_generated(ROOT) == []

    _taxonomy, sources, records = load_context(ROOT)
    assert {source["kind"] for source in sources} >= {
        "conversation",
        "document",
        "code_revision",
        "pull_request",
        "issue",
        "test_result",
    }
    assert {record["kind"] for record in records} == {
        "fact",
        "decision",
        "task",
        "blocker",
        "proposal",
    }
    overview = (ROOT / "project-context" / "overview.md").read_text(encoding="utf-8")
    for section in (
        "## Goal",
        "## Current state",
        "## Recent changes",
        "## Unresolved questions",
        "## Next steps",
        "## Record index",
    ):
        assert section in overview


def test_selector_finds_runtime_decision_and_retains_audit_fields():
    _taxonomy, sources, records = load_context(ROOT)
    selected = select_records(
        records,
        sources,
        "Why are Windows and WSL virtual environments separate?",
        max_records=3,
    )
    assert selected[0][1]["id"] == "decision-014"

    rendered = render_selection(
        "Why are Windows and WSL virtual environments separate?",
        selected,
        sources,
        include_details=False,
        max_chars=1800,
    )
    assert "Status: implemented" in rendered
    assert "Freshness: stable" in rendered
    assert "Source: source-064" in rendered
    assert "Verified against:" in rendered
    assert len(rendered) <= 1800


def test_selector_keeps_proposal_distinct_from_implemented_decisions():
    _taxonomy, sources, records = load_context(ROOT)
    selected = select_records(records, sources, "semantic retrieval embeddings")
    proposal = next(record for _score, record in selected if record["id"] == "proposal-001")
    assert proposal["kind"] == "proposal"
    assert proposal["status"] == "proposed"


def test_selector_supports_categorical_kind_and_area_filters():
    _taxonomy, sources, records = load_context(ROOT)
    selected = select_records(
        records,
        sources,
        "shared media service validation",
        kinds={"decision"},
        areas={"architecture"},
    )
    assert selected
    assert all(record["kind"] == "decision" for _score, record in selected)
    assert all(record["area"] == "architecture" for _score, record in selected)


def test_selector_drops_superseded_record():
    _taxonomy, sources, records = load_context(ROOT)
    old = deepcopy(next(record for record in records if record["id"] == "fact-001"))
    old.update(
        id="fact-090",
        statement="Use the old context selection implementation.",
        tags=["context", "old", "selection"],
    )
    new = deepcopy(old)
    new.update(
        id="fact-091",
        statement="Use the replacement context selection implementation.",
        supersedes="fact-090",
    )
    selected = select_records([old, new], sources, "context selection implementation")
    assert [record["id"] for _score, record in selected] == ["fact-091"]


def test_overview_hides_replaced_claims_without_rewriting_evidence():
    taxonomy, sources, records = load_context(ROOT)
    old = deepcopy(next(record for record in records if record["id"] == "blocker-002"))
    resolved = deepcopy(old)
    resolved.update(id="blocker-099", status="resolved", supersedes=old["id"])

    overview = render_overview(ROOT, taxonomy, sources, [old, resolved])

    assert "**blocker-002**" not in overview
    assert "**blocker-099**" in overview
    assert old["status"] == "open"


def test_selector_deduplicates_after_ranking_so_fresher_record_wins():
    _taxonomy, sources, records = load_context(ROOT)
    older = deepcopy(next(record for record in records if record["id"] == "fact-001"))
    older.update(id="fact-090", freshness="stale")
    newer = deepcopy(older)
    newer.update(id="fact-091", freshness="current")

    selected = select_records([older, newer], sources, "cat video mission")

    assert [record["id"] for _score, record in selected] == ["fact-091"]


def test_context_budget_compresses_details_before_dropping_a_record():
    _taxonomy, sources, records = load_context(ROOT)
    selected = select_records(records, sources, "project memory generated narrative")
    rendered = render_selection(
        "project memory generated narrative",
        selected,
        sources,
        include_details=True,
        max_chars=500,
    )
    assert len(rendered) <= 500
    assert "- Statement:" in rendered
    assert "- Status:" in rendered
    assert "- Freshness:" in rendered
    assert "- Details:" not in rendered


def test_current_freshness_expires_without_reverification():
    taxonomy, _sources, _records = load_context(ROOT)
    errors: list[str] = []
    _validate_freshness(
        {"freshness": "current", "last_verified_at": "2026-10-16"},
        "fact-999",
        taxonomy,
        date(2026, 11, 16),
        errors,
    )
    assert errors == ["fact-999: current evidence expired 31 days after verification (limit 30)"]


def test_verification_date_cannot_claim_future_evidence():
    taxonomy, _sources, _records = load_context(ROOT)
    errors: list[str] = []
    _validate_freshness(
        {"freshness": "current", "last_verified_at": "2026-10-17"},
        "fact-999",
        taxonomy,
        date(2026, 10, 16),
        errors,
    )
    assert errors == ["fact-999: last_verified_at cannot be in the future"]


def test_memory_secret_scan_reports_location_without_value(tmp_path):
    evidence = tmp_path / "project-context" / "evidence"
    evidence.mkdir(parents=True)
    (evidence / "unsafe.md").write_text("BOT_TOKEN=1234567890:abcdefghijklmnop\n", encoding="utf-8")

    findings = _sensitive_memory_locations(tmp_path)

    assert findings == ["project-context/evidence/unsafe.md:1: secret-like assignment detected"]
    assert "1234567890" not in findings[0]


def test_local_evidence_cannot_escape_or_point_at_private_runtime_paths(tmp_path):
    assert _local_locator_error(tmp_path, "../../outside.txt") == (
        "local locator escapes the repository"
    )
    assert _local_locator_error(tmp_path, ".secrets/session.session") == (
        "local locator points at an excluded private/runtime path"
    )
    assert _local_locator_error(tmp_path, ".venv/lib/package.txt") == (
        "local locator points at an excluded private/runtime path"
    )
    assert _local_locator_error(tmp_path, "docs/decision.md") is None

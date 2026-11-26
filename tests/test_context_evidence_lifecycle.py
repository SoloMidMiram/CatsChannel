"""Deterministic evidence lifecycle and receipt integrity regressions."""

import hashlib
import json
from copy import deepcopy
from datetime import date
from pathlib import Path

import pytest

from tools import context_render, context_store, project_context

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "freshness,as_of,expired",
    [
        ("current", date(2026, 11, 25), False),
        ("current", date(2026, 11, 26), True),
        ("historical", date(2030, 1, 1), False),
        ("stable", date(2030, 1, 1), False),
    ],
)
def test_freshness_boundary_replay(freshness, as_of, expired):
    taxonomy, _, _ = context_store.load_context(ROOT)
    errors = []
    context_store._validate_freshness(
        {"freshness": freshness, "last_verified_at": "2026-10-26"},
        "fact-999",
        taxonomy,
        as_of,
        errors,
    )
    assert bool(errors) == expired
    if expired:
        assert "31 days" in errors[0] and "limit 30" in errors[0]


def test_cli_injects_explicit_date_but_defaults_to_real_clock(monkeypatch):
    observed = []
    monkeypatch.setattr(
        project_context,
        "validate_repository",
        lambda root, today=None: observed.append(today) or [],
    )
    assert project_context.main(["--as-of", "2026-11-26", "validate"]) == 0
    assert project_context.main(["validate"]) == 0
    assert observed == [date(2026, 11, 26), None]


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_receipt_digest_detects_tampering_across_platform_newlines(tmp_path, newline):
    taxonomy, sources, _ = context_store.load_context(ROOT)
    receipt = tmp_path / "receipt.md"
    receipt.write_bytes(("original" + newline).encode())
    source = deepcopy(sources[0])
    source.update(
        kind="document",
        locator="receipt.md",
        freshness="historical",
        content_sha256=hashlib.sha256(b"original\n").hexdigest(),
    )
    assert context_store._validate_source(source, tmp_path, taxonomy, date(2026, 11, 26)) == []
    receipt.write_text("tampered\n", encoding="utf-8")
    assert any(
        "content_sha256 mismatch" in x
        for x in context_store._validate_source(source, tmp_path, taxonomy, date(2026, 11, 26))
    )


@pytest.mark.parametrize("freshness", ["stale", "unknown"])
def test_current_record_rejects_unsubstantiated_dependencies(monkeypatch, freshness):
    taxonomy, sources, records = deepcopy(context_store.load_context(ROOT))
    record = next(x for x in records if x["id"] == "fact-089")
    source = next(x for x in sources if x["id"] == record["source"])
    source["freshness"] = freshness
    monkeypatch.setattr(context_store, "load_context", lambda root: (taxonomy, sources, records))
    assert any(
        "fact-089: current claim depends on source-193" in x
        for x in context_store.validate_repository(ROOT, today=date(2026, 11, 26))
    )


def test_reconciliation_preserves_ids_claims_and_unique_successors():
    _, sources, records = context_store.load_context(ROOT)
    ledger = json.loads(
        (ROOT / "project-context/evidence/act-p2-inventory-2026-11-26.json").read_text(
            encoding="utf-8"
        )
    )
    entries = ledger["expired_entries"]
    assert len(entries) == 166
    current = {x["id"]: x for x in sources + records}
    assert len(current) == len(sources) + len(records)
    assert set(ledger["baseline_record_ids"]) <= current.keys()
    assert set(ledger["baseline_source_ids"]) <= current.keys()
    for entry in entries:
        old = entry["original"]
        assert old["id"] in current
        if entry["type"] == "records":
            assert current[old["id"]]["statement"] == old["statement"]
        assert entry["justification"] and entry["supporting_evidence"]
    by_id = {x["id"]: x for x in records}
    assert by_id["fact-028"]["status"] == "superseded"
    assert by_id["fact-028"]["freshness"] == "historical"
    assert by_id["fact-088"]["supersedes"] == "fact-028"
    assert "October 22, 2026" in by_id["fact-088"]["statement"]
    predecessors = [x["supersedes"] for x in records if x["supersedes"]]
    assert len(predecessors) == len(set(predecessors))


@pytest.mark.parametrize(
    "field,value,diagnostic",
    [
        ("source", "source-999", "not cataloged"),
        ("verified_against", ["source-999"], "unknown verification sources"),
        ("statement", "bot_token=synthetic-sensitive-sentinel", "appears to contain a secret"),
    ],
)
def test_invalid_provenance_and_sensitive_claims_remain_rejected(field, value, diagnostic):
    taxonomy, sources, records = context_store.load_context(ROOT)
    record = deepcopy(records[0])
    record[field] = value
    errors = context_store._validate_record(
        record, {s["id"] for s in sources}, taxonomy, date(2026, 11, 26)
    )
    assert any(diagnostic in error for error in errors)


def test_generation_is_idempotent_and_retains_record_index(tmp_path, monkeypatch):
    context = context_store.load_context(ROOT)
    monkeypatch.setattr(context_render, "load_context", lambda root: context)
    first = context_render.write_generated(tmp_path)
    before = {path: path.read_bytes() for path in first}
    second = context_render.write_generated(tmp_path)
    assert before == {path: path.read_bytes() for path in second}
    assert context_render.check_generated(tmp_path) == []


def test_malformed_source_id_produces_diagnostic_not_dependency_index_crash(monkeypatch):
    taxonomy, sources, records = deepcopy(context_store.load_context(ROOT))
    sources[0]["id"] = ["invalid-source-id"]
    monkeypatch.setattr(context_store, "load_context", lambda root: (taxonomy, sources, records))
    assert any("invalid source ID" in error for error in context_store.validate_repository(ROOT))


@pytest.mark.parametrize("invalid_freshness", [[], {}])
def test_malformed_dependency_freshness_returns_diagnostic(monkeypatch, invalid_freshness):
    taxonomy, sources, records = deepcopy(context_store.load_context(ROOT))
    next(source for source in sources if source["id"] == "source-193")["freshness"] = (
        invalid_freshness
    )
    monkeypatch.setattr(context_store, "load_context", lambda root: (taxonomy, sources, records))
    assert any(
        "source-193: unknown freshness" in error
        for error in context_store.validate_repository(ROOT)
    )

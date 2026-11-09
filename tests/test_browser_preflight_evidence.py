"""Validate the saved MCP run. The executable browser regression runs in MCP."""

import json
from pathlib import Path

FIXTURE = (
    Path(__file__).resolve().parents[1] / "docs/discovery/fixtures/browser-cdp-preflight-v2.json"
)


def test_recorded_policy_cases_have_independent_evidence():
    evidence = json.loads(FIXTURE.read_text(encoding="utf-8"))
    cases = {row["name"]: row for row in evidence["reports"]}
    assert len(cases) == len(evidence["reports"]) == 6
    redirects = cases["redirects"]["decisions"]
    for path in ("/forbidden.mp4", "/cross-forbidden.mp4"):
        decision = next(row for row in redirects if row["url"].endswith(path))
        assert decision["reason"] == "not_allowlisted"
        assert decision["beforeAdmissionCap"]
    assert cases["redirects"]["scriptResult"] == "metadata-ok"
    for path in ("/thumbnail.png", "/captions.vtt", "/media.mp4"):
        decision = next(row for row in cases["resources"]["decisions"] if row["url"].endswith(path))
        assert decision["reason"] == "not_allowlisted"
        assert decision["beforeAdmissionCap"]
    assert evidence["checks"]["admissionCap"]
    assert cases["cancellation"]["cancelled"] == 1
    assert cases["cancellation"]["pendingAtClose"] == 0
    assert all(case["contextClosed"] and not case["failures"] for case in cases.values())


def test_recorded_coverage_gaps_keep_live_gate_blocked():
    evidence = json.loads(FIXTURE.read_text(encoding="utf-8"))
    cases = {row["name"]: row for row in evidence["reports"]}
    assert cases["attempt_cap"]["cdpAttempts"] > cases["attempt_cap"]["attemptCap"]
    assert cases["attempt_cap"]["stoppedAtAttemptCap"]
    assert any(url.endswith("/popup") for url in cases["child_targets"]["uncontrolledObserved"])
    assert not evidence["checks"]["strictAttemptCeiling"]
    assert not evidence["checks"]["childTargetCoverage"]
    assert evidence["liveQualification"] == "BLOCKED"

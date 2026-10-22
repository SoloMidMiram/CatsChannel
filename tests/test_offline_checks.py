import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from tools import context_render, project_context, regress
from tools.context_store import _local_locator_error, validate_repository
from tools.log_checks import audit_log, audit_records


def failure():
    return {
        "event": "bot_publication_failure",
        "level": "error",
        "correlation_id": "c1",
        "operation": "pilot_publish",
        "code": "publication_not_eligible",
    }


def completion(**changes):
    record = {
        "event": "bot_operation_finished",
        "correlation_id": "c1",
        "operation": "pilot_publish",
        "outcome": "error",
        "error_category": "publication_not_eligible",
    }
    return record | changes


@pytest.mark.parametrize("reverse", [False, True])
def test_log_audit_accepts_failure_after_completion_and_reports_error_events(reverse):
    records = [failure(), completion()]
    if reverse:
        records.reverse()
    result = audit_records(list(enumerate(records, 1)))
    assert result["status"] == "pass"  # Contract consistency, not application success.
    assert result["error_events"] == 1


@pytest.mark.parametrize(
    "change,category",
    [
        ({"outcome": "success"}, "failure_logged_as_success"),
        ({"error_category": "internal_error"}, "failure_category_mismatch"),
        ({"publication_state": "confirmed"}, "publication_state_mismatch"),
        ({"disposition": "created"}, "intake_disposition_mismatch"),
    ],
)
def test_audit_catches_misleading_completion(change, category):
    result = audit_records([(1, failure()), (2, completion(**change))])
    assert category in {issue["category"] for issue in result["issues"]}


def test_audit_distinguishes_incomplete_window_and_duplicate_completion():
    assert audit_records([(1, failure())])["status"] == "fail"
    assert audit_records([(1, failure())], allow_incomplete=True)["status"] == "pass"
    success = completion(outcome="success", error_category=None)
    result = audit_records([(1, success), (2, success)])
    assert result["issues"] == [{"line": 2, "category": "duplicate_completion"}]


def test_error_completion_requires_failure_unless_window_is_incomplete():
    orphan = [(7, completion())]
    assert audit_records(orphan)["issues"] == [
        {"line": 7, "category": "error_completion_without_failure"}
    ]
    assert audit_records(orphan, allow_incomplete=True)["status"] == "pass"
    assert (
        audit_records([(1, completion(outcome="success", error_category=None))])["status"] == "pass"
    )


@pytest.mark.parametrize("reverse", [False, True])
def test_unrelated_failure_does_not_satisfy_error_completion(reverse):
    events = [failure() | {"correlation_id": "other"}, completion()]
    if reverse:
        events.reverse()
    result = audit_records(list(enumerate(events, 1)))
    assert {item["category"] for item in result["issues"]} == {
        "failure_without_completion",
        "error_completion_without_failure",
    }


def test_incomplete_policy_does_not_allow_mismatched_correlated_records():
    result = audit_records(
        [(1, completion(error_category="internal_error")), (2, failure())],
        allow_incomplete=True,
    )
    assert result["issues"] == [{"line": 1, "category": "failure_category_mismatch"}]


def test_polling_counts_reset_but_cannot_silently_skip():
    def poll(attempt):
        return {
            "event": "bot_polling_failure",
            "analysis": {
                "phase": "bot_api_get_updates",
                "operation_attempts": attempt,
                "automatic_retries": attempt - 1,
            },
        }

    assert audit_records(list(enumerate([poll(1), poll(2), poll(1)], 1)))["status"] == "pass"
    result = audit_records([(1, poll(1)), (2, poll(3))])
    assert result["issues"] == [{"line": 2, "category": "polling_counter_discontinuous"}]
    record = poll(True)
    assert audit_records([(1, record)])["status"] == "fail"


@pytest.mark.parametrize(
    "value", [[], {"event": []}, {"event": "bot_polling_failure", "analysis": []}]
)
def test_malformed_log_shapes_fail_without_crashing(tmp_path, value):
    path = tmp_path / "input.jsonl"
    path.write_text(json.dumps(value), encoding="utf-8")
    assert audit_log(path)["status"] == "fail"


def test_log_values_never_appear_in_audit_errors(tmp_path):
    path = tmp_path / "input.jsonl"
    path.write_text(json.dumps(completion(bot_token="PRIVATE_SENTINEL")), encoding="utf-8")
    result = audit_log(path)
    assert result["status"] == "fail"
    assert "PRIVATE_SENTINEL" not in json.dumps(result)
    path.write_bytes(b"\xffPRIVATE_SENTINEL")
    assert "PRIVATE_SENTINEL" not in json.dumps(audit_log(path))


def test_empty_missing_and_overlong_logs_are_not_success(tmp_path):
    path = tmp_path / "input.jsonl"
    assert audit_log(path)["status"] == "fail"
    path.write_text("", encoding="utf-8")
    assert audit_log(path)["status"] == "fail"
    path.write_bytes(b"x" * (256 * 1024 + 1))
    assert audit_log(path)["issues"][0]["category"] == "log_limit"


def test_repeat_failure_cannot_be_erased_by_later_success(tmp_path):
    codes = iter([1, 0, 0])

    def runner(command, **kwargs):
        assert command[:2] == [sys.executable, "-m"]
        assert kwargs["timeout"] == 5
        kwargs["stderr"].write(b"LOCAL_PRIVATE_OUTPUT")
        return SimpleNamespace(returncode=next(codes))

    result = regress.run_checks(tmp_path, "context", 3, 5, runner=runner)
    assert result["status"] == "fail"
    assert [run["exit_code"] for run in result["runs"]] == [1, 0, 0]
    assert "LOCAL_PRIVATE_OUTPUT" not in json.dumps(result)
    report = Path(result["report"])
    assert json.loads(report.read_text())["status"] == "fail"
    assert (report.parent / "1.stderr.txt").read_text() == "LOCAL_PRIVATE_OUTPUT"
    assert not report.with_suffix(".tmp").exists()


@pytest.mark.parametrize(
    "error,category",
    [
        (subprocess.TimeoutExpired("private", 5), "timeout"),
        (OSError("private"), "process_start_failed"),
        (KeyboardInterrupt(), "interrupted"),
        (regress.ProcessCleanupError(), "process_cleanup_unconfirmed"),
    ],
)
def test_runner_records_errors_and_stops_on_unconfirmed_cleanup(tmp_path, error, category):
    def runner(*args, **kwargs):
        raise error

    result = regress.run_checks(tmp_path, "context", 2, 5, runner=runner)
    assert result["status"] == "fail"
    assert result["runs"][0]["category"] == category
    assert len(result["runs"]) == (
        1 if category in {"interrupted", "process_cleanup_unconfirmed"} else 2
    )
    assert "private" not in json.dumps(result)


def test_report_stays_running_between_successful_repetitions(tmp_path):
    def runner(*args, **kwargs):
        report_path = next((tmp_path / ".runtime/regress").glob("*/report.json"))
        assert json.loads(report_path.read_text())["status"] == "running"
        return SimpleNamespace(returncode=0)

    assert regress.run_checks(tmp_path, "context", 2, 5, runner=runner)["status"] == "pass"


def test_log_failure_makes_successful_regressions_fail(tmp_path):
    result = regress.run_checks(
        tmp_path,
        "context",
        1,
        5,
        log=tmp_path / "missing",
        runner=lambda *a, **k: SimpleNamespace(returncode=0),
    )
    assert result["status"] == "fail"


@pytest.mark.parametrize("repeat,timeout", [(0, 5), (11, 5), (1, 0), (1, 601)])
def test_runner_rejects_unbounded_invocations(tmp_path, repeat, timeout):
    with pytest.raises(ValueError):
        regress.run_checks(tmp_path, "context", repeat, timeout)
    assert not (tmp_path / ".runtime").exists()


def test_generator_preserves_previous_file_on_replace_failure(tmp_path, monkeypatch):
    path = tmp_path / "project-context/overview.md"
    path.parent.mkdir()
    path.write_text("previous", encoding="utf-8")
    monkeypatch.setattr(
        context_render, "generated_outputs", lambda _: {Path("project-context/overview.md"): "next"}
    )

    def fail(*args):
        raise PermissionError("PRIVATE_SENTINEL")

    monkeypatch.setattr(context_render.os, "replace", fail)
    with pytest.raises(PermissionError):
        context_render.write_generated(tmp_path)
    assert path.read_text() == "previous"
    assert list(path.parent.glob("*.tmp")) == []


def test_context_cli_reports_io_error_without_exception_body(monkeypatch, capsys):
    monkeypatch.setattr(
        project_context, "_run", lambda _: (_ for _ in ()).throw(OSError("PRIVATE_SENTINEL"))
    )
    assert project_context.main([]) == 1
    assert capsys.readouterr().err == "ERROR: context_io_or_data_error\n"


def test_bad_unicode_context_and_private_locators_fail_safely(tmp_path):
    context = tmp_path / "project-context"
    context.mkdir()
    (context / "taxonomy.yaml").write_bytes(b"\xffPRIVATE_SENTINEL")
    errors = validate_repository(tmp_path)
    assert errors and "PRIVATE_SENTINEL" not in str(errors)
    assert _local_locator_error(tmp_path, ".runtime/pilot.jsonl")
    assert _local_locator_error(tmp_path, "C:\\private\\session.session")


@pytest.mark.parametrize(
    "interruption", [subprocess.TimeoutExpired("test", 5), KeyboardInterrupt()]
)
def test_owned_test_process_group_is_stopped_and_reaped(tmp_path, monkeypatch, interruption):
    process = Mock(pid=12345)
    process.wait.side_effect = [interruption, 0]
    process.poll.return_value = None
    popen = Mock(return_value=process)
    monkeypatch.setattr(regress.subprocess, "Popen", popen)
    kill = Mock()
    if os.name == "nt":
        monkeypatch.setattr(regress.subprocess, "run", kill)
    else:
        monkeypatch.setattr(regress.os, "killpg", kill)
    with pytest.raises(type(interruption)):
        regress._run_command(
            ["test"], cwd=tmp_path, stdout=None, stderr=None, timeout=5, check=False
        )
    kill.assert_called_once()
    process.kill.assert_called_once()
    assert process.wait.call_count == 2
    if os.name == "nt":
        assert popen.call_args.kwargs["creationflags"] == subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        assert popen.call_args.kwargs["start_new_session"] is True


def test_cli_log_audit_exit_code_and_json_are_stable(tmp_path, capsys):
    path = tmp_path / "events.jsonl"
    path.write_text(json.dumps(failure()) + "\n", encoding="utf-8")
    assert regress.main(["logs", str(path)]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "fail"
    assert regress.main(["logs", str(path), "--allow-incomplete"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "pass"

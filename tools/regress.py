"""Repeat offline regression profiles and audit sanitized logs without hiding failures."""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.log_checks import audit_log

ROOT = Path(__file__).resolve().parents[1]
PROFILES = {
    "context": ["tests/test_project_context.py", "tests/test_offline_checks.py"],
    "lifecycle": [
        "tests/test_bot_transport.py",
        "tests/test_bot_lifecycle.py",
        "tests/test_aiogram_publisher.py",
        "tests/test_bot_submission_intake.py",
        "tests/test_telethon_connection.py",
    ],
    "all": [],
}


class ProcessCleanupError(RuntimeError):
    """An owned test process tree could not be confirmed terminated."""


def _run_command(command: list[str], *, cwd: Path, stdout, stderr, timeout: int, check: bool):
    """Own a test-process group and reap it on timeout or operator interruption."""
    options = (
        {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
        if os.name == "nt"
        else {"start_new_session": True}
    )
    process = subprocess.Popen(command, cwd=cwd, stdout=stdout, stderr=stderr, **options)
    try:
        code = process.wait(timeout=timeout)
    except (subprocess.TimeoutExpired, KeyboardInterrupt):
        cleanup_failed = False
        try:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=10,
                    check=True,
                )
            else:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        except (OSError, subprocess.SubprocessError):
            cleanup_failed = True
        finally:
            try:
                if process.poll() is None:
                    process.kill()
                process.wait(timeout=10)
            except (OSError, subprocess.SubprocessError):
                cleanup_failed = True
        if cleanup_failed:
            raise ProcessCleanupError from None
        raise
    return subprocess.CompletedProcess(command, code)


def _save_report(path: Path, report: dict) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def run_checks(
    root: Path,
    profile: str,
    repeat: int,
    timeout: int,
    *,
    log: Path | None = None,
    allow_incomplete: bool = False,
    runner=None,
) -> dict:
    """Every repetition is recorded; a later success cannot erase a failure."""
    if profile not in PROFILES or not 1 <= repeat <= 10 or not 5 <= timeout <= 600:
        raise ValueError("invalid regression bounds")
    runner = runner or _run_command
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]
    output = root / ".runtime" / "regress" / run_id
    output.mkdir(parents=True)
    report = {
        "status": "running",
        "profile": profile,
        "requested_runs": repeat,
        "runs": [],
        "report": str(output / "report.json"),
    }
    _save_report(output / "report.json", report)
    command = [sys.executable, "-m", "pytest", "--capture=sys", "-q", *PROFILES[profile]]
    interrupted = False
    failed = False
    for index in range(1, repeat + 1):
        started = time.monotonic()
        category = "passed"
        code = None
        # Raw test output stays in ignored local files, never in a shared summary.
        with (
            (output / f"{index}.stdout.txt").open("wb") as stdout,
            (output / f"{index}.stderr.txt").open("wb") as stderr,
        ):
            try:
                completed = runner(
                    command,
                    cwd=root,
                    stdout=stdout,
                    stderr=stderr,
                    timeout=timeout,
                    check=False,
                )
                code = completed.returncode
                if code != 0:
                    category = "tests_failed"
            except subprocess.TimeoutExpired:
                category = "timeout"
            except OSError:
                category = "process_start_failed"
            except ProcessCleanupError:
                category = "process_cleanup_unconfirmed"
                interrupted = True
            except KeyboardInterrupt:
                category = "interrupted"
                interrupted = True
        report["runs"].append(
            {
                "iteration": index,
                "category": category,
                "exit_code": code,
                "duration_ms": round((time.monotonic() - started) * 1000),
            }
        )
        failed = failed or category != "passed"
        report["status"] = "fail" if failed else ("pass" if index == repeat else "running")
        # Persist after each completed/failed invocation, not just at the end.
        _save_report(output / "report.json", report)
        if interrupted:
            break
    if log is not None:
        report["log_audit"] = audit_log(log, allow_incomplete=allow_incomplete)
        if report["log_audit"]["status"] != "pass":
            report["status"] = "fail"
    _save_report(output / "report.json", report)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest="action", required=True)
    run = actions.add_parser("run")
    run.add_argument("--profile", choices=PROFILES, default="context")
    run.add_argument("--repeat", type=int, default=1)
    run.add_argument("--timeout", type=int, default=180)
    run.add_argument("--log", type=Path)
    audit = actions.add_parser("logs")
    audit.add_argument("path", type=Path)
    for action in (run, audit):
        action.add_argument("--allow-incomplete", action="store_true")
    args = parser.parse_args(argv)
    if args.action == "run" and (not 1 <= args.repeat <= 10 or not 5 <= args.timeout <= 600):
        parser.error("repeat must be 1..10 and timeout 5..600 seconds")
    try:
        if args.action == "logs":
            report = audit_log(args.path, allow_incomplete=args.allow_incomplete)
        else:
            report = run_checks(
                ROOT,
                args.profile,
                args.repeat,
                args.timeout,
                log=args.log,
                allow_incomplete=args.allow_incomplete,
            )
    except OSError:
        report = {"status": "fail", "category": "report_io_failed"}
    print(json.dumps(report, indent=2))
    if any(run["category"] == "interrupted" for run in report.get("runs", [])):
        return 130
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())

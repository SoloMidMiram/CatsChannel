"""Offline checks for sanitized CatsChannel JSONL diagnostic contracts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

MAX_BYTES = 20 * 1024 * 1024
MAX_LINE = 256 * 1024
_FAILURES = {
    "bot_intake_failure",
    "bot_publication_failure",
    "bot_media_failure",
    "bot_upload_failure",
    "bot_publish_failure",
    "bot_unexpected_failure",
}
_PRIVATE_KEYS = {
    "bot_token",
    "api_hash",
    "authorization",
    "password",
    "cookie",
    "session_string",
    "caption",
    "file_id",
    "file_unique_id",
    "message_text",
    "proxy_url",
    "token",
    "text",
    "payload",
    "chat_id",
    "message_id",
}


def _has_private_fields(value: Any, depth: int = 0) -> bool:
    if depth > 32:
        return True
    if isinstance(value, dict):
        return any(
            str(key).lower() in _PRIVATE_KEYS or _has_private_fields(item, depth + 1)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_has_private_fields(item, depth + 1) for item in value)
    return False


def audit_records(records: list[tuple[int, dict]], *, allow_incomplete: bool = False) -> dict:
    """Return categories/line numbers only; never echo input values or payloads."""
    issues: list[dict] = []
    failures: dict[tuple[str, str], list[tuple[int, dict]]] = {}
    completions: dict[tuple[str, str], tuple[int, dict]] = {}
    checked = 0
    error_events = 0
    polling_attempt = 0

    def issue(line: int, category: str) -> None:
        issues.append({"line": line, "category": category})

    for line, record in records:
        if _has_private_fields(record):
            issue(line, "private_payload_field")
        event = record.get("event")
        if not isinstance(event, str):
            issue(line, "event_missing_or_invalid")
            continue
        if record.get("level") == "error":
            error_events += 1
        if event == "bot_polling_failure":
            checked += 1
            analysis = record.get("analysis")
            if not isinstance(analysis, dict):
                issue(line, "polling_analysis_missing")
                continue
            attempt = analysis.get("operation_attempts")
            retry = analysis.get("automatic_retries")
            if (
                type(attempt) is not int
                or attempt < 1
                or type(retry) is not int
                or retry != attempt - 1
                or analysis.get("phase") != "bot_api_get_updates"
            ):
                issue(line, "polling_counter_or_phase_invalid")
            elif polling_attempt and attempt not in {1, polling_attempt + 1}:
                issue(line, "polling_counter_discontinuous")
            if type(attempt) is int:
                polling_attempt = attempt
        elif event in _FAILURES or event == "bot_operation_finished":
            checked += 1
            correlation = record.get("correlation_id")
            operation = record.get("operation")
            if (
                not isinstance(correlation, str)
                or not correlation
                or not isinstance(operation, str)
            ):
                issue(line, "operation_identity_missing")
                continue
            key = (correlation, operation)
            if event in _FAILURES:
                if not isinstance(record.get("code"), str) or not record["code"]:
                    issue(line, "failure_category_missing")
                failures.setdefault(key, []).append((line, record))
            elif key in completions:
                issue(line, "duplicate_completion")
            else:
                completions[key] = (line, record)
                if not isinstance(record.get("outcome"), str):
                    issue(line, "completion_outcome_invalid")
                state = record.get("publication_state")
                if state is not None and state != record.get("outcome"):
                    issue(line, "publication_state_mismatch")
                disposition = record.get("disposition")
                if disposition is not None and record.get("outcome") != f"pending_{disposition}":
                    issue(line, "intake_disposition_mismatch")
        elif event in {"bot_startup_retry", "bot_lifecycle_failure", "cli_failure"}:
            checked += 1
            analysis = record.get("analysis")
            if not isinstance(analysis, dict) or not isinstance(analysis.get("phase"), str):
                issue(line, "failure_phase_missing")

    for key, errors in failures.items():
        completion = completions.get(key)
        if completion is None:
            if not allow_incomplete:
                issue(errors[0][0], "failure_without_completion")
            continue
        line, finished = completion
        if finished.get("outcome") in (None, "success", "confirmed"):
            issue(line, "failure_logged_as_success")
        if any(error.get("code") != finished.get("error_category") for _, error in errors):
            issue(line, "failure_category_mismatch")
    if checked == 0:
        issue(0, "no_supported_events")
    return {
        "status": "fail" if issues else "pass",
        "events_checked": checked,
        "error_events": error_events,
        "issues": issues,
    }


def audit_log(path: Path, *, allow_incomplete: bool = False) -> dict:
    records = []
    size = 0
    try:
        with path.open("rb") as stream:
            line = 0
            while raw := stream.readline(MAX_LINE + 1):
                line += 1
                size += len(raw)
                if len(raw) > MAX_LINE or size > MAX_BYTES:
                    return {"status": "fail", "issues": [{"line": line, "category": "log_limit"}]}
                if not raw.strip():
                    continue
                try:
                    record = json.loads(raw.decode("utf-8"))
                except (ValueError, UnicodeError, RecursionError):
                    return {
                        "status": "fail",
                        "issues": [{"line": line, "category": "invalid_json_record"}],
                    }
                if not isinstance(record, dict):
                    return {
                        "status": "fail",
                        "issues": [{"line": line, "category": "invalid_json_record"}],
                    }
                records.append((line, record))
    except OSError:
        return {"status": "fail", "issues": [{"line": 0, "category": "log_read_failed"}]}
    return audit_records(records, allow_incomplete=allow_incomplete)

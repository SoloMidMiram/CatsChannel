"""Deterministic error classification and secret-safe structured logging."""

from __future__ import annotations

import json
import logging
import re
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass(frozen=True)
class DiagnosticRule:
    """One ordered rule in an auditable regex classifier."""

    code: str
    category: str
    phase: str
    confidence: str
    patterns: tuple[re.Pattern[str], ...]


def diagnostic_rule(
    code: str,
    category: str,
    phase: str,
    confidence: str,
    *patterns: str,
) -> DiagnosticRule:
    return DiagnosticRule(
        code=code,
        category=category,
        phase=phase,
        confidence=confidence,
        patterns=tuple(re.compile(pattern, re.IGNORECASE) for pattern in patterns),
    )


def matching_rules(
    values: Iterable[str], rules: Sequence[DiagnosticRule]
) -> tuple[DiagnosticRule, ...]:
    """Return every matching rule once, preserving explicit rule priority."""
    materialized = tuple(values)
    return tuple(
        rule
        for rule in rules
        if any(pattern.search(value) for pattern in rule.patterns for value in materialized)
    )


def exception_chain(error: BaseException, *, max_depth: int = 8) -> tuple[tuple[str, ...], bool]:
    """Walk explicit/implicit causes without messages, cycles, or unbounded chains."""
    names: list[str] = []
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and len(names) < max_depth and id(current) not in seen:
        seen.add(id(current))
        names.append(type(current).__name__)
        next_error = current.__cause__
        if next_error is None and not current.__suppress_context__:
            # Context is useful for wrappers, but causes always take precedence.
            next_error = current.__context__
        current = next_error
    truncated = current is not None
    return tuple(names), truncated


def classify_exception(
    error: BaseException,
    rules: Sequence[DiagnosticRule],
    *,
    phase: str,
    default_code: str,
    default_category: str,
) -> tuple[str, dict[str, object]]:
    """Classify an exception chain using deterministic ordered regex rules."""
    exception_types, chain_truncated = exception_chain(error)
    matches = matching_rules(exception_types, rules)
    primary = matches[0] if matches else None
    code = primary.code if primary else default_code
    return code, {
        "primary": code,
        "category": primary.category if primary else default_category,
        "phase": phase,
        "confidence": primary.confidence if primary else "low",
        "signals": list(dict.fromkeys(rule.code for rule in matches)),
        "matched_line_scope": "exception",
        "exception_types": list(exception_types),
        "exception_chain_truncated": chain_truncated,
        "raw_log_included": False,
    }


_TOKEN = re.compile(r"[A-Za-z0-9_.:-]{1,80}\Z")
_ANALYSIS_TOKEN_FIELDS = {
    "primary",
    "category",
    "phase",
    "confidence",
    "matched_line_scope",
}
_ANALYSIS_LIST_FIELDS = {"signals", "exception_types", "http_statuses"}
_ANALYSIS_COUNT_FIELDS = {
    "automatic_retries",
    "connection_attempts",
    "error_lines",
    "line_count",
    "operation_attempts",
    "warning_lines",
}


class _DynamicStderrHandler(logging.StreamHandler):
    """Follow redirected stderr instead of retaining a stale test/CLI stream."""

    def emit(self, record: logging.LogRecord) -> None:
        self.stream = sys.stderr
        super().emit(record)


def _safe_token(value: object, fallback: str = "unknown") -> str:
    try:
        candidate = str(value)
    except Exception:  # noqa: BLE001 - diagnostics must never replace the primary failure
        return fallback
    return candidate if _TOKEN.fullmatch(candidate) else fallback


def safe_log_analysis(analysis: object) -> dict[str, object]:
    """Allowlist diagnostic fields; arbitrary exception text is always discarded."""
    if not isinstance(analysis, dict):
        return {"raw_log_included": False}
    safe: dict[str, object] = {}
    for field in _ANALYSIS_TOKEN_FIELDS:
        if field in analysis:
            safe[field] = _safe_token(analysis[field])
    for field in _ANALYSIS_LIST_FIELDS:
        value = analysis.get(field)
        if isinstance(value, (list, tuple)):
            safe[field] = [_safe_token(item) for item in value[:20]]
    for field in _ANALYSIS_COUNT_FIELDS:
        value = analysis.get(field)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            safe[field] = value
    fingerprint = analysis.get("terminal_fingerprint")
    if isinstance(fingerprint, str) and re.fullmatch(r"[0-9a-f]{12}", fingerprint):
        safe["terminal_fingerprint"] = fingerprint
    for field in ("stderr_present", "exception_chain_truncated"):
        if isinstance(analysis.get(field), bool):
            safe[field] = analysis[field]
    safe["raw_log_included"] = False
    return safe


def configure_logging(level: str = "WARNING") -> logging.Logger:
    """Configure the CatsChannel JSON logger on stderr, idempotently."""
    logger = logging.getLogger("cats_channel")
    if not any(getattr(handler, "_cats_channel_handler", False) for handler in logger.handlers):
        handler = _DynamicStderrHandler(sys.stderr)
        handler.setFormatter(logging.Formatter("%(message)s"))
        handler._cats_channel_handler = True  # type: ignore[attr-defined]
        logger.addHandler(handler)
    logger.setLevel(getattr(logging, level.upper(), logging.WARNING))
    logger.propagate = False
    return logger


def log_failure(
    logger: logging.Logger,
    event: str,
    error: BaseException,
    *,
    operation: str | None = None,
) -> None:
    """Emit one safe JSON failure event without serializing exception messages."""
    try:
        code = _safe_token(getattr(error, "code", "internal_error"), "internal_error")
        analysis = safe_log_analysis(getattr(error, "log_analysis", None))
        if not analysis.get("exception_types"):
            names, truncated = exception_chain(error)
            analysis["exception_types"] = [_safe_token(name) for name in names]
            analysis["exception_chain_truncated"] = truncated
        warnings = getattr(error, "warnings", ())
        payload: dict[str, object] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": "error",
            "event": _safe_token(event, "operation_failed"),
            "code": code,
            "analysis": analysis,
        }
        if operation is not None:
            payload["operation"] = _safe_token(operation)
        if isinstance(warnings, (list, tuple)) and warnings:
            payload["warnings"] = [_safe_token(value) for value in warnings[:20]]
        logger.error(json.dumps(payload, ensure_ascii=True, sort_keys=True, allow_nan=False))
    except Exception:  # noqa: BLE001 - logging must not hide the primary operational error
        return

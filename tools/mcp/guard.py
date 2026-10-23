#!/usr/bin/env python3
"""Privacy guard for the optional local Context7 stdio server."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, TextIO

MAX_LINE_BYTES = 64 * 1024
MAX_PUBLIC_TEXT = 800
ALLOWED_LIBRARY_IDS = frozenset({"/aiogram/aiogram", "/sqlalchemy/sqlalchemy"})
ALLOWED_LIBRARY_NAMES = frozenset({"aiogram", "sqlalchemy"})
ALLOWED_LANGUAGES = frozenset({"", "Python"})
ALLOWED_TOOLS = frozenset({"resolve-library-id", "resolve_library_id", "query-docs", "query_docs"})
QUERY_TOOLS = frozenset({"query-docs", "query_docs"})

# Filtering is defense in depth. It cannot prove that every possible encoding of
# private data has been recognized.
PRIVATE_PATTERNS = (
    (
        "source_excerpt",
        re.compile(
            r"```|^\s*(?:from|import)\s+\w|\bdef\s+\w+\s*\(|\bclass\s+\w+\s*[:(]",
            re.IGNORECASE | re.MULTILINE,
        ),
    ),
    (
        "repository_path",
        re.compile(
            r"(?:^|[\s'\"])(?:/tmp/|/mnt/|/home/|[A-Za-z]:[\\/]"
            r"|(?:\.\.?/)?(?:cats_channel|tests|project-context|\.git|uv\.lock"
            r"|pyproject\.toml)(?:[/\\]|\b))",
            re.IGNORECASE,
        ),
    ),
    (
        "internal_identifier",
        re.compile(
            r"\b(?:catschannel|cats_channel|submissionintakeservice|publicationservice"
            r"|replychainservice|postintent|intakeplacement|telegrammessageref"
            r"|privateentrycontext|flowlease|botoperation|reply_parent_unpublished"
            r"|reply_chain_conflict)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "credential",
        re.compile(
            r"(?:bearer\s+|api[_ -]?key\s*[:=]|password\s*[:=]|secret\s*[:=]"
            r"|token\s*[:=]|-----begin|eyj[a-z0-9_-]+\.[a-z0-9_-]+\.)",
            re.IGNORECASE,
        ),
    ),
    (
        "private_url",
        re.compile(
            r"(?:file://|https?://(?:localhost|127\.0\.0\.1|0\.0\.0\.0|10\."
            r"|192\.168\.|172\.(?:1[6-9]|2\d|3[01])\.)"
            r"|\b(?:postgres|sqlite)(?:\+\w+)?://)",
            re.IGNORECASE,
        ),
    ),
    (
        "internal_id",
        re.compile(
            r"\b[0-9a-f]{8}-[0-9a-f-]{27,}\b|\b\d{8,10}:[A-Za-z0-9_-]{30,}\b",
            re.IGNORECASE,
        ),
    ),
)


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        result: list[str] = []
        for key, item in value.items():
            result.extend(_strings(key))
            result.extend(_strings(item))
        return result
    if isinstance(value, list):
        return [text for item in value for text in _strings(item)]
    return []


def request_digest(request: Any) -> str:
    raw = json.dumps(request, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def validate_request(request: dict[str, Any]) -> tuple[bool, str, str]:
    """Return a policy decision and a content digest without retaining content."""
    digest = request_digest(request)
    method = request.get("method")
    if not isinstance(method, str):
        return False, "invalid_method", digest
    if method != "tools/call":
        return True, "protocol_message", digest
    params = request.get("params")
    if not isinstance(params, dict):
        return False, "invalid_params", digest
    name = params.get("name")
    arguments = params.get("arguments", {})
    if not isinstance(name, str):
        return False, "invalid_tool_name", digest
    if name not in ALLOWED_TOOLS:
        return False, "tool_not_allowlisted", digest
    if not isinstance(arguments, dict):
        return False, "invalid_arguments", digest
    query = arguments.get("query")
    if not isinstance(query, str):
        return False, "invalid_query", digest
    if name in QUERY_TOOLS:
        library_id = arguments.get("libraryId")
        language = arguments.get("language", "Python")
        if not isinstance(library_id, str):
            return False, "invalid_library_id", digest
        if not isinstance(language, str):
            return False, "invalid_language", digest
    else:
        library_name = arguments.get("libraryName")
        if not isinstance(library_name, str):
            return False, "invalid_library_name", digest
    combined = "\n".join(_strings(arguments))
    if len(combined.encode("utf-8")) > MAX_PUBLIC_TEXT:
        return False, "query_too_long", digest
    for reason, pattern in PRIVATE_PATTERNS:
        if pattern.search(combined):
            return False, reason, digest
    if name in QUERY_TOOLS:
        if library_id not in ALLOWED_LIBRARY_IDS:
            return False, "library_id_not_allowlisted", digest
        if language not in ALLOWED_LANGUAGES:
            return False, "language_not_allowlisted", digest
    elif library_name.casefold() not in ALLOWED_LIBRARY_NAMES:
        return False, "library_name_not_allowlisted", digest
    return True, "allowed_public_library_query", digest


def _safe_request_kind(request: dict[str, Any]) -> tuple[str, str]:
    if request.get("method") != "tools/call":
        return "protocol", "none"
    params = request.get("params")
    name = params.get("name") if isinstance(params, dict) else None
    return "tool_call", name if isinstance(name, str) and name in ALLOWED_TOOLS else "other"


class AuditLog:
    """Append only fixed metadata and digests, never arguments or raw messages."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()

    def write(
        self,
        *,
        request: dict[str, Any],
        allowed: bool,
        reason: str,
        digest: str,
    ) -> None:
        request_kind, tool_class = _safe_request_kind(request)
        record = {
            "schema": 1,
            "timestamp_unix": round(time.time(), 3),
            "request_kind": request_kind,
            "tool_class": tool_class,
            "allowed": allowed,
            "reason": reason,
            "request_sha256": digest,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock, self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")


def _error(request_id: Any, code: int, message: str) -> str:
    return json.dumps(
        {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}},
        separators=(",", ":"),
    )


def _emit(stream: TextIO, payload: str) -> bool:
    try:
        stream.write(payload + "\n")
        stream.flush()
    except (BrokenPipeError, OSError):
        return False
    return True


def _stop_process(process: subprocess.Popen[str], timeout: float) -> int:
    if process.poll() is not None:
        return process.returncode or 0
    process.terminate()
    try:
        return process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        return process.wait(timeout=timeout)


def run_guard(
    backend: list[str],
    *,
    audit_path: Path,
    input_stream: TextIO = sys.stdin,
    output_stream: TextIO = sys.stdout,
    shutdown_timeout: float = 5.0,
) -> int:
    """Run one guarded backend and own it until EOF, failure, or termination."""
    if not backend:
        raise ValueError("a backend command is required")
    try:
        child = subprocess.Popen(
            backend,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=sys.stderr,
            text=True,
            encoding="utf-8",
            bufsize=1,
        )
    except OSError:
        print("MCP backend could not be started", file=sys.stderr)
        return 69

    audit = AuditLog(audit_path)
    output_failed = threading.Event()

    def relay() -> None:
        assert child.stdout is not None
        for line in child.stdout:
            try:
                output_stream.write(line)
                output_stream.flush()
            except (BrokenPipeError, OSError):
                output_failed.set()
                return

    relay_thread = threading.Thread(target=relay, name="mcp-guard-relay", daemon=True)
    relay_thread.start()
    assert child.stdin is not None
    try:
        for line in input_stream:
            if output_failed.is_set():
                break
            raw_digest = hashlib.sha256(line.encode("utf-8")).hexdigest()
            if len(line.encode("utf-8")) > MAX_LINE_BYTES:
                invalid = {"method": "invalid"}
                audit.write(
                    request=invalid,
                    allowed=False,
                    reason="request_too_large",
                    digest=raw_digest,
                )
                if not _emit(output_stream, _error(None, -32600, "invalid request")):
                    break
                continue
            try:
                request = json.loads(line)
                if not isinstance(request, dict):
                    raise TypeError
            except (json.JSONDecodeError, TypeError):
                invalid = {"method": "invalid"}
                audit.write(
                    request=invalid,
                    allowed=False,
                    reason="malformed_json",
                    digest=raw_digest,
                )
                if not _emit(output_stream, _error(None, -32700, "parse error")):
                    break
                continue
            allowed, reason, digest = validate_request(request)
            audit.write(request=request, allowed=allowed, reason=reason, digest=digest)
            if not allowed:
                code = -32600 if reason == "invalid_method" else -32602
                message = "invalid request" if reason == "invalid_method" else "invalid params"
                if not reason.startswith("invalid_"):
                    code = -32001
                    message = "Context7 query rejected by policy"
                if not _emit(
                    output_stream,
                    _error(request.get("id"), code, message),
                ):
                    break
                continue
            if child.poll() is not None:
                _emit(output_stream, _error(request.get("id"), -32002, "MCP backend unavailable"))
                break
            try:
                child.stdin.write(line if line.endswith("\n") else line + "\n")
                child.stdin.flush()
            except (BrokenPipeError, OSError):
                _emit(output_stream, _error(request.get("id"), -32002, "MCP backend unavailable"))
                break
    finally:
        try:
            child.stdin.close()
        except (BrokenPipeError, OSError):
            pass
        try:
            return_code = child.wait(timeout=shutdown_timeout)
        except subprocess.TimeoutExpired:
            return_code = _stop_process(child, shutdown_timeout)
        relay_thread.join(timeout=shutdown_timeout)
    return return_code or 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit-log", required=True, type=Path)
    parser.add_argument("--shutdown-timeout", type=float, default=5.0)
    parser.add_argument("backend", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    backend = args.backend[1:] if args.backend[:1] == ["--"] else args.backend
    if not backend:
        parser.error("a backend command is required after --")
    if args.shutdown_timeout <= 0:
        parser.error("--shutdown-timeout must be positive")
    return run_guard(
        backend,
        audit_path=args.audit_log,
        shutdown_timeout=args.shutdown_timeout,
    )


if __name__ == "__main__":
    raise SystemExit(main())

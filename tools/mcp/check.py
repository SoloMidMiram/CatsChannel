#!/usr/bin/env python3
"""Run an explicit bounded Context7 stdio health check."""

from __future__ import annotations

import argparse
import hashlib
import json
import queue
import re
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, TextIO
from urllib.parse import urlsplit

SOURCE_URL = re.compile(r"https://(?:docs\.aiogram\.dev|docs\.sqlalchemy\.org|github\.com)/\S+")
PROTOCOL_VERSION = "2024-11-05"
EXPECTED_LIBRARY_ID = "/aiogram/aiogram"
LIBRARY_ID = re.compile(r"(?m)^\s*- Context7-compatible library ID:\s*(/[^\s]+)\s*$")


class RpcClient:
    def __init__(self, process: subprocess.Popen[str], timeout: float) -> None:
        self.process = process
        self.timeout = timeout
        self.responses: queue.Queue[str | None] = queue.Queue()
        self.reader = threading.Thread(target=self._read, name="mcp-check-reader", daemon=True)
        self.reader.start()

    def _read(self) -> None:
        assert self.process.stdout is not None
        for line in self.process.stdout:
            self.responses.put(line)
        self.responses.put(None)

    def send(self, payload: dict[str, Any]) -> None:
        assert self.process.stdin is not None
        self.process.stdin.write(json.dumps(payload, separators=(",", ":")) + "\n")
        self.process.stdin.flush()

    def call(self, request_id: int, method: str, params: dict[str, Any]) -> dict[str, Any]:
        self.send({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
        deadline = time.monotonic() + self.timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(method)
            try:
                line = self.responses.get(timeout=remaining)
            except queue.Empty as error:
                raise TimeoutError(method) from error
            if line is None:
                raise RuntimeError("transport closed")
            response = json.loads(line)
            if not isinstance(response, dict):
                raise TypeError("invalid JSON-RPC response")
            if response.get("id") == request_id:
                return response


def _content(response: dict[str, Any]) -> str:
    result = response.get("result")
    if not isinstance(result, dict) or result.get("isError"):
        return ""
    content = result.get("content")
    if not isinstance(content, list):
        return ""
    return "\n".join(
        item.get("text", "")
        for item in content
        if isinstance(item, dict) and item.get("type") == "text"
    )


def _initialization_valid(result: Any) -> bool:
    if not isinstance(result, dict) or result.get("protocolVersion") != PROTOCOL_VERSION:
        return False
    capabilities, info = result.get("capabilities"), result.get("serverInfo")
    if not isinstance(capabilities, dict) or not isinstance(capabilities.get("tools"), dict):
        return False
    if "listChanged" in capabilities["tools"] and not isinstance(
        capabilities["tools"]["listChanged"], bool
    ):
        return False
    return isinstance(info, dict) and all(
        isinstance(info.get(key), str) and bool(info[key].strip()) for key in ("name", "version")
    )


def _documentation_sources(text: str) -> list[str]:
    """Match public references to the requested library, without fetching pages."""
    sources = set()
    for line in text.splitlines():
        if not line.startswith("Source:"):
            continue
        for url in SOURCE_URL.findall(line):
            parsed = urlsplit(url)
            if parsed.query or parsed.username or parsed.password:
                continue
            if (parsed.hostname == "docs.aiogram.dev" and parsed.path.startswith("/en/")) or (
                parsed.hostname == "github.com" and parsed.path.startswith("/aiogram/aiogram/blob/")
            ):
                sources.add(url)
    return sorted(sources)


def _result_row(name: str, response: dict[str, Any], elapsed: float) -> dict[str, Any]:
    text = _content(response)
    error = response.get("error")
    row: dict[str, Any] = {"name": name, "elapsed_seconds": round(elapsed, 3)}
    has_result = "result" in response
    has_error = "error" in response
    if response.get("jsonrpc") != "2.0" or has_result == has_error:
        row.update({"ok": False, "error": "invalid_json_rpc_response"})
    elif isinstance(error, dict):
        row.update({"ok": False, "error_code": error.get("code"), "error": "json_rpc_error"})
    elif name == "initialize":
        row["ok"] = _initialization_valid(response.get("result"))
    elif name == "tools/list":
        result = response.get("result")
        tools = result.get("tools") if isinstance(result, dict) else None
        names = sorted(
            item["name"]
            for item in tools or []
            if isinstance(item, dict) and isinstance(item.get("name"), str)
        )
        row.update(
            {
                "ok": {"resolve-library-id", "query-docs"}.issubset(names),
                "advertised_tools": names,
            }
        )
    else:
        sources = _documentation_sources(text)
        if name == "tools/call:resolve-library-id":
            ok = EXPECTED_LIBRARY_ID in LIBRARY_ID.findall(text)
        else:
            body = re.sub(r"(?m)^Source:.*$", "", text).strip()
            ok = bool(body and sources)
        row.update(
            {
                "ok": ok,
                "content_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()
                if text
                else None,
                "source_urls": sources,
            }
        )
    return row


def run_check(
    command: list[str],
    *,
    timeout: float,
    idle_seconds: float,
    verify_policy_recovery: bool,
    stderr: TextIO = sys.stderr,
) -> tuple[int, dict[str, Any]]:
    started = time.monotonic()
    rows: list[dict[str, Any]] = []
    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=stderr,
            text=True,
            encoding="utf-8",
            bufsize=1,
            start_new_session=True,
        )
    except OSError:
        return 1, {
            "schema": 1,
            "ok": False,
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "process_exit": None,
            "termination": "start_failed",
            "error": "transport_start_failure",
            "calls": rows,
        }
    client = RpcClient(process, timeout)

    def call(request_id: int, method: str, params: dict[str, Any], label: str) -> dict[str, Any]:
        call_started = time.monotonic()
        response = client.call(request_id, method, params)
        rows.append(_result_row(label, response, time.monotonic() - call_started))
        return response

    error: str | None = None
    try:
        call(
            1,
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "cats-channel-mcp-check", "version": "1"},
            },
            "initialize",
        )
        client.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        call(2, "tools/list", {}, "tools/list")
        call(
            3,
            "tools/call",
            {
                "name": "resolve-library-id",
                "arguments": {"libraryName": "aiogram", "query": "aiogram Router documentation"},
            },
            "tools/call:resolve-library-id",
        )
        if idle_seconds:
            time.sleep(idle_seconds)
        query = {
            "name": "query-docs",
            "arguments": {
                "libraryId": "/aiogram/aiogram",
                "query": "Python Router include_router registration",
            },
        }
        call(4, "tools/call", query, "tools/call:query-docs")
        if verify_policy_recovery:
            denied = {
                "name": "query-docs",
                "arguments": {
                    "libraryId": "/aiogram/aiogram/3.31.0",
                    "query": "Python Router include_router registration",
                },
            }
            call(5, "tools/call", denied, "tools/call:expected-policy-denial")
            call(6, "tools/call", query, "tools/call:query-docs-after-denial")
    except (OSError, RuntimeError, TimeoutError, TypeError, json.JSONDecodeError):
        error = "transport_or_protocol_failure"
    finally:
        if process.stdin is not None:
            try:
                process.stdin.close()
            except (BrokenPipeError, OSError):
                pass
        try:
            process_exit = process.wait(timeout=min(timeout, 10.0))
            termination = "stdin_eof"
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                process_exit = process.wait(timeout=5)
                termination = "timeout_sigterm"
            except subprocess.TimeoutExpired:
                process.kill()
                process_exit = process.wait(timeout=5)
                termination = "timeout_sigkill"
    tool_rows = [row for row in rows if row["name"].startswith("tools/call")]
    expected_denial = next(
        (row for row in tool_rows if row["name"] == "tools/call:expected-policy-denial"), None
    )
    required_rows = [row for row in rows if row["name"] != "tools/call:expected-policy-denial"]
    retrievals = [row for row in required_rows if row["name"].startswith("tools/call")]
    ok = (
        error is None
        and process_exit == 0
        and all(row.get("ok") for row in required_rows)
        and any(row.get("content_sha256") for row in retrievals)
        and (expected_denial is None or expected_denial.get("error_code") == -32001)
    )
    summary = {
        "schema": 1,
        "ok": ok,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "process_exit": process_exit,
        "termination": termination,
        "error": error,
        "calls": rows,
    }
    return (0 if ok else 1), summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--idle-seconds", type=float, default=8.0)
    parser.add_argument("--verify-policy-recovery", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("a launcher command is required after --")
    if args.timeout <= 0 or args.idle_seconds < 0:
        parser.error("timeouts must be positive and idle time must be non-negative")
    code, summary = run_check(
        command,
        timeout=args.timeout,
        idle_seconds=args.idle_seconds,
        verify_policy_recovery=args.verify_policy_recovery,
    )
    rendered = json.dumps(summary, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    sys.stdout.write(rendered)
    return code


if __name__ == "__main__":
    raise SystemExit(main())

"""Codex negotiation compatibility and privacy negative controls."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from tools.mcp import guard


def initialize() -> dict:
    # Sanitized Codex 0.146.0-alpha.3 shape; no client-specific identifiers.
    return {
        "jsonrpc": "2.0",
        "id": "init-1",
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-11-25",
            "capabilities": {"elicitation": {"form": {}, "url": {}}},
            "clientInfo": {"name": "codex", "title": "Codex", "version": "0.146.0-alpha.3"},
        },
    }


@pytest.mark.parametrize("method", sorted(guard.DISCOVERY_METHODS))
@pytest.mark.parametrize("token", [0, -1, 7.5, 2**53 - 1, "inventory-1", "x" * 128])
def test_discovery_progress_token(method: str, token: object) -> None:
    assert guard.validate_request(
        {"method": method, "params": {"cursor": "next", "_meta": {"progressToken": token}}}
    )[0]


@pytest.mark.parametrize(
    "meta",
    [
        None,
        [],
        {},
        {"progressToken": True},
        {"progressToken": None},
        {"progressToken": []},
        {"progressToken": {}},
        {"progressToken": ""},
        {"progressToken": "x" * 129},
        {"progressToken": "é" * 65},
        {"progressToken": 2**53},
        {"progressToken": 10**500},
        {"progressToken": float("inf")},
        {"progressToken": float("nan")},
        {"progressToken": 1, "extra": "public"},
        {"other": 1},
        {"progressToken": "token=synthetic-private-canary"},
        {"progressToken": "/mnt/private/source.py"},
    ],
)
def test_discovery_metadata_negative_controls(meta: object) -> None:
    assert not guard.validate_request({"method": "tools/list", "params": {"_meta": meta}})[0]


@pytest.mark.parametrize(
    "capabilities",
    [
        {"elicitation": {"form": {"extra": True}}},
        {"elicitation": {"url": []}},
        {"elicitation": {"form": False}},
        {"elicitation": {"unknown": {}}},
        {"elicitation": []},
        {"sampling": {"tools": {}}},
        {"experimental": {"extra": {}}},
        {"roots": {"listChanged": 1}},
        {"unknown": {}},
    ],
)
def test_capability_negative_controls(capabilities: object) -> None:
    request = initialize()
    request["params"]["capabilities"] = capabilities
    assert not guard.validate_request(request)[0]


def test_handshake_normalizes_and_recovers_without_forwarding_private_fields(
    tmp_path: Path,
) -> None:
    backend = tmp_path / "backend.py"
    log = tmp_path / "forwarded.jsonl"
    backend.write_text(
        "import sys,json\n"
        "with open(sys.argv[1], 'w') as log:\n"
        " for line in sys.stdin:\n"
        "  msg=json.loads(line); log.write(line); log.flush()\n"
        "  if 'id' in msg:\n"
        "   print(json.dumps({'jsonrpc':'2.0','id':msg['id'],'result':{}}),flush=True)\n"
    )
    denied = [
        {"method": "tools/list", "params": {"_meta": {"progressToken": False}}},
        {"method": "tools/list", "params": {"_meta": {"progressToken": 1, "other": "canary"}}},
        {"method": "tools/list", "params": {"_meta": {"progressToken": "token=canary"}}},
        {"method": "elicitation/create", "params": {}},
        {"method": "ping", "params": {}, "_meta": {"private": "canary"}},
        {
            "method": "tools/call",
            "params": {
                "name": "query-docs",
                "arguments": {"libraryId": "/aiogram/aiogram/3.31.0", "query": "public docs"},
            },
        },
        {
            "method": "tools/call",
            "params": {
                "name": "query-docs",
                "arguments": {"libraryId": "/aiogram/aiogram", "query": "public docs"},
                "_meta": {"x": 1},
            },
        },
    ]
    for index, request in enumerate(denied):
        request.update(jsonrpc="2.0", id=f"deny-{index}")
    discovery = {
        "jsonrpc": "2.0",
        "id": 42,
        "method": "tools/list",
        "params": {"_meta": {"progressToken": 0}},
    }
    ping = {"jsonrpc": "2.0", "id": "recovered", "method": "ping"}
    messages = [initialize(), *denied, discovery, ping]
    completed = subprocess.run(
        [
            sys.executable,
            str(Path(guard.__file__)),
            "--audit-log",
            str(tmp_path / "audit"),
            "--",
            sys.executable,
            str(backend),
            str(log),
        ],
        input="".join(json.dumps(msg) + "\n" for msg in messages),
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )
    assert completed.returncode == 0
    assert completed.stdout.endswith("\n")
    responses = {msg["id"]: msg for msg in map(json.loads, completed.stdout.splitlines())}
    assert set(responses) == {msg["id"] for msg in messages}
    assert all("error" in responses[msg["id"]] for msg in denied)
    assert all("result" in responses[msg["id"]] for msg in [messages[0], discovery, ping])
    forwarded = list(map(json.loads, log.read_text().splitlines()))
    expected = initialize()
    expected["params"]["capabilities"] = {}
    assert forwarded == [expected, discovery, ping]
    assert "canary" not in log.read_text() + (tmp_path / "audit").read_text() + completed.stdout


@pytest.mark.parametrize("method", ["elicitation/create", "roots/list", "sampling/createMessage"])
def test_server_request_is_answered_locally(tmp_path: Path, method: str) -> None:
    backend = tmp_path / "backend.py"
    backend.write_text(
        "import json,sys\n"
        "msg=json.loads(sys.stdin.readline())\n"
        f"print(json.dumps({{'jsonrpc':'2.0','id':'server-1','method':{method!r},"
        "'params':{'message':'private-canary'}}),flush=True)\n"
        "reply=json.loads(sys.stdin.readline())\n"
        "assert reply['id']=='server-1' and reply['error']['code']==-32601\n"
        "print(json.dumps({'jsonrpc':'2.0','id':msg['id'],'result':{}}),flush=True)\n"
    )
    process = subprocess.Popen(
        [
            sys.executable,
            str(Path(guard.__file__)),
            "--audit-log",
            str(tmp_path / "audit"),
            "--",
            sys.executable,
            str(backend),
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert process.stdin is not None and process.stdout is not None
    try:
        process.stdin.write(json.dumps(initialize()) + "\n")
        process.stdin.flush()
        # communicate would close stdin before the backend request is answered.
        import threading

        received: list[str] = []
        reader = threading.Thread(
            target=lambda: received.append(process.stdout.readline()), daemon=True
        )
        reader.start()
        reader.join(timeout=5)
        assert not reader.is_alive()
        assert json.loads(received[0]) == {"jsonrpc": "2.0", "id": "init-1", "result": {}}
        _, stderr = process.communicate(timeout=5)
        assert process.returncode == 0, stderr
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)

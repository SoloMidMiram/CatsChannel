from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path, PureWindowsPath

import pytest

from tools.mcp import check, guard, launch

BACKEND = r"""
import json
import sys

record = open(sys.argv[1], "a", encoding="utf-8")
for line in sys.stdin:
    message = json.loads(line)
    record.write(json.dumps(message, sort_keys=True) + "\n")
    record.flush()
    if "id" in message:
        response = {
            "jsonrpc": "2.0",
            "id": message["id"],
            "result": {"content": [{"type": "text", "text": "public result"}]},
        }
        print(json.dumps(response), flush=True)
record.close()
"""


HEALTH_BACKEND = r"""
import json
import sys

mode = sys.argv[1]
fail_query = mode == "fail"
for line in sys.stdin:
    request = json.loads(line)
    if "id" not in request:
        continue
    method = request.get("method")
    params = request.get("params", {})
    name = params.get("name")
    arguments = params.get("arguments", {})
    if mode == "fail-initialize" and method == "initialize":
        response = {
            "jsonrpc": "2.0",
            "id": request["id"],
            "error": {"code": -32602, "message": "bad initialization"},
        }
    elif mode == "invalid-list-protocol" and method == "tools/list":
        response = {
            "jsonrpc": "1.0",
            "id": request["id"],
            "result": {"tools": [{"name": "resolve-library-id"}, {"name": "query-docs"}]},
        }
    elif name == "query-docs" and arguments.get("libraryId", "").endswith("3.31.0"):
        response = {
            "jsonrpc": "2.0",
            "id": request["id"],
            "error": {"code": -32001, "message": "policy"},
        }
    elif fail_query and name == "query-docs":
        response = {
            "jsonrpc": "2.0",
            "id": request["id"],
            "result": {"isError": True, "content": [{"type": "text", "text": "upstream detail"}]},
        }
    elif method == "tools/call":
        text = (
            "- Context7-compatible library ID: /aiogram/aiogram"
            if name == "resolve-library-id"
            else "### Router registration\n\nSource: https://docs.aiogram.dev/en/latest/dispatcher/router.html\n\nUse Router.include_router to register a child Router."
        )
        if mode == "arbitrary-text":
            text = "arbitrary nonempty response without evidence"
        elif mode == "wrong-library" and name == "resolve-library-id":
            text = "- Context7-compatible library ID: /unrelated/library"
        elif mode == "wrong-source" and name == "query-docs":
            text = "Source: https://github.com/unrelated/library/blob/main/docs.md\nUnrelated docs."
        elif mode == "no-source" and name == "query-docs":
            text = "Router.include_router attaches a child router."
        response = {
            "jsonrpc": "2.0",
            "id": request["id"],
            "result": {
                "content": [
                    {
                        "type": "text",
                        "text": text,
                    }
                ]
            },
        }
    elif method == "tools/list":
        response = {
            "jsonrpc": "2.0",
            "id": request["id"],
            "result": {"tools": [{"name": "resolve-library-id"}, {"name": "query-docs"}]},
        }
    else:
        result = {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "offline-fixture", "version": "1"},
        }
        if mode == "invalid-initialize":
            result = {"ok": True}
        elif mode == "wrong-protocol-version":
            result["protocolVersion"] = "1999-01-01"
        response = {"jsonrpc": "2.0", "id": request["id"], "result": result}
    print(json.dumps(response), flush=True)
"""


def write_script(tmp_path: Path, name: str, source: str) -> Path:
    path = tmp_path / name
    path.write_text(source, encoding="utf-8")
    return path


def guard_command(tmp_path: Path, backend: list[str]) -> list[str]:
    return [
        sys.executable,
        str(Path(guard.__file__)),
        "--audit-log",
        str(tmp_path / "audit.jsonl"),
        "--",
        *backend,
    ]


def call_message(request_id: int, library_id: str = "/aiogram/aiogram") -> dict[str, object]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "tools/call",
        "params": {
            "name": "query-docs",
            "arguments": {"libraryId": library_id, "query": "public Router documentation"},
        },
    }


def test_guard_frames_errors_and_recovers_on_same_connection(tmp_path: Path) -> None:
    backend_log = tmp_path / "backend.jsonl"
    backend = write_script(tmp_path, "backend.py", BACKEND)
    denied = call_message(2, "/aiogram/aiogram/3.31.0")
    allowed = call_message(3)
    payload = "not-json\n" + json.dumps(denied) + "\n" + json.dumps(allowed) + "\n"

    completed = subprocess.run(
        guard_command(tmp_path, [sys.executable, str(backend), str(backend_log)]),
        input=payload,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )

    assert completed.returncode == 0
    lines = completed.stdout.splitlines()
    assert len(lines) == 3
    assert json.loads(lines[0])["error"]["code"] == -32700
    assert json.loads(lines[1]) == {
        "jsonrpc": "2.0",
        "id": 2,
        "error": {"code": -32001, "message": "Context7 query rejected by policy"},
    }
    assert json.loads(lines[2])["id"] == 3
    forwarded = [json.loads(line) for line in backend_log.read_text(encoding="utf-8").splitlines()]
    assert forwarded == [allowed]

    audit_text = (tmp_path / "audit.jsonl").read_text(encoding="utf-8")
    assert "public Router documentation" not in audit_text
    assert "/aiogram/aiogram" not in audit_text
    records = [json.loads(line) for line in audit_text.splitlines()]
    assert [record["reason"] for record in records] == [
        "malformed_json",
        "library_id_not_allowlisted",
        "allowed_public_library_query",
    ]
    assert all(
        set(record)
        == {
            "allowed",
            "reason",
            "request_kind",
            "request_sha256",
            "schema",
            "timestamp_unix",
            "tool_class",
        }
        for record in records
    )


def test_guard_rejects_unsupported_protocol_payloads_and_recovers(tmp_path: Path) -> None:
    backend_log = tmp_path / "backend.jsonl"
    backend = write_script(tmp_path, "backend.py", BACKEND)
    private = "token=synthetic-private-canary"
    invalid = [
        {"method": "private/upload", "params": {"text": private}},
        {"method": "ping", "params": {"text": private}},
        {"method": "tools/list", "params": {"text": private}},
        {"method": "notifications/initialized", "params": {"text": private}},
        {
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"experimental": {"text": private}},
                "clientInfo": {"name": "test", "version": "1"},
            },
        },
        {
            "method": "notifications/cancelled",
            "params": {"requestId": 1, "reason": private},
        },
    ]
    messages = [dict(jsonrpc="2.0", id=index, **item) for index, item in enumerate(invalid, 1)]
    allowed = call_message(7)
    completed = subprocess.run(
        guard_command(tmp_path, [sys.executable, str(backend), str(backend_log)]),
        input="".join(json.dumps(item) + "\n" for item in [*messages, allowed]),
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )

    assert completed.returncode == 0
    responses = [json.loads(line) for line in completed.stdout.splitlines()]
    assert all("error" in response for response in responses[:-1])
    assert responses[-1]["id"] == 7
    assert [json.loads(line) for line in backend_log.read_text().splitlines()] == [allowed]
    assert private not in (tmp_path / "audit.jsonl").read_text() + completed.stdout


@pytest.mark.parametrize(
    ("method", "params"),
    [
        (
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {"roots": {"listChanged": True}},
                "clientInfo": {"name": "offline-client", "version": "1"},
            },
        ),
        ("notifications/initialized", {}),
        ("ping", {}),
        ("tools/list", {}),
        ("resources/list", {"cursor": "next-page"}),
        ("resources/templates/list", {}),
        ("prompts/list", {}),
        ("notifications/cancelled", {"requestId": 2, "reason": "Client cancelled"}),
    ],
)
def test_guard_allows_required_protocol_shapes(method: str, params: dict[str, object]) -> None:
    assert guard.validate_request({"method": method, "params": params})[0]


@pytest.mark.parametrize(
    ("arguments", "reason"),
    [
        ({"libraryId": "/other/library", "query": "public docs"}, "library_id_not_allowlisted"),
        ({"libraryId": "/aiogram/aiogram", "query": "/mnt/private/source.py"}, "repository_path"),
        ({"libraryId": "/aiogram/aiogram", "query": "token=top-secret"}, "credential"),
        ({"libraryId": "/aiogram/aiogram", "query": "x" * 801}, "query_too_long"),
    ],
)
def test_guard_rejects_non_public_arguments(arguments: dict[str, str], reason: str) -> None:
    request = {
        "jsonrpc": "2.0",
        "id": "possibly-private-id",
        "method": "tools/call",
        "params": {"name": "query-docs", "arguments": arguments},
    }
    allowed, actual_reason, digest = guard.validate_request(request)
    assert not allowed
    assert actual_reason == reason
    assert len(digest) == 64


@pytest.mark.parametrize(
    ("name", "arguments", "reason"),
    [
        ([], {"query": "public docs"}, "invalid_tool_name"),
        ("query-docs", {"libraryId": [], "query": "public docs"}, "invalid_library_id"),
        (
            "query-docs",
            {"libraryId": "/aiogram/aiogram", "query": "public docs", "language": {}},
            "invalid_language",
        ),
        ("query-docs", {"libraryId": "/aiogram/aiogram", "query": 7}, "invalid_query"),
        ("resolve-library-id", {"libraryName": [], "query": "public docs"}, "invalid_library_name"),
    ],
)
def test_guard_rejects_malformed_field_types_without_raising(
    name: object, arguments: dict[str, object], reason: str
) -> None:
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": name, "arguments": arguments},
    }

    allowed, actual_reason, _ = guard.validate_request(request)

    assert not allowed
    assert actual_reason == reason


def test_guard_malformed_type_is_framed_and_connection_recovers(tmp_path: Path) -> None:
    backend_log = tmp_path / "backend.jsonl"
    backend = write_script(tmp_path, "backend.py", BACKEND)
    malformed: list[dict[str, object]] = []
    for request_id, name, arguments in (
        (1, [], {"query": "public docs"}),
        (2, "query-docs", {"libraryId": [], "query": "public docs"}),
        (
            3,
            "query-docs",
            {"libraryId": "/aiogram/aiogram", "query": "public docs", "language": {}},
        ),
        (4, "query-docs", {"libraryId": "/aiogram/aiogram", "query": 7}),
        (5, "resolve-library-id", {"libraryName": [], "query": "public docs"}),
    ):
        malformed.append(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": "tools/call",
                "params": {"name": name, "arguments": arguments},
            }
        )
    allowed = call_message(6)

    completed = subprocess.run(
        guard_command(tmp_path, [sys.executable, str(backend), str(backend_log)]),
        input="".join(json.dumps(request) + "\n" for request in [*malformed, allowed]),
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )

    assert completed.returncode == 0
    responses = [json.loads(line) for line in completed.stdout.splitlines()]
    assert [response["error"]["code"] for response in responses[:-1]] == [-32602] * 5
    assert responses[-1]["id"] == 6
    forwarded = [json.loads(line) for line in backend_log.read_text(encoding="utf-8").splitlines()]
    assert forwarded == [allowed]
    audit = [
        json.loads(line)
        for line in (tmp_path / "audit.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert [record["reason"] for record in audit] == [
        "invalid_tool_name",
        "invalid_library_id",
        "invalid_language",
        "invalid_query",
        "invalid_library_name",
        "allowed_public_library_query",
    ]


def test_guard_rejects_oversized_input_without_forwarding(tmp_path: Path) -> None:
    backend_log = tmp_path / "backend.jsonl"
    backend = write_script(tmp_path, "backend.py", BACKEND)
    oversized = "{" + ("x" * guard.MAX_LINE_BYTES) + "}\n"

    completed = subprocess.run(
        guard_command(tmp_path, [sys.executable, str(backend), str(backend_log)]),
        input=oversized + json.dumps(call_message(9)) + "\n",
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )

    assert completed.returncode == 0
    assert completed.stdout.endswith("\n")
    responses = list(map(json.loads, completed.stdout.splitlines()))
    assert responses[0]["error"]["code"] == -32600
    assert responses[1]["id"] == 9 and "result" in responses[1]
    assert json.loads(backend_log.read_text(encoding="utf-8")) == call_message(9)
    audit = list(
        map(json.loads, (tmp_path / "audit.jsonl").read_text(encoding="utf-8").splitlines())
    )
    assert [row["reason"] for row in audit] == ["request_too_large", "allowed_public_library_query"]


def test_guard_backend_start_failure_is_prompt_and_sanitized(tmp_path: Path) -> None:
    missing = tmp_path / "secret-name-that-must-not-be-printed"
    completed = subprocess.run(
        guard_command(tmp_path, [str(missing)]),
        input="",
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )

    assert completed.returncode == 69
    assert completed.stderr.strip() == "MCP backend could not be started"
    assert str(missing) not in completed.stderr


def test_guard_reports_closed_backend_without_exception_payload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    backend = write_script(
        tmp_path,
        "closed.py",
        "raise SystemExit(0)\n",
    )
    popen = subprocess.Popen

    def closed_backend(*args, **kwargs):
        process = popen(*args, **kwargs)
        process.wait(timeout=5)
        return process

    monkeypatch.setattr(guard.subprocess, "Popen", closed_backend)
    output = io.StringIO()
    guard.run_guard(
        [sys.executable, str(backend)],
        audit_path=tmp_path / "audit.jsonl",
        input_stream=io.StringIO(json.dumps(call_message(1)) + "\n"),
        output_stream=output,
    )
    stdout = output.getvalue()

    assert json.loads(stdout)["error"] == {"code": -32002, "message": "MCP backend unavailable"}


def test_audit_never_records_request_ids_or_arguments(tmp_path: Path) -> None:
    request = call_message(7)
    request["private-extra"] = "do-not-retain"
    audit = guard.AuditLog(tmp_path / "audit.jsonl")
    allowed, reason, digest = guard.validate_request(request)
    audit.write(request=request, allowed=allowed, reason=reason, digest=digest)
    content = (tmp_path / "audit.jsonl").read_text(encoding="utf-8")

    assert "do-not-retain" not in content
    assert '"id"' not in content
    assert "public Router documentation" not in content


@pytest.mark.skipif(os.name == "nt", reason="POSIX process-group lifecycle")
def test_supervisor_termination_stops_and_reaps_owned_child() -> None:
    supervisor = launch.Supervisor(
        [sys.executable, "-c", "import time; time.sleep(60)"], shutdown_timeout=1
    )
    result: list[int] = []
    worker = threading.Thread(target=lambda: result.append(supervisor.run()))
    worker.start()
    deadline = time.monotonic() + 5
    while supervisor.process is None and time.monotonic() < deadline:
        time.sleep(0.01)
    assert supervisor.process is not None

    supervisor.request_stop(signal.SIGTERM)
    worker.join(timeout=5)

    assert not worker.is_alive()
    assert supervisor.process.poll() is not None
    assert result == [-signal.SIGTERM]


@pytest.mark.skipif(os.name == "nt", reason="POSIX process lifecycle")
def test_supervisor_survives_spawning_context_until_normal_exit() -> None:
    supervisor = launch.Supervisor(
        [sys.executable, "-c", "import time; time.sleep(0.2)"], shutdown_timeout=1
    )
    result: list[int] = []

    spawning_thread = threading.Thread(target=lambda: result.append(supervisor.run()))
    spawning_thread.start()
    time.sleep(0.1)

    assert spawning_thread.is_alive()
    assert supervisor.process is not None
    assert supervisor.process.poll() is None
    spawning_thread.join(timeout=3)
    assert result == [0]
    assert supervisor.process.poll() == 0


@pytest.mark.skipif(
    os.name == "nt" or shutil.which("bwrap") is None,
    reason="requires Linux/WSL bubblewrap",
)
def test_supervisor_terminates_and_reaps_actual_sandbox_server(tmp_path: Path) -> None:
    state = tmp_path / "state"
    state.mkdir()
    command = launch._base_bwrap(state_dir=state, network=False)
    command.extend(("/usr/bin/python3", "-c", "import time; time.sleep(60)"))
    supervisor = launch.Supervisor(
        command,
        shutdown_timeout=2,
        sandboxed=True,
        startup_timeout=3,
    )
    result: list[int] = []
    errors: list[BaseException] = []

    def run() -> None:
        try:
            result.append(supervisor.run())
        except BaseException as error:  # noqa: BLE001 - propagated into the test thread
            errors.append(error)

    worker = threading.Thread(target=run)
    worker.start()
    deadline = time.monotonic() + 5
    while supervisor.sandbox_pid is None and not errors and time.monotonic() < deadline:
        time.sleep(0.01)

    assert not errors
    assert supervisor.process is not None
    assert supervisor.sandbox_pid is not None
    assert supervisor.sandbox_pid != supervisor.process.pid
    server_pid = supervisor.sandbox_pid

    supervisor.request_stop(signal.SIGTERM)
    worker.join(timeout=5)

    assert not worker.is_alive()
    assert not errors
    assert result
    assert supervisor.process.poll() is not None
    with pytest.raises(ProcessLookupError):
        os.kill(server_pid, 0)


@pytest.mark.skipif(
    os.name == "nt" or shutil.which("bwrap") is None,
    reason="requires Linux/WSL bubblewrap",
)
def test_supervisor_terminates_server_when_sandbox_wrapper_dies(tmp_path: Path) -> None:
    state = tmp_path / "state"
    state.mkdir()
    command = launch._base_bwrap(state_dir=state, network=False)
    command.extend(("/usr/bin/python3", "-c", "import time; time.sleep(60)"))
    supervisor = launch.Supervisor(
        command,
        shutdown_timeout=2,
        sandboxed=True,
        startup_timeout=3,
    )
    errors: list[BaseException] = []

    def run() -> None:
        try:
            supervisor.run()
        except BaseException as error:  # noqa: BLE001 - propagated into the test thread
            errors.append(error)

    worker = threading.Thread(target=run)
    worker.start()
    deadline = time.monotonic() + 5
    while supervisor.sandbox_pid is None and not errors and time.monotonic() < deadline:
        time.sleep(0.01)

    assert not errors
    assert supervisor.process is not None
    assert supervisor.sandbox_pid is not None
    server_pid = supervisor.sandbox_pid
    os.kill(supervisor.process.pid, signal.SIGKILL)
    worker.join(timeout=7)

    assert not worker.is_alive()
    assert not errors
    with pytest.raises(ProcessLookupError):
        os.kill(server_pid, 0)


@pytest.mark.skipif(
    os.name == "nt" or shutil.which("bwrap") is None,
    reason="requires Linux/WSL bubblewrap",
)
def test_serena_metadata_overlay_is_writable_without_mutating_source(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "source.py").write_text("SOURCE = True\n", encoding="utf-8")
    state = tmp_path / "state"
    metadata = tmp_path / "project-metadata"
    state.mkdir()
    metadata.mkdir()
    command = launch._base_bwrap(state_dir=state, network=False)
    command.extend(launch._workspace_mounts(project, metadata))
    command.extend(
        (
            "/usr/bin/python3",
            "-c",
            (
                "from pathlib import Path; "
                "Path('/workspace/.serena/project.yml').write_text('ok'); "
                "assert Path('/workspace/source.py').read_text() == 'SOURCE = True\\n'"
            ),
        )
    )

    completed = subprocess.run(command, capture_output=True, text=True, timeout=10, check=False)

    assert completed.returncode == 0, completed.stderr
    assert (metadata / "project.yml").read_text(encoding="utf-8") == "ok"
    assert not (project / ".serena").exists()


@pytest.mark.skipif(
    os.name == "nt" or shutil.which("bwrap") is None,
    reason="requires Linux/WSL bubblewrap",
)
def test_managed_python_symlink_chain_executes_inside_sandbox(tmp_path: Path) -> None:
    environment = tmp_path / "tool"
    managed = tmp_path / "managed-python"
    versioned = managed / "cpython-3.13.9" / "bin"
    (environment / "bin").mkdir(parents=True)
    versioned.mkdir(parents=True)
    (versioned / "python3.13").symlink_to("/usr/bin/python3")
    (managed / "cpython-3.13-linux-x86_64-gnu").symlink_to(versioned.parent)
    environment_python = environment / "bin" / "python"
    environment_python.symlink_to(managed / "cpython-3.13-linux-x86_64-gnu" / "bin" / "python3.13")
    python_roots = launch._python_mount_roots(environment_python, environment)
    state = tmp_path / "state"
    state.mkdir()
    command = launch._base_bwrap(state_dir=state, network=False)
    command.extend(launch._destination_dirs((environment, *python_roots)))
    command.extend(("--ro-bind", str(environment), str(environment)))
    for python_root in python_roots:
        command.extend(("--ro-bind", str(python_root), str(python_root)))
    command.extend((str(environment_python), "-c", "print('managed-python-ok')"))

    completed = subprocess.run(command, capture_output=True, text=True, timeout=10, check=False)

    assert python_roots == [managed]
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "managed-python-ok"


@pytest.mark.skipif(
    os.name == "nt" or shutil.which("bwrap") is None,
    reason="requires Linux/WSL bubblewrap",
)
def test_wsl_resolver_target_is_readable_inside_sandbox(tmp_path: Path) -> None:
    host_resolver = Path("/etc/resolv.conf").resolve(strict=True)
    state = tmp_path / "state"
    state.mkdir()
    command = launch._base_bwrap(state_dir=state, network=True)
    command.extend(
        (
            "/usr/bin/python3",
            "-c",
            "from pathlib import Path; print(Path('/etc/resolv.conf').read_text(), end='')",
        )
    )

    completed = subprocess.run(command, capture_output=True, text=True, timeout=10, check=False)

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout == host_resolver.read_text(encoding="utf-8")


def test_external_resolver_symlink_target_is_mounted(tmp_path: Path) -> None:
    target = tmp_path / "mnt" / "wsl" / "resolv.conf"
    target.parent.mkdir(parents=True)
    target.write_text("nameserver 192.0.2.1\n", encoding="utf-8")
    resolver = tmp_path / "etc" / "resolv.conf"
    resolver.parent.mkdir()
    resolver.symlink_to(target)

    mounts = launch._resolver_mounts(resolver)

    target_index = mounts.index(str(target))
    assert mounts[target_index - 1] == "--ro-bind"
    assert mounts[target_index + 1] == str(target)
    assert str(target.parent) in mounts


def test_destination_dirs_stops_at_unrecognized_filesystem_anchor() -> None:
    target = PureWindowsPath("D:/external/resolv.conf")

    mounts = launch._destination_dirs((target,))  # type: ignore[arg-type]

    assert mounts == ["--dir", r"D:\external"]


@pytest.mark.skipif(os.name == "nt", reason="Linux/WSL sandbox command")
def test_context7_command_checks_pin_and_does_not_mount_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package_root = tmp_path / "external" / "context7"
    package = package_root / "node_modules" / "@upstash" / "context7-mcp"
    (package / "dist").mkdir(parents=True)
    (package / "package.json").write_text('{"version":"4.4.4"}', encoding="utf-8")
    (package / "dist" / "index.js").write_text("", encoding="utf-8")
    monkeypatch.setattr(launch, "ROOT", tmp_path / "checkout")
    monkeypatch.setattr(launch.shutil, "which", lambda name, **kwargs: "/usr/bin/bwrap")

    command = launch.context7_command(package_root, tmp_path / "checkout" / ".runtime" / "mcp")
    rendered = " ".join(command)

    assert "--clearenv" in command
    assert "--die-with-parent" not in command
    assert str(package_root / "node_modules") in command
    assert "/workspace" not in rendered
    assert "CONTEXT7_API_KEY" not in rendered


@pytest.mark.skipif(os.name != "nt", reason="native Windows limitation")
def test_native_windows_sandbox_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="Linux or WSL"):
        launch._base_bwrap(state_dir=tmp_path, network=True)


def test_context7_command_rejects_package_tree_inside_checkout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "checkout"
    package_root = root / ".cache" / "context7"
    package_root.mkdir(parents=True)
    monkeypatch.setattr(launch, "ROOT", root)

    with pytest.raises(ValueError, match="outside"):
        launch.context7_command(package_root, root / ".runtime" / "mcp")


def test_launcher_failure_does_not_print_external_path(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    missing = tmp_path / "private-machine-path"

    code = launch.main(["context7", "--package-root", str(missing)])

    captured = capsys.readouterr()
    assert code == 78
    assert str(missing) not in captured.err


@pytest.mark.skipif(os.name == "nt", reason="Linux/WSL sandbox command")
def test_serena_command_is_offline_read_only_and_version_checked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "checkout"
    root.mkdir()
    (root / "source.py").write_text("SOURCE = True\n", encoding="utf-8")
    environment = tmp_path / "external" / "serena-agent"
    bin_dir = environment / "bin"
    metadata = environment / "lib" / "python3.13" / "site-packages" / "serena_agent-2.1.0.dist-info"
    managed = tmp_path / "external" / "managed-python"
    versioned = managed / "cpython-3.13.9" / "bin"
    bin_dir.mkdir(parents=True)
    metadata.mkdir(parents=True)
    versioned.mkdir(parents=True)
    (bin_dir / "serena").write_text("#!/bin/sh\n", encoding="utf-8")
    (versioned / "python3.13").write_text("", encoding="utf-8")
    (managed / "cpython-3.13-linux-x86_64-gnu").symlink_to(versioned.parent)
    (bin_dir / "python").symlink_to(
        managed / "cpython-3.13-linux-x86_64-gnu" / "bin" / "python3.13"
    )
    (metadata / "METADATA").write_text("Name: serena-agent\nVersion: 2.1.0\n", encoding="utf-8")
    monkeypatch.setattr(launch, "ROOT", root)
    monkeypatch.setattr(launch.shutil, "which", lambda name, **kwargs: "/usr/bin/bwrap")

    pyright = tmp_path / "external" / "pyright"
    pyright.mkdir()
    (pyright / "package.json").write_text('{"name":"pyright","version":"1.1.403"}')
    (pyright / "langserver.index.js").write_text("#!/usr/bin/env node\n")
    command = launch.serena_command(
        environment, root, root / ".runtime" / "mcp", pyright_root=pyright
    )

    # Initialization alone used to pass with no Python language-server prerequisite.
    config = root / ".runtime/mcp/serena-state/.serena/serena_config.yml"
    assert config.is_file(), "packaged Serena must configure an offline Python language server"
    settings = json.loads(config.read_text(encoding="utf-8"))
    assert settings["projects"] == []
    assert set(settings["fixed_tools"]) == {
        "find_declaration",
        "find_implementations",
        "find_referencing_symbols",
        "find_symbol",
        "get_symbols_overview",
    }
    assert (
        settings["ls_specific_settings"]["python"]["ls_path"] == "/opt/pyright/langserver.index.js"
    )
    assert "trusted_project_path_patterns" not in settings
    pyright_bind = command.index(str(pyright))
    assert command[pyright_bind - 1 : pyright_bind + 2] == [
        "--ro-bind",
        str(pyright),
        "/opt/pyright",
    ]
    assert "uv" not in command and "uvx" not in command

    assert "--unshare-net" in command
    assert "--die-with-parent" not in command
    source_bind = command.index(str(root / "source.py"))
    assert command[source_bind - 1] == "--ro-bind"
    assert command[source_bind + 1] == "/workspace/source.py"
    project_state = root / ".runtime" / "mcp" / "serena-project"
    project_state_index = command.index(str(project_state))
    assert command[project_state_index - 1] == "--bind"
    assert command[project_state_index + 1] == "/workspace/.serena"
    managed_index = command.index(str(managed))
    assert command[managed_index - 1] == "--ro-bind"
    assert command[managed_index + 1] == str(managed)
    assert "no-memories" in command
    assert "find_symbol" not in command  # The owned config limits the exposed inventory.


@pytest.mark.skipif(os.name == "nt", reason="Linux/WSL sandbox command")
def test_serena_command_rejects_wrong_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "checkout"
    root.mkdir()
    environment = tmp_path / "external" / "serena-agent"
    metadata = environment / "lib" / "python3.13" / "site-packages" / "serena_agent-2.0.0.dist-info"
    (environment / "bin").mkdir(parents=True)
    metadata.mkdir(parents=True)
    (environment / "bin" / "serena").write_text("", encoding="utf-8")
    (metadata / "METADATA").write_text("Name: serena-agent\nVersion: 2.0.0\n", encoding="utf-8")
    monkeypatch.setattr(launch, "ROOT", root)
    monkeypatch.setattr(launch.shutil, "which", lambda *args, **kwargs: "/usr/bin/node")

    pyright = tmp_path / "pyright"
    pyright.mkdir()
    (pyright / "package.json").write_text('{"name":"pyright","version":"1.1.403"}')
    (pyright / "langserver.index.js").write_text("#!/usr/bin/env node\n")
    with pytest.raises(ValueError, match="does not match"):
        launch.serena_command(environment, root, root / ".runtime" / "mcp", pyright_root=pyright)


@pytest.mark.parametrize("fault", ["missing", "version", "entrypoint", "internal", "node"])
def test_serena_rejects_missing_or_invalid_pyright_prerequisite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    root = tmp_path / "checkout"
    root.mkdir()
    environment = tmp_path / "serena"
    environment.mkdir()
    pyright = (root if fault == "internal" else tmp_path) / "pyright"
    if fault != "missing":
        pyright.mkdir()
        (pyright / "package.json").write_text(
            json.dumps({"name": "pyright", "version": "0.0.0" if fault == "version" else "1.1.403"})
        )
        if fault != "entrypoint":
            (pyright / "langserver.index.js").write_text("#!/usr/bin/env node\n")
    monkeypatch.setattr(launch, "ROOT", root)
    monkeypatch.setattr(launch.shutil, "which", lambda *args, **kwargs: None)
    with pytest.raises((OSError, ValueError, RuntimeError)):
        launch.serena_command(environment, root, root / ".runtime/mcp", pyright_root=pyright)
    assert not (root / ".runtime").exists()


@pytest.mark.skipif(
    sys.platform != "linux"
    or not os.environ.get("CATS_SERENA_ENV")
    or not os.environ.get("CATS_PYRIGHT_ROOT"),
    reason="opt-in: preinstalled external Serena/Pyright and Linux bubblewrap required",
)
@pytest.mark.parametrize("shutdown", ["eof", "sigterm"])
def test_packaged_serena_real_python_semantics(tmp_path: Path, shutdown: str) -> None:
    """No installs/network: exercise the actual launcher, coordinates and LS teardown."""
    root = launch.ROOT
    environment = Path(os.environ["CATS_SERENA_ENV"])
    pyright = Path(os.environ["CATS_PYRIGHT_ROOT"])
    tracked = subprocess.check_output(["git", "ls-files", "-z"], cwd=root).split(b"\0")

    def source_snapshot() -> dict[str, tuple[str, int]]:
        return {
            os.fsdecode(name): (
                hashlib.sha256((root / os.fsdecode(name)).read_bytes()).hexdigest(),
                (root / os.fsdecode(name)).stat().st_mtime_ns,
            )
            for name in tracked
            if name
        }

    def process_tree(parent: int) -> dict[int, str]:
        processes = {}
        for entry in Path("/proc").iterdir():
            if entry.name.isdigit():
                try:
                    fields = (entry / "stat").read_text().split(") ", 1)[1].split()
                    processes[int(entry.name)] = (int(fields[1]), fields[19])
                except (OSError, IndexError):
                    pass
        owned = {parent}
        while children := {pid for pid, (ppid, _) in processes.items() if ppid in owned} - owned:
            owned.update(children)
        return {pid: processes[pid][1] for pid in owned if pid in processes}

    before = source_snapshot()
    command = [
        sys.executable,
        str(Path(launch.__file__)),
        "--runtime-dir",
        str(tmp_path / "runtime"),
        "serena",
        "--tool-environment",
        str(environment),
        "--project-root",
        str(root),
        "--pyright-root",
        str(pyright),
    ]
    owned: dict[int, str] = {}
    with (tmp_path / "stderr.log").open("w") as stderr:
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=stderr,
            text=True,
            start_new_session=True,
        )
        client = check.RpcClient(process, timeout=90)
        try:
            initialized = client.call(
                1,
                "initialize",
                {
                    "protocolVersion": check.PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "packaged-serena-acceptance", "version": "1"},
                },
            )
            assert check._initialization_valid(initialized.get("result"))
            client.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
            inventory = client.call(2, "tools/list", {})
            assert {tool["name"] for tool in inventory["result"]["tools"]} == {
                "find_declaration",
                "find_implementations",
                "find_referencing_symbols",
                "find_symbol",
                "get_symbols_overview",
            }
            symbol_response = client.call(
                3,
                "tools/call",
                {
                    "name": "find_symbol",
                    "arguments": {
                        "name_path_pattern": "validate_request",
                        "relative_path": "tools/mcp/guard.py",
                    },
                },
            )
            symbols = json.loads(check._content(symbol_response))
            assert len(symbols) == 1 and symbols[0]["name_path"] == "validate_request"
            lines = (root / symbols[0]["relative_path"]).read_text().splitlines()
            assert lines[symbols[0]["body_location"]["start_line"]].startswith(
                "def validate_request("
            )
            references_response = client.call(
                4,
                "tools/call",
                {
                    "name": "find_referencing_symbols",
                    "arguments": {
                        "name_path": "validate_request",
                        "relative_path": "tools/mcp/guard.py",
                    },
                },
            )
            references = json.loads(check._content(references_response))
            assert set(references) == {"tools/mcp/guard.py", "tests/test_mcp_tools.py"}
            count = 0
            for relative_path, kinds in references.items():
                lines = (root / relative_path).read_text().splitlines()
                for reference in (row for rows in kinds.values() for row in rows):
                    location = reference["body_location"]
                    assert 0 <= location["start_line"] <= location["end_line"] < len(lines)
                    highlights = re.findall(
                        r"(?m)^\s*>\s*(\d+):(.*)$", reference["content_around_reference"]
                    )
                    assert highlights
                    for line, content in highlights:
                        assert lines[int(line)] == content
                        assert "validate_request(" in content
                        count += 1
            assert count == 5
            owned = process_tree(process.pid)
            assert len(owned) >= 4  # launcher, bwrap, Serena and the real Pyright process
        finally:
            if shutdown == "sigterm":
                process.terminate()
            assert process.stdin is not None
            process.stdin.close()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.terminate()
                process.wait(timeout=15)
        expected_exits = {0, 128 + signal.SIGTERM} if shutdown == "sigterm" else {0}
        assert process.returncode in expected_exits
    assert before == source_snapshot()
    for pid, start_time in owned.items():
        assert process_tree(pid).get(pid) != start_time, f"owned process {pid} survived shutdown"


def test_health_check_verifies_content_policy_denial_and_recovery(tmp_path: Path) -> None:
    backend = write_script(tmp_path, "health.py", HEALTH_BACKEND)
    code, summary = check.run_check(
        [sys.executable, str(backend), "pass"],
        timeout=2,
        idle_seconds=0,
        verify_policy_recovery=True,
        stderr=subprocess.DEVNULL,
    )

    assert code == 0
    assert summary["ok"] is True
    calls = {row["name"]: row for row in summary["calls"]}
    assert calls["tools/call:expected-policy-denial"]["error_code"] == -32001
    assert calls["tools/call:query-docs-after-denial"]["ok"] is True
    assert calls["tools/call:query-docs"]["content_sha256"]
    assert calls["tools/call:query-docs"]["source_urls"] == [
        "https://docs.aiogram.dev/en/latest/dispatcher/router.html"
    ]


def test_health_check_reports_tool_failure_despite_clean_process_exit(tmp_path: Path) -> None:
    backend = write_script(tmp_path, "health.py", HEALTH_BACKEND)
    code, summary = check.run_check(
        [sys.executable, str(backend), "fail"],
        timeout=2,
        idle_seconds=0,
        verify_policy_recovery=False,
        stderr=subprocess.DEVNULL,
    )

    assert code == 1
    assert summary["process_exit"] == 0
    assert summary["ok"] is False
    query = next(row for row in summary["calls"] if row["name"] == "tools/call:query-docs")
    assert query["ok"] is False
    assert "upstream detail" not in json.dumps(summary)


@pytest.mark.parametrize(
    ("mode", "failed_call"),
    [
        ("fail-initialize", "initialize"),
        ("invalid-list-protocol", "tools/list"),
        ("invalid-initialize", "initialize"),
        ("wrong-protocol-version", "initialize"),
        ("arbitrary-text", "tools/call:resolve-library-id"),
        ("wrong-library", "tools/call:resolve-library-id"),
        ("wrong-source", "tools/call:query-docs"),
        ("no-source", "tools/call:query-docs"),
    ],
)
def test_health_check_includes_protocol_failures_in_verdict(
    tmp_path: Path, mode: str, failed_call: str
) -> None:
    backend = write_script(tmp_path, "health.py", HEALTH_BACKEND)

    code, summary = check.run_check(
        [sys.executable, str(backend), mode],
        timeout=2,
        idle_seconds=0,
        verify_policy_recovery=False,
        stderr=subprocess.DEVNULL,
    )

    assert code == 1
    assert summary["process_exit"] == 0
    assert summary["ok"] is False
    failed = next(row for row in summary["calls"] if row["name"] == failed_call)
    assert failed["ok"] is False


def test_health_check_start_failure_does_not_expose_os_error(tmp_path: Path) -> None:
    code, summary = check.run_check(
        [str(tmp_path / "missing-secret-name")],
        timeout=1,
        idle_seconds=0,
        verify_policy_recovery=False,
        stderr=subprocess.DEVNULL,
    )

    assert code == 1
    assert summary["termination"] == "start_failed"
    assert "missing-secret-name" not in json.dumps(summary)

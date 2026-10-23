#!/usr/bin/env python3
"""Launch an externally installed MCP server in a bounded Linux sandbox."""

from __future__ import annotations

import argparse
import json
import os
import select
import shutil
import signal
import subprocess
import sys
import time
from collections.abc import Sequence
from pathlib import Path
from types import FrameType
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
VERSIONS_PATH = Path(__file__).with_name("versions.json")


def _resolved(path: Path) -> Path:
    return path.expanduser().resolve(strict=True)


def _require_external(path: Path, label: str) -> Path:
    resolved = _resolved(path)
    if resolved == ROOT or ROOT in resolved.parents:
        raise ValueError(f"{label} must be outside the repository checkout")
    return resolved


def _versions() -> dict[str, Any]:
    return json.loads(VERSIONS_PATH.read_text(encoding="utf-8"))


def _destination_dirs(paths: Sequence[Path]) -> list[str]:
    """Create parents for external mounts below the sandbox's tmpfs roots."""
    fixed_roots = {
        Path(name) for name in ("/", "/home", "/tmp", "/usr", "/bin", "/lib", "/lib64", "/etc")
    }
    directories: set[Path] = set()
    for path in paths:
        parent = path.parent
        while parent not in fixed_roots and parent != parent.parent:
            directories.add(parent)
            parent = parent.parent
    arguments: list[str] = []
    for directory in sorted(directories, key=lambda item: (len(item.parts), str(item))):
        arguments.extend(("--dir", str(directory)))
    return arguments


def _resolver_mounts(resolver: Path = Path("/etc/resolv.conf")) -> list[str]:
    """Preserve an external resolver target such as WSL's /mnt/wsl file."""
    if not resolver.is_symlink():
        return []
    target = resolver.resolve(strict=True)
    if target == Path("/etc") or Path("/etc") in target.parents:
        return []
    return [*_destination_dirs((target,)), "--ro-bind", str(target), str(target)]


def _system_mounts() -> list[str]:
    arguments: list[str] = []
    for name in ("/usr", "/bin", "/lib", "/lib64", "/etc"):
        path = Path(name)
        if path.exists():
            arguments.extend(("--ro-bind", name, name))
    arguments.extend(_resolver_mounts())
    return arguments


def _is_within(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _python_mount_roots(environment_python: Path, tool_environment: Path) -> list[Path]:
    """Return minimal roots that preserve every managed-runtime symlink hop."""
    if environment_python.is_symlink():
        target = Path(os.readlink(environment_python))
        logical_target = target if target.is_absolute() else environment_python.parent / target
    else:
        logical_target = environment_python
    final_target = logical_target.resolve(strict=True)
    candidates: set[Path] = {final_target.parents[1]}

    current = Path(logical_target.anchor)
    for part in logical_target.parts[1:]:
        current /= part
        if current.is_symlink():
            candidates.add(current.parent)

    existing_roots = (tool_environment, Path("/usr"), Path("/bin"), Path("/lib"), Path("/lib64"))
    external = [
        candidate
        for candidate in candidates
        if not any(_is_within(candidate, root) for root in existing_roots)
    ]
    selected: list[Path] = []
    for candidate in sorted(external, key=lambda item: (len(item.parts), str(item))):
        if not any(_is_within(candidate, root) for root in selected):
            selected.append(candidate)
    return selected


def _workspace_mounts(project_root: Path, project_state: Path) -> list[str]:
    """Mount project entries read-only and reserve writable Serena metadata."""
    arguments = ["--dir", "/workspace"]
    for entry in sorted(project_root.iterdir(), key=lambda item: item.name):
        if entry.name in {".runtime", ".serena"}:
            continue
        arguments.extend(("--ro-bind", str(entry), f"/workspace/{entry.name}"))
    arguments.extend(
        (
            "--dir",
            "/workspace/.serena",
            "--bind",
            str(project_state),
            "/workspace/.serena",
        )
    )
    return arguments


def _base_bwrap(*, state_dir: Path, network: bool) -> list[str]:
    bwrap = shutil.which("bwrap")
    if os.name == "nt" or not bwrap:
        raise RuntimeError("bubblewrap is required; use Linux or WSL with bwrap installed")
    command = [bwrap, "--clearenv", "--new-session"]
    if not network:
        command.append("--unshare-net")
    command.extend(_system_mounts())
    command.extend(
        (
            "--dev",
            "/dev",
            "--proc",
            "/proc",
            "--tmpfs",
            "/tmp",
            "--tmpfs",
            "/home",
            "--dir",
            "/state",
            "--bind",
            str(state_dir),
            "/state",
            "--setenv",
            "HOME",
            "/state",
            "--setenv",
            "PATH",
            "/usr/bin:/bin",
            "--setenv",
            "LANG",
            "C.UTF-8",
        )
    )
    return command


def context7_command(package_root: Path, runtime_dir: Path) -> list[str]:
    package_root = _require_external(package_root, "Context7 package root")
    runtime_dir.mkdir(parents=True, exist_ok=True)
    state_dir = runtime_dir.resolve() / "context7-state"
    audit_dir = runtime_dir.resolve() / "audit"
    state_dir.mkdir(parents=True, exist_ok=True)
    audit_dir.mkdir(parents=True, exist_ok=True)
    versions = _versions()["context7"]
    package = package_root / "node_modules" / versions["package"]
    metadata = json.loads((package / "package.json").read_text(encoding="utf-8"))
    if metadata.get("version") != versions["version"]:
        raise ValueError("installed Context7 version does not match versions.json")
    entrypoint = package / versions["entrypoint"]
    if not entrypoint.is_file():
        raise ValueError("Context7 entrypoint is missing")
    guard = Path(__file__).with_name("guard.py").resolve()
    python = shutil.which("python3", path="/usr/bin:/bin")
    if not python:
        raise RuntimeError("system python3 is required inside the sandbox")
    command = _base_bwrap(state_dir=state_dir, network=True)
    command.extend(
        (
            "--dir",
            "/opt/context7",
            "--ro-bind",
            str(package_root / "node_modules"),
            "/opt/context7/node_modules",
            "--dir",
            "/runner",
            "--ro-bind",
            str(guard),
            "/runner/guard.py",
            "--dir",
            "/audit",
            "--bind",
            str(audit_dir),
            "/audit",
            "--setenv",
            "NODE_ENV",
            "production",
            python,
            "/runner/guard.py",
            "--audit-log",
            "/audit/context7.jsonl",
            "--",
            "/usr/bin/node",
            f"/opt/context7/node_modules/{versions['package']}/{versions['entrypoint']}",
        )
    )
    return command


def serena_command(
    tool_environment: Path, project_root: Path, runtime_dir: Path, *, pyright_root: Path
) -> list[str]:
    tool_environment = _require_external(tool_environment, "Serena tool environment")
    project_root = _resolved(project_root)
    pyright_root = _require_external(pyright_root, "Pyright package root")
    if _is_within(pyright_root, project_root):
        raise ValueError("Pyright must be outside the source project")
    pyright = _versions()["pyright"]
    package = json.loads((pyright_root / "package.json").read_text(encoding="utf-8"))
    if package.get("name") != "pyright" or package.get("version") != pyright["version"]:
        raise ValueError("installed Pyright version does not match versions.json")
    if not (pyright_root / pyright["entrypoint"]).is_file():
        raise ValueError("Pyright language-server entrypoint is missing")
    if not shutil.which("node", path="/usr/bin:/bin"):
        raise RuntimeError("system node is required inside the sandbox")
    runtime_dir.mkdir(parents=True, exist_ok=True)
    state_dir = runtime_dir.resolve() / "serena-state"
    project_state = runtime_dir.resolve() / "serena-project"
    state_dir.mkdir(parents=True, exist_ok=True)
    project_state.mkdir(parents=True, exist_ok=True)
    # Owned global config avoids trusting project-supplied commands. ls_path
    # bypasses Serena's uvx installation path entirely (including deferred install).
    config_dir = state_dir / ".serena"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "serena_config.yml").write_text(
        json.dumps(
            {
                "projects": [],
                "fixed_tools": [
                    "find_declaration",
                    "find_implementations",
                    "find_referencing_symbols",
                    "find_symbol",
                    "get_symbols_overview",
                ],
                "ls_specific_settings": {"python": {"ls_path": "/opt/pyright/langserver.index.js"}},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    executable = tool_environment / ("Scripts/serena.exe" if os.name == "nt" else "bin/serena")
    if not executable.is_file():
        raise ValueError("Serena executable is missing from the tool environment")
    metadata_files = list(
        tool_environment.glob("lib/python*/site-packages/serena_agent-*.dist-info/METADATA")
    )
    if len(metadata_files) != 1:
        raise ValueError("Serena package metadata is missing or ambiguous")
    metadata = metadata_files[0].read_text(encoding="utf-8")
    installed_version = next(
        (
            line.removeprefix("Version: ")
            for line in metadata.splitlines()
            if line.startswith("Version: ")
        ),
        None,
    )
    if installed_version != _versions()["serena"]["version"]:
        raise ValueError("installed Serena version does not match versions.json")
    environment_python = tool_environment / "bin" / "python"
    python_roots = _python_mount_roots(environment_python, tool_environment)
    command = _base_bwrap(state_dir=state_dir, network=False)
    command.extend(_destination_dirs((tool_environment, *python_roots)))
    command.extend(
        (
            "--ro-bind",
            str(tool_environment),
            str(tool_environment),
        )
    )
    for python_root in python_roots:
        command.extend(("--ro-bind", str(python_root), str(python_root)))
    command.extend(("--dir", "/opt/pyright", "--ro-bind", str(pyright_root), "/opt/pyright"))
    command.extend(_workspace_mounts(project_root, project_state))
    command.extend(
        (
            "--setenv",
            "VIRTUAL_ENV",
            str(tool_environment),
            "--setenv",
            "PATH",
            f"{tool_environment / 'bin'}:/usr/bin:/bin",
            str(executable),
            "start-mcp-server",
            "--project",
            "/workspace",
            "--context=codex",
            "--mode",
            "no-memories",
            "--agent-interface",
            "tools",
            "--enable-web-dashboard=false",
            "--open-web-dashboard=false",
        )
    )
    return command


class Supervisor:
    """Own a subprocess group and reap it on EOF-driven exit or termination."""

    def __init__(
        self,
        command: Sequence[str],
        *,
        shutdown_timeout: float = 5.0,
        sandboxed: bool = False,
        startup_timeout: float = 10.0,
    ) -> None:
        if not command:
            raise ValueError("command must not be empty")
        if shutdown_timeout <= 0:
            raise ValueError("shutdown_timeout must be positive")
        if startup_timeout <= 0:
            raise ValueError("startup_timeout must be positive")
        self.command = list(command)
        self.shutdown_timeout = shutdown_timeout
        self.sandboxed = sandboxed
        self.startup_timeout = startup_timeout
        self.process: subprocess.Popen[bytes] | None = None
        self.sandbox_pid: int | None = None
        self._termination_signal: int | None = None

    def request_stop(self, signum: int = signal.SIGTERM, _frame: FrameType | None = None) -> None:
        self._termination_signal = signum

    @staticmethod
    def _signal_group(process_group: int, signum: int) -> None:
        try:
            os.killpg(process_group, signum)
        except ProcessLookupError:
            pass

    @staticmethod
    def _group_exists(process_group: int) -> bool:
        try:
            os.killpg(process_group, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True

    def _stop_sandbox_group(self) -> None:
        assert self.sandbox_pid is not None
        self._signal_group(self.sandbox_pid, signal.SIGTERM)
        deadline = time.monotonic() + self.shutdown_timeout
        while self._group_exists(self.sandbox_pid) and time.monotonic() < deadline:
            time.sleep(0.05)
        if self._group_exists(self.sandbox_pid):
            self._signal_group(self.sandbox_pid, signal.SIGKILL)
            deadline = time.monotonic() + self.shutdown_timeout
            while self._group_exists(self.sandbox_pid) and time.monotonic() < deadline:
                time.sleep(0.05)

    def _terminate(self) -> int:
        assert self.process is not None
        if self.sandbox_pid is not None:
            self._stop_sandbox_group()
        if self.process.poll() is not None:
            return self.process.returncode or 0
        target_group = self.process.pid
        self._signal_group(target_group, signal.SIGTERM)
        try:
            return self.process.wait(timeout=self.shutdown_timeout)
        except subprocess.TimeoutExpired:
            self._signal_group(target_group, signal.SIGKILL)
            try:
                return self.process.wait(timeout=self.shutdown_timeout)
            except subprocess.TimeoutExpired:
                self._signal_group(self.process.pid, signal.SIGKILL)
                return self.process.wait(timeout=self.shutdown_timeout)

    def _start(self) -> None:
        if not self.sandboxed:
            self.process = subprocess.Popen(self.command, start_new_session=True)
            return
        read_fd, write_fd = os.pipe()
        command = [self.command[0], "--info-fd", str(write_fd), *self.command[1:]]
        try:
            self.process = subprocess.Popen(
                command,
                start_new_session=True,
                pass_fds=(write_fd,),
            )
        finally:
            os.close(write_fd)
        ready, _, _ = select.select((read_fd,), (), (), self.startup_timeout)
        try:
            if not ready:
                self._signal_group(self.process.pid, signal.SIGKILL)
                self.process.wait(timeout=self.shutdown_timeout)
                raise RuntimeError("sandbox did not report its child process")
            payload = os.read(read_fd, 64 * 1024)
        finally:
            os.close(read_fd)
        try:
            child_pid = json.loads(payload).get("child-pid")
        except (AttributeError, json.JSONDecodeError) as error:
            self._signal_group(self.process.pid, signal.SIGKILL)
            self.process.wait(timeout=self.shutdown_timeout)
            raise RuntimeError("sandbox returned invalid process information") from error
        if not isinstance(child_pid, int) or child_pid <= 0:
            self._signal_group(self.process.pid, signal.SIGKILL)
            self.process.wait(timeout=self.shutdown_timeout)
            raise RuntimeError("sandbox did not report a valid child process")
        self.sandbox_pid = child_pid

    def run(self) -> int:
        self._start()
        assert self.process is not None
        while self.process.poll() is None and self._termination_signal is None:
            time.sleep(0.05)
        if self._termination_signal is not None:
            return self._terminate()
        if self.sandbox_pid is not None and self._group_exists(self.sandbox_pid):
            self._stop_sandbox_group()
        return self.process.returncode or 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-dir", type=Path, default=ROOT / ".runtime" / "mcp")
    parser.add_argument("--shutdown-timeout", type=float, default=5.0)
    subparsers = parser.add_subparsers(dest="server", required=True)
    context7 = subparsers.add_parser("context7")
    context7.add_argument("--package-root", required=True, type=Path)
    serena = subparsers.add_parser("serena")
    serena.add_argument("--tool-environment", required=True, type=Path)
    serena.add_argument("--pyright-root", required=True, type=Path)
    serena.add_argument("--project-root", type=Path, default=ROOT)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.server == "context7":
            command = context7_command(args.package_root, args.runtime_dir)
        else:
            command = serena_command(
                args.tool_environment,
                args.project_root,
                args.runtime_dir,
                pyright_root=args.pyright_root,
            )
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError):
        print(
            "MCP launcher refused to start; verify external paths, versions, and prerequisites",
            file=sys.stderr,
        )
        return 78
    supervisor = Supervisor(command, shutdown_timeout=args.shutdown_timeout, sandboxed=True)
    if os.name != "nt":
        signal.signal(signal.SIGTERM, supervisor.request_stop)
        signal.signal(signal.SIGINT, supervisor.request_stop)
    try:
        return supervisor.run()
    except (OSError, RuntimeError):
        print("MCP launcher could not start the sandbox", file=sys.stderr)
        return 69


if __name__ == "__main__":
    raise SystemExit(main())

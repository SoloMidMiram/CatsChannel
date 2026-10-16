import os
import signal
import subprocess
import tempfile
import threading
import time
from collections.abc import Mapping, Sequence
from contextlib import ExitStack
from dataclasses import dataclass, field
from typing import BinaryIO

from ..errors import MediaError


class _WindowsJob:
    """Minimal Windows Job Object wrapper; inert on non-Windows platforms."""

    def __init__(self, process: subprocess.Popen) -> None:
        self._handle = None
        if os.name != "nt":
            return
        import ctypes
        from ctypes import wintypes

        class IO_COUNTERS(ctypes.Structure):
            _fields_ = [
                ("ReadOperationCount", ctypes.c_uint64),
                ("WriteOperationCount", ctypes.c_uint64),
                ("OtherOperationCount", ctypes.c_uint64),
                ("ReadTransferCount", ctypes.c_uint64),
                ("WriteTransferCount", ctypes.c_uint64),
                ("OtherTransferCount", ctypes.c_uint64),
            ]

        class BASIC_LIMITS(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_int64),
                ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class EXTENDED_LIMITS(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", BASIC_LIMITS),
                ("IoInfo", IO_COUNTERS),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        handle = kernel32.CreateJobObjectW(None, None)
        if not handle:
            return
        limits = EXTENDED_LIMITS()
        limits.BasicLimitInformation.LimitFlags = 0x00002000
        configured = kernel32.SetInformationJobObject(
            handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)
        )
        assigned = configured and kernel32.AssignProcessToJobObject(
            handle, wintypes.HANDLE(process._handle)
        )
        if not assigned:
            kernel32.CloseHandle(handle)
            return
        self._handle = handle
        self._kernel32 = kernel32

    @property
    def active(self) -> bool:
        return self._handle is not None

    def terminate(self) -> None:
        if self._handle is not None:
            self._kernel32.TerminateJobObject(self._handle, 1)

    def close(self) -> None:
        if self._handle is not None:
            self._kernel32.CloseHandle(self._handle)
            self._handle = None


class _WindowsCapture:
    """Seekable process output that never creates blocking pipe-reader threads."""

    def __init__(self) -> None:
        self._stack = ExitStack()
        self.stdout: BinaryIO = self._stack.enter_context(
            tempfile.TemporaryFile(mode="w+b")  # noqa: SIM115 - owned by ExitStack
        )
        self.stderr: BinaryIO = self._stack.enter_context(
            tempfile.TemporaryFile(mode="w+b")  # noqa: SIM115 - owned by ExitStack
        )

    def read(
        self,
        *,
        text: bool,
        encoding: str,
        errors: str,
    ) -> tuple[str | bytes, str | bytes]:
        values: list[str | bytes] = []
        for stream in (self.stdout, self.stderr):
            stream.flush()
            stream.seek(0)
            payload = stream.read()
            values.append(payload.decode(encoding, errors) if text else payload)
        return values[0], values[1]

    def close(self) -> None:
        try:
            self._stack.close()
        except OSError:
            pass


@dataclass
class CancellationToken:
    _event: threading.Event = field(default_factory=threading.Event)

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()


class OwnedProcessRunner:
    """Run one owned process group and reap it before returning or raising."""

    def __init__(self, *, poll_seconds: float = 0.1, terminate_grace_seconds: float = 2.0):
        self.poll_seconds = poll_seconds
        self.terminate_grace_seconds = terminate_grace_seconds

    def run(
        self,
        command: Sequence[str],
        *,
        timeout: float,
        token: CancellationToken | None = None,
        text: bool = True,
        encoding: str = "utf-8",
        errors: str = "replace",
        env: Mapping[str, str] | None = None,
    ) -> subprocess.CompletedProcess:
        windows_capture = _WindowsCapture() if os.name == "nt" else None
        popen_kwargs: dict[str, object] = {
            "stdout": windows_capture.stdout if windows_capture else subprocess.PIPE,
            "stderr": windows_capture.stderr if windows_capture else subprocess.PIPE,
            "env": dict(env) if env is not None else None,
        }
        if windows_capture is None:
            popen_kwargs["text"] = text
        if text and windows_capture is None:
            popen_kwargs.update(encoding=encoding, errors=errors)
        if os.name == "nt":
            popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            popen_kwargs["start_new_session"] = True
        try:
            process = subprocess.Popen(list(command), **popen_kwargs)
        except OSError as error:
            if windows_capture is not None:
                windows_capture.close()
            raise MediaError(
                "Could not start the required media process.",
                code="process_start",
            ) from error
        job = _WindowsJob(process)
        windows_descendants: set[int] = set()

        try:
            deadline = time.monotonic() + timeout
            while True:
                if token is not None and token.cancelled:
                    raise MediaError(code="cancelled")
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise MediaError(code="timeout")
                if windows_capture is not None:
                    if not job.active:
                        windows_descendants.update(
                            self._windows_descendant_pids({process.pid, *windows_descendants})
                        )
                    try:
                        process.wait(timeout=min(self.poll_seconds, remaining))
                    except subprocess.TimeoutExpired:
                        continue
                    if not job.active:
                        windows_descendants.update(
                            self._windows_descendant_pids({process.pid, *windows_descendants})
                        )
                        self._stop_and_reap(process, job, windows_descendants)
                    stdout, stderr = windows_capture.read(
                        text=text,
                        encoding=encoding,
                        errors=errors,
                    )
                    return subprocess.CompletedProcess(
                        list(command), process.returncode, stdout=stdout, stderr=stderr
                    )
                try:
                    stdout, stderr = process.communicate(timeout=min(self.poll_seconds, remaining))
                    if os.name != "nt" and self._posix_group_exists(process.pid):
                        self._stop_and_reap(process, job)
                    return subprocess.CompletedProcess(
                        list(command), process.returncode, stdout=stdout, stderr=stderr
                    )
                except subprocess.TimeoutExpired:
                    continue
        except BaseException:
            self._stop_and_reap(process, job, windows_descendants)
            raise
        finally:
            job.close()
            if windows_capture is not None:
                windows_capture.close()

    def _stop_and_reap(
        self,
        process: subprocess.Popen,
        job: _WindowsJob,
        windows_descendants: set[int] | None = None,
    ) -> None:
        if os.name == "nt":
            deadline = time.monotonic() + self.terminate_grace_seconds
            terminated_job = False
            if job.active:
                try:
                    job.terminate()
                    terminated_job = True
                except (OSError, KeyboardInterrupt):
                    pass
            if not terminated_job:
                self._stop_windows_tree(
                    process,
                    windows_descendants if windows_descendants is not None else set(),
                    deadline,
                )
            if process.poll() is None:
                self._kill_process(process)
            self._bounded_wait(process, timeout=self._remaining(deadline))
            return

        deadline = time.monotonic() + self.terminate_grace_seconds
        self._signal_posix_group(process.pid, signal.SIGTERM)
        self._bounded_communicate(process, timeout=self.terminate_grace_seconds)
        self._wait_for_posix_group(process.pid, deadline)
        if self._posix_group_exists(process.pid):
            self._signal_posix_group(process.pid, signal.SIGKILL)
            self._bounded_communicate(process, timeout=self.terminate_grace_seconds)
        self._close_pipes(process)
        if not self._bounded_wait(process):
            self._kill_process(process)
            self._bounded_wait(process)

    @staticmethod
    def _signal_posix_group(process_group_id: int, signal_number: int) -> None:
        try:
            os.killpg(process_group_id, signal_number)
        except (OSError, ProcessLookupError):
            pass

    @staticmethod
    def _posix_group_exists(process_group_id: int) -> bool:
        try:
            os.killpg(process_group_id, 0)
        except (OSError, ProcessLookupError):
            return False
        return True

    def _wait_for_posix_group(self, process_group_id: int, deadline: float) -> None:
        try:
            while self._posix_group_exists(process_group_id) and time.monotonic() < deadline:
                time.sleep(min(self.poll_seconds, max(0.0, deadline - time.monotonic())))
        except KeyboardInterrupt:
            pass

    def _bounded_communicate(
        self,
        process: subprocess.Popen,
        *,
        timeout: float | None = None,
    ) -> bool:
        try:
            process.communicate(
                timeout=self.terminate_grace_seconds if timeout is None else max(timeout, 0.001)
            )
        except (OSError, ValueError, subprocess.TimeoutExpired, KeyboardInterrupt):
            return False
        return True

    def _bounded_wait(
        self,
        process: subprocess.Popen,
        *,
        timeout: float | None = None,
    ) -> bool:
        try:
            process.wait(
                timeout=(self.terminate_grace_seconds if timeout is None else max(timeout, 0.001))
            )
        except (OSError, subprocess.TimeoutExpired, KeyboardInterrupt):
            return False
        return True

    @staticmethod
    def _kill_process(process: subprocess.Popen) -> None:
        try:
            process.kill()
        except (OSError, ProcessLookupError):
            pass

    @staticmethod
    def _close_pipes(process: subprocess.Popen) -> None:
        for stream in (process.stdout, process.stderr, process.stdin):
            if stream is None:
                continue
            try:
                stream.close()
            except OSError:
                pass

    @staticmethod
    def _remaining(deadline: float) -> float:
        return max(0.0, deadline - time.monotonic())

    @staticmethod
    def _windows_descendant_pids(root_pids: set[int]) -> set[int]:
        """Snapshot descendants even if an original root process has already exited."""
        if os.name != "nt" or not root_pids:
            return set()
        import ctypes
        from ctypes import wintypes

        class PROCESSENTRY32W(ctypes.Structure):
            _fields_ = [
                ("dwSize", wintypes.DWORD),
                ("cntUsage", wintypes.DWORD),
                ("th32ProcessID", wintypes.DWORD),
                ("th32DefaultHeapID", ctypes.c_size_t),
                ("th32ModuleID", wintypes.DWORD),
                ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD),
                ("pcPriClassBase", wintypes.LONG),
                ("dwFlags", wintypes.DWORD),
                ("szExeFile", wintypes.WCHAR * 260),
            ]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateToolhelp32Snapshot.argtypes = (wintypes.DWORD, wintypes.DWORD)
        kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        kernel32.Process32FirstW.argtypes = (
            wintypes.HANDLE,
            ctypes.POINTER(PROCESSENTRY32W),
        )
        kernel32.Process32FirstW.restype = wintypes.BOOL
        kernel32.Process32NextW.argtypes = (
            wintypes.HANDLE,
            ctypes.POINTER(PROCESSENTRY32W),
        )
        kernel32.Process32NextW.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        kernel32.CloseHandle.restype = wintypes.BOOL
        snapshot = kernel32.CreateToolhelp32Snapshot(0x00000002, 0)
        if snapshot == ctypes.c_void_p(-1).value:
            return set()
        parent_by_pid: dict[int, int] = {}
        try:
            entry = PROCESSENTRY32W()
            entry.dwSize = ctypes.sizeof(entry)
            if not kernel32.Process32FirstW(snapshot, ctypes.byref(entry)):
                return set()
            while True:
                parent_by_pid[int(entry.th32ProcessID)] = int(entry.th32ParentProcessID)
                if not kernel32.Process32NextW(snapshot, ctypes.byref(entry)):
                    break
        finally:
            kernel32.CloseHandle(snapshot)

        descendants: set[int] = set()
        frontier = set(root_pids)
        while frontier:
            children = {
                pid
                for pid, parent_pid in parent_by_pid.items()
                if parent_pid in frontier and pid not in root_pids and pid not in descendants
            }
            if not children:
                break
            descendants.update(children)
            frontier = children
        return descendants

    def _run_taskkill(self, process_id: int, deadline: float) -> None:
        remaining = min(self._remaining(deadline), max(self.poll_seconds, 0.01))
        if remaining <= 0:
            return
        try:
            taskkill = subprocess.Popen(
                ["taskkill", "/PID", str(process_id), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except OSError:
            return
        try:
            taskkill.wait(timeout=remaining)
        except (subprocess.TimeoutExpired, KeyboardInterrupt):
            try:
                taskkill.kill()
            except OSError:
                pass
            remaining = self._remaining(deadline)
            if remaining > 0:
                try:
                    taskkill.wait(timeout=remaining)
                except (OSError, subprocess.TimeoutExpired, KeyboardInterrupt):
                    pass

    def _terminate_windows_pids(self, process_ids: set[int], deadline: float) -> None:
        """Signal known descendants directly, then wait only within the shared budget."""
        if os.name != "nt" or not process_ids:
            return
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.TerminateProcess.argtypes = (wintypes.HANDLE, wintypes.UINT)
        kernel32.TerminateProcess.restype = wintypes.BOOL
        kernel32.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
        kernel32.WaitForSingleObject.restype = wintypes.DWORD
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        kernel32.CloseHandle.restype = wintypes.BOOL
        handles = []
        try:
            for process_id in process_ids:
                if self._remaining(deadline) <= 0:
                    break
                handle = kernel32.OpenProcess(0x00100001, False, process_id)
                if not handle:
                    continue
                handles.append(handle)
                kernel32.TerminateProcess(handle, 1)
            for handle in handles:
                remaining_ms = int(self._remaining(deadline) * 1000)
                if remaining_ms <= 0:
                    break
                kernel32.WaitForSingleObject(handle, remaining_ms)
        finally:
            for handle in handles:
                kernel32.CloseHandle(handle)

    def _stop_windows_tree(
        self,
        process: subprocess.Popen,
        known_descendants: set[int],
        deadline: float,
    ) -> None:
        """Terminate a fallback tree within one shared deadline."""
        roots = {process.pid, *known_descendants}
        for _attempt in range(2):
            if self._remaining(deadline) <= 0:
                return
            known_descendants.update(self._windows_descendant_pids(roots))
            roots.update(known_descendants)
            if process.poll() is None:
                self._run_taskkill(process.pid, deadline)
            if not known_descendants:
                return
            self._terminate_windows_pids(known_descendants, deadline)


DEFAULT_PROCESS_RUNNER = OwnedProcessRunner()

import os
import subprocess
import sys
import threading
import time
from unittest.mock import patch

import pytest

from cats_channel.adapters.process import CancellationToken, OwnedProcessRunner
from cats_channel.errors import MediaError


def test_cancellation_reaps_process_group_before_return(tmp_path):
    marker = tmp_path / "survived.txt"
    child_code = "import pathlib,sys,time;time.sleep(.8);pathlib.Path(sys.argv[1]).write_text('x')"
    parent_code = (
        "import subprocess,sys,time;"
        "subprocess.Popen([sys.executable,'-c',sys.argv[1],sys.argv[2]]);"
        "time.sleep(10)"
    )
    token = CancellationToken()
    runner = OwnedProcessRunner(poll_seconds=0.02, terminate_grace_seconds=0.2)
    caught = []

    def run():
        try:
            runner.run(
                [sys.executable, "-c", parent_code, child_code, str(marker)],
                timeout=5,
                token=token,
            )
        except MediaError as error:
            caught.append(error.code)

    thread = threading.Thread(target=run)
    thread.start()
    time.sleep(0.15)
    token.cancel()
    thread.join(timeout=2)
    assert not thread.is_alive()
    assert caught == ["cancelled"]
    time.sleep(0.9)
    assert not marker.exists()


def test_timeout_reaps_process_before_raising():
    runner = OwnedProcessRunner(poll_seconds=0.01, terminate_grace_seconds=0.1)
    with pytest.raises(MediaError) as error:
        runner.run([sys.executable, "-c", "import time; time.sleep(10)"], timeout=0.1)
    assert error.value.code == "timeout"


@pytest.mark.skipif(os.name == "nt", reason="POSIX process-group regression")
def test_keyboard_interrupt_reaps_process_group_before_return(tmp_path):
    ready = tmp_path / "ready.txt"
    marker = tmp_path / "survived.txt"
    child_code = "import pathlib,sys,time;time.sleep(.8);pathlib.Path(sys.argv[1]).write_text('x')"
    parent_code = (
        "import pathlib,subprocess,sys,time;"
        "subprocess.Popen([sys.executable,'-c',sys.argv[1],sys.argv[2]]);"
        "pathlib.Path(sys.argv[3]).write_text('ready');"
        "time.sleep(10)"
    )
    runner = OwnedProcessRunner(poll_seconds=0.02, terminate_grace_seconds=0.2)
    original_communicate = subprocess.Popen.communicate
    interrupted = False

    def interrupt_once(process, *args, **kwargs):
        nonlocal interrupted
        if not interrupted:
            interrupted = True
            deadline = time.monotonic() + 1
            while not ready.exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            raise KeyboardInterrupt
        return original_communicate(process, *args, **kwargs)

    with (
        patch("cats_channel.adapters.process.subprocess.Popen.communicate", interrupt_once),
        pytest.raises(KeyboardInterrupt),
    ):
        runner.run(
            [sys.executable, "-c", parent_code, child_code, str(marker), str(ready)],
            timeout=5,
        )

    time.sleep(0.9)
    assert not marker.exists()


@pytest.mark.skipif(os.name == "nt", reason="POSIX process-group regression")
def test_timeout_reaps_descendant_after_parent_exits_without_unbounded_wait(tmp_path):
    marker = tmp_path / "survived.txt"
    child_code = "import pathlib,sys,time;time.sleep(.8);pathlib.Path(sys.argv[1]).write_text('x')"
    parent_code = (
        "import subprocess,sys;subprocess.Popen([sys.executable,'-c',sys.argv[1],sys.argv[2]])"
    )
    runner = OwnedProcessRunner(poll_seconds=0.01, terminate_grace_seconds=0.1)

    started = time.monotonic()
    with pytest.raises(MediaError) as error:
        runner.run(
            [sys.executable, "-c", parent_code, child_code, str(marker)],
            timeout=0.1,
        )
    elapsed = time.monotonic() - started

    assert error.value.code == "timeout"
    assert elapsed < 0.65
    time.sleep(0.8)
    assert not marker.exists()


def test_process_runner_returns_captured_output():
    result = OwnedProcessRunner().run([sys.executable, "-c", "print('ok')"], timeout=2)
    assert isinstance(result, subprocess.CompletedProcess)
    assert result.returncode == 0
    assert result.stdout.strip() == "ok"


def test_process_runner_returns_binary_output():
    result = OwnedProcessRunner().run(
        [sys.executable, "-c", "import sys;sys.stdout.buffer.write(b'cat\\x00video')"],
        timeout=2,
        text=False,
    )
    assert result.returncode == 0
    assert result.stdout == b"cat\x00video"
    assert result.stderr == b""


@pytest.mark.skipif(os.name != "nt", reason="Windows fallback regression")
def test_windows_fallback_reaps_descendant_without_pipe_close_delay(tmp_path):
    marker = tmp_path / "survived.txt"
    child_code = "import pathlib,sys,time;time.sleep(.8);pathlib.Path(sys.argv[1]).write_text('x')"
    parent_code = (
        "import subprocess,sys;subprocess.Popen([sys.executable,'-c',sys.argv[1],sys.argv[2]])"
    )

    class InactiveJob:
        active = False

        def __init__(self, _process):
            pass

        def terminate(self):
            raise AssertionError("inactive job must not be terminated")

        def close(self):
            pass

    runner = OwnedProcessRunner(poll_seconds=0.01, terminate_grace_seconds=0.2)
    snapshots = []
    original_snapshot = runner._windows_descendant_pids

    def record_snapshot(root_pids):
        descendants = original_snapshot(root_pids)
        snapshots.append((set(root_pids), descendants))
        return descendants

    started = time.monotonic()
    with (
        patch("cats_channel.adapters.process._WindowsJob", InactiveJob),
        patch.object(runner, "_windows_descendant_pids", side_effect=record_snapshot),
        patch.object(
            runner,
            "_terminate_windows_pids",
            wraps=runner._terminate_windows_pids,
        ) as terminate_descendants,
        patch(
            "cats_channel.adapters.process.subprocess.Popen.communicate",
            side_effect=AssertionError("Windows capture must not use pipe reader threads"),
        ),
    ):
        result = runner.run(
            [sys.executable, "-c", parent_code, child_code, str(marker)],
            timeout=0.3,
        )
    elapsed = time.monotonic() - started

    assert result.returncode == 0
    assert elapsed < 0.75
    assert terminate_descendants.call_count >= 1, snapshots
    time.sleep(0.9)
    assert not marker.exists(), (snapshots, terminate_descendants.call_args_list, elapsed)

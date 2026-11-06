"""CI runs the standalone diagnostic's network-free acceptance checks."""

import json
import subprocess
import sys
from pathlib import Path


def test_default_is_offline_self_check(tmp_path):
    script = Path(__file__).resolve().parents[1] / "tools" / "uush_diagnostic.py"
    evidence = tmp_path / "self-check.json"
    result = subprocess.run(
        [sys.executable, str(script), "--output", str(evidence)],
        capture_output=True,
        timeout=45,
        check=False,
    )
    assert result.returncode == 0, result.stdout
    assert result.stderr == b""
    assert evidence.read_bytes() == result.stdout
    assert len(result.stdout) <= 65536
    assert json.loads(result.stdout)["offline_self_check"] == "PASS"


def test_live_requires_explicit_operator_assertion():
    script = Path(__file__).resolve().parents[1] / "tools" / "uush_diagnostic.py"
    result = subprocess.run(
        [sys.executable, str(script), "--live"],
        capture_output=True,
        timeout=5,
        check=False,
    )
    assert result.returncode == 2
    assert b"requires Linux and --operator-authorized" in result.stderr

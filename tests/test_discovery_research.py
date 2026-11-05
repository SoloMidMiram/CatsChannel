"""Keep historical research fixtures compatible with the discovery DTOs."""

import runpy
import sys
from pathlib import Path


def test_offline_discovery_fixture_replay(monkeypatch):
    root = Path(__file__).resolve().parents[1]
    monkeypatch.setattr(sys, "path", sys.path.copy())
    runpy.run_path(str(root / "docs/discovery/fixtures/replay.py"), run_name="__main__")

"""Installed-distribution smoke tests independent of repository working directory."""

from __future__ import annotations

import importlib.metadata
import os
import subprocess
import sys
from pathlib import Path

import axis_memlab


def test_installed_import_and_console_entry_point(tmp_path: Path) -> None:
    assert axis_memlab.__version__ == "0.0.0"
    entries = importlib.metadata.distribution("axis-memory-lab").entry_points
    assert any(
        entry.name == "axis-memlab" and entry.value == "axis_memlab.cli:main" for entry in entries
    )
    result = subprocess.run(
        [sys.executable, "-m", "axis_memlab", "--version"],
        cwd=tmp_path,
        env=os.environ.copy(),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert result.stdout.strip() == "axis-memory-lab 0.0.0"
    script = subprocess.run(
        ["axis-memlab", "--version"],
        cwd=tmp_path,
        env=os.environ.copy(),
        capture_output=True,
        text=True,
        check=False,
    )
    assert script.returncode == 0
    assert script.stdout.strip() == "axis-memory-lab 0.0.0"


def test_distribution_does_not_require_private_device_modules() -> None:
    import axis_memlab.cli

    assert axis_memlab.cli.__file__ is not None

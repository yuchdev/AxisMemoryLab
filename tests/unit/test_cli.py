"""CLI scaffold contract tests."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from axis_memlab.cli import _PLANNED, build_parser, main


def test_help_and_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as help_result:
        build_parser().parse_args(["--help"])
    assert help_result.value.code == 0
    output = capsys.readouterr().out
    assert all(command in output for command in _PLANNED)
    with pytest.raises(SystemExit) as version_result:
        build_parser().parse_args(["--version"])
    assert version_result.value.code == 0
    assert "axis-memory-lab 0.0.0" in capsys.readouterr().out


@pytest.mark.parametrize("command", sorted(_PLANNED))
def test_planned_command_does_not_perform_work(
    command: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main([command]) == 3
    output = capsys.readouterr().err
    assert f"'{command}' is planned for milestone" in output
    assert "no " in output
    assert not (tmp_path / "runs").exists()


def test_bad_arguments_exit_two_without_traceback() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "axis_memlab", "config", "check"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert "usage:" in result.stderr
    assert "Traceback" not in result.stderr


def test_module_entry_point_runs() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "axis_memlab", "--version"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert result.stdout.strip() == "axis-memory-lab 0.0.0"

"""Offline configuration validation tests."""

from __future__ import annotations

import socket
import subprocess
from pathlib import Path

import pytest

from axis_memlab.config import load_config
from axis_memlab.errors import ConfigError

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    "name", ["default.toml", "lightweight.toml", "inapp-only.toml", "stress-lab.toml"]
)
def test_profiles_validate(name: str) -> None:
    config = load_config(ROOT / "configs" / name)
    assert config["collection"]["profile"] == name.removesuffix(".toml")


@pytest.mark.parametrize(
    ("contents", "message"),
    [
        ("[collection", "invalid TOML"),
        ('[collection]\nprofile="default"\n', "missing sections"),
    ],
)
def test_syntax_or_missing_sections_rejected(tmp_path: Path, contents: str, message: str) -> None:
    path = tmp_path / "bad.toml"
    path.write_text(contents)
    with pytest.raises(ConfigError, match=message):
        load_config(path)


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ("sample_interval_seconds = 15", 'sample_interval_seconds = "15"', "positive integer"),
        ("sample_interval_seconds = 15", "sample_interval_seconds = 0", "positive integer"),
        ('profile = "default"', 'profile = "default"\nunknown_setting = 1', "unknown"),
        ("allow_ptrace = false", "allow_ptrace = true", "unsupported"),
    ],
)
def test_bad_fields_rejected(tmp_path: Path, old: str, new: str, message: str) -> None:
    source = (ROOT / "configs/default.toml").read_text()
    path = tmp_path / "bad.toml"
    path.write_text(source.replace(old, new))
    with pytest.raises(ConfigError, match=message):
        load_config(path)


def test_missing_file_is_io_error() -> None:
    with pytest.raises(FileNotFoundError):
        load_config(ROOT / "configs/not-present.toml")


def test_invalid_encoding_is_reported_as_config_error(tmp_path: Path) -> None:
    path = tmp_path / "bad.toml"
    path.write_bytes(b"\xff")
    with pytest.raises(ConfigError, match="invalid TOML"):
        load_config(path)


def test_configuration_check_does_not_use_network_or_subprocess(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("configuration validation attempted external I/O")

    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    assert load_config(ROOT / "configs/default.toml")["collection"]["source"] == "host_ssh"


def test_cli_reports_missing_file_with_io_exit_code(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from axis_memlab.cli import main

    assert main(["config", "check", "--file", str(ROOT / "configs/not-present.toml")]) == 4
    assert "cannot read configuration file" in capsys.readouterr().err


def test_abort_threshold_must_be_below_trigger_threshold(tmp_path: Path) -> None:
    source = (ROOT / "configs/default.toml").read_text()
    path = tmp_path / "bad.toml"
    path.write_text(
        source.replace(
            "abort_mem_available_below_bytes = 16777216",
            "abort_mem_available_below_bytes = 33554432",
        )
    )
    with pytest.raises(ConfigError, match="abort_mem_available_below_bytes must be less"):
        load_config(path)

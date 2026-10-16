"""Offline TOML parsing and safety validation for scaffold profiles."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

from axis_memlab.errors import ConfigError

_SECTIONS = {"collection", "safety", "analysis", "privacy"}
_COLLECTION_POSITIVE = {
    "sample_interval_seconds",
    "smaps_rollup_interval_seconds",
    "max_snapshot_bytes",
    "max_snapshot_seconds",
    "transient_buffer_bytes",
    "deep_snapshot_cooldown_seconds",
    "trigger_pss_growth_bytes",
    "trigger_mem_available_below_bytes",
    "abort_mem_available_below_bytes",
    "ssh_connect_timeout_seconds",
    "ssh_command_timeout_seconds",
}
_SAFETY_FLAGS = {
    "allow_root",
    "allow_deep_snapshot",
    "allow_remote_commands_that_mutate",
    "capture_image_data",
    "capture_plate_text",
    "write_camera_flash",
    "allow_ptrace",
}
_PRIVACY_FLAGS = {
    "redact_device_identity",
    "redact_process_arguments",
    "local_artifacts_only",
    "exclude_raw_sensitive_data",
}
_ALLOWED = {
    "collection": _COLLECTION_POSITIVE | {"profile", "source"},
    "safety": _SAFETY_FLAGS,
    "analysis": {"warmup_seconds", "minimum_samples", "metrics", "normalization"},
    "privacy": _PRIVACY_FLAGS,
}
_PROFILE_NAMES = {"default", "lightweight", "inapp-only", "stress-lab"}
_SOURCES = {"host_ssh", "in_app"}


def _positive_int(value: Any, field: str, path: Path) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ConfigError(f"{path}: {field} must be a positive integer")


def load_config(path: str | Path) -> dict[str, Any]:
    """Load and validate one TOML configuration without device or subprocess I/O."""
    config_path = Path(path)
    try:
        with config_path.open("rb") as stream:
            data = tomllib.load(stream)
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
        raise ConfigError(f"{config_path}: invalid TOML: {exc}") from None
    if not isinstance(data, dict):
        raise ConfigError(f"{config_path}: document must be a TOML table")
    if set(data) != _SECTIONS:
        missing = sorted(_SECTIONS - set(data))
        extra = sorted(set(data) - _SECTIONS)
        details = []
        if missing:
            details.append(f"missing sections: {', '.join(missing)}")
        if extra:
            details.append(f"unknown sections: {', '.join(extra)}")
        raise ConfigError(f"{config_path}: {'; '.join(details)}")

    for section, allowed_fields in _ALLOWED.items():
        values = data[section]
        if not isinstance(values, dict):
            raise ConfigError(f"{config_path}: [{section}] must be a table")
        unknown = set(values) - allowed_fields
        missing_fields = allowed_fields - set(values)
        if unknown:
            key = sorted(unknown)[0]
            raise ConfigError(f"{config_path}: [{section}].{key} is unknown")
        if missing_fields:
            key = sorted(missing_fields)[0]
            raise ConfigError(f"{config_path}: [{section}].{key} is required")

    collection = data["collection"]
    profile = collection["profile"]
    if not isinstance(profile, str) or profile not in _PROFILE_NAMES:
        raise ConfigError(f"{config_path}: [collection].profile is not a documented profile")
    source = collection["source"]
    if not isinstance(source, str) or source not in _SOURCES:
        raise ConfigError(f"{config_path}: [collection].source must be host_ssh or in_app")
    for field in _COLLECTION_POSITIVE:
        _positive_int(collection[field], f"[collection].{field}", config_path)
    if collection["transient_buffer_bytes"] < collection["max_snapshot_bytes"]:
        raise ConfigError(
            f"{config_path}: [collection].transient_buffer_bytes must be at least "
            "[collection].max_snapshot_bytes"
        )
    if (
        collection["abort_mem_available_below_bytes"]
        >= collection["trigger_mem_available_below_bytes"]
    ):
        raise ConfigError(
            f"{config_path}: [collection].abort_mem_available_below_bytes must be less than "
            "[collection].trigger_mem_available_below_bytes"
        )

    for field in _SAFETY_FLAGS:
        if type(data["safety"][field]) is not bool:
            raise ConfigError(f"{config_path}: [safety].{field} must be a boolean")
        if data["safety"][field]:
            raise ConfigError(
                f"{config_path}: [safety].{field}=true is unsupported in scaffold milestone 0000"
            )
    analysis = data["analysis"]
    _positive_int(analysis["warmup_seconds"], "[analysis].warmup_seconds", config_path)
    _positive_int(analysis["minimum_samples"], "[analysis].minimum_samples", config_path)
    for field in ("metrics", "normalization"):
        if (
            not isinstance(analysis[field], list)
            or not analysis[field]
            or any(not isinstance(item, str) or not item for item in analysis[field])
        ):
            raise ConfigError(f"{config_path}: [analysis].{field} must be a nonempty string list")
    for field in _PRIVACY_FLAGS:
        if type(data["privacy"][field]) is not bool:
            raise ConfigError(f"{config_path}: [privacy].{field} must be a boolean")
        if not data["privacy"][field]:
            raise ConfigError(
                f"{config_path}: [privacy].{field}=false is unsupported in scaffold milestone 0000"
            )
    return data

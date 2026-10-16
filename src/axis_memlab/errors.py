"""Typed errors used by the scaffold's host-local operations."""


class ConfigError(ValueError):
    """A configuration file is syntactically valid but violates its contract."""


class FeatureUnavailableError(RuntimeError):
    """A command belongs to a later milestone and has not been implemented."""

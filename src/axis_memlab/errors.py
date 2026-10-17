"""Typed errors used by the scaffold's host-local operations."""


class ConfigError(ValueError):
    """A configuration file is syntactically valid but violates its contract."""


class FeatureUnavailableError(RuntimeError):
    """A command belongs to a later milestone and has not been implemented."""


class RunDataError(ValueError):
    """A run archive or report document is unreadable or violates its contract."""


class TransportError(RuntimeError):
    """The transport itself failed (for example SSH could not connect); retry with backoff."""


class CollectionError(RuntimeError):
    """A collection request is invalid or cannot proceed (bad selector, unsafe target)."""

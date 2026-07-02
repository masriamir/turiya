"""Typed exception hierarchy for turiya."""


class TuriyaError(Exception):
    """Base class for all turiya errors."""


class ConfigError(TuriyaError):
    """Configuration is missing, unreadable, or invalid."""


class KeychainError(TuriyaError):
    """The restic password could not be retrieved from or stored in the Keychain."""


class ResticError(TuriyaError):
    """A restic invocation failed."""


class RcloneError(TuriyaError):
    """An rclone invocation failed or a remote is missing."""


class SchedulingError(TuriyaError):
    """launchd/pmset scheduling setup failed."""

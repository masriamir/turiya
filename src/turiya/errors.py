"""Typed exception hierarchy for turiya."""


class ResticBackupError(Exception):
    """Base class for all turiya errors."""


class ConfigError(ResticBackupError):
    """Configuration is missing, unreadable, or invalid."""


class KeychainError(ResticBackupError):
    """The restic password could not be retrieved from or stored in the Keychain."""


class ResticError(ResticBackupError):
    """A restic invocation failed."""


class RcloneError(ResticBackupError):
    """An rclone invocation failed or a remote is missing."""


class SchedulingError(ResticBackupError):
    """launchd/pmset scheduling setup failed."""

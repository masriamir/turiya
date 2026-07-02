import pytest

from turiya.errors import (
    ConfigError,
    KeychainError,
    RcloneError,
    ResticBackupError,
    ResticError,
    SchedulingError,
)


@pytest.mark.parametrize(
    "exc",
    [ConfigError, KeychainError, ResticError, RcloneError, SchedulingError],
)
def test_subclasses_of_base(exc: type[ResticBackupError]) -> None:
    assert issubclass(exc, ResticBackupError)
    instance = exc("boom")
    assert str(instance) == "boom"
    assert isinstance(instance, ResticBackupError)

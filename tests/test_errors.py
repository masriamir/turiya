import pytest

from turiya.errors import (
    ConfigError,
    KeychainError,
    RcloneError,
    ResticError,
    SchedulingError,
    TuriyaError,
)


@pytest.mark.parametrize(
    "exc",
    [ConfigError, KeychainError, ResticError, RcloneError, SchedulingError],
)
def test_subclasses_of_base(exc: type[TuriyaError]) -> None:
    assert issubclass(exc, TuriyaError)
    instance = exc("boom")
    assert str(instance) == "boom"
    assert isinstance(instance, TuriyaError)

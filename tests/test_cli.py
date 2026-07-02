from pathlib import Path

import pytest
from typer.testing import CliRunner

from turiya.cli import app

runner = CliRunner()


def test_help_lists_subcommands() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for cmd in ("backup", "restore", "status", "query", "setup", "teardown"):
        assert cmd in result.stdout


def test_backup_runs_against_harness(harness_config: Path) -> None:
    result = runner.invoke(app, ["backup"])
    assert result.exit_code == 0


def test_query_mutual_exclusivity_exits_nonzero(harness_config: Path) -> None:
    result = runner.invoke(app, ["query", "--find", "x", "--since", "2020-01-01"])
    assert result.exit_code != 0


def test_backup_operation_error_exits_cleanly(
    monkeypatch: pytest.MonkeyPatch, harness_config: Path
) -> None:
    from turiya.errors import KeychainError
    from turiya.operations import backup as backup_op

    def _boom(*args: object, **kwargs: object) -> bool:
        raise KeychainError("no password")

    monkeypatch.setattr(backup_op, "run", _boom)
    result = runner.invoke(app, ["backup"])
    assert result.exit_code == 1
    assert not isinstance(result.exception, KeychainError)


def test_restore_operation_error_exits_cleanly(
    monkeypatch: pytest.MonkeyPatch, harness_config: Path
) -> None:
    from turiya.errors import ConfigError
    from turiya.operations import restore as restore_op

    def _boom(*args: object, **kwargs: object) -> bool:
        raise ConfigError("bad repo filter")

    monkeypatch.setattr(restore_op, "run", _boom)
    result = runner.invoke(app, ["restore", "--target", "/tmp/x", "--repo", "nope"])
    assert result.exit_code == 1
    assert not isinstance(result.exception, ConfigError)


def test_status_operation_error_exits_cleanly(
    monkeypatch: pytest.MonkeyPatch, harness_config: Path
) -> None:
    from turiya.errors import KeychainError
    from turiya.operations import status as status_op

    def _boom(*args: object, **kwargs: object) -> bool:
        raise KeychainError("no password")

    monkeypatch.setattr(status_op, "run", _boom)
    result = runner.invoke(app, ["status"])
    assert result.exit_code == 1
    assert not isinstance(result.exception, KeychainError)


def test_teardown_operation_error_exits_cleanly(
    monkeypatch: pytest.MonkeyPatch, harness_config: Path
) -> None:
    from turiya.errors import SchedulingError
    from turiya.operations import setup as setup_op

    def _boom(*args: object, **kwargs: object) -> None:
        raise SchedulingError("launchd failed")

    monkeypatch.setattr(setup_op, "teardown", _boom)
    result = runner.invoke(app, ["teardown"])
    assert result.exit_code == 1
    assert not isinstance(result.exception, SchedulingError)

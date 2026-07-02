from pathlib import Path

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

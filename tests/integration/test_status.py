from pathlib import Path

from turiya import config
from turiya.operations import backup, status


def test_status_all_lists_snapshots(harness_config: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    cfg = config.load()
    backup.run(cfg)
    assert status.run(cfg, mode="all") is True
    out = capsys.readouterr().out
    assert out.strip() != ""


def test_snapshot_matches_filters() -> None:
    paths = ["/Users/x/src/notes"]
    assert status.snapshot_matches(paths, pattern=("notes",), glob=(), exclude=()) is True
    assert status.snapshot_matches(paths, pattern=("photos",), glob=(), exclude=()) is False
    assert status.snapshot_matches(paths, pattern=(), glob=(), exclude=("notes",)) is False
    assert status.snapshot_matches(paths, pattern=(), glob=("notes",), exclude=()) is True

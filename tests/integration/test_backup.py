import json
from pathlib import Path

from turiya import config, restic
from turiya.operations import backup


def test_plain_backup_creates_snapshot(harness_config: Path) -> None:
    cfg = config.load()
    assert backup.run(cfg) is True
    snaps = restic.run_json(cfg.repos[0].url, ["snapshots"], password="testpass123")
    assert isinstance(snaps, list) and len(snaps) == 1


def test_glob_restricts_targets(harness_config: Path) -> None:
    cfg = config.load()
    assert backup.run(cfg, glob=("todo.md",)) is True
    snaps = restic.run_json(cfg.repos[0].url, ["snapshots"], password="testpass123")
    paths = snaps[-1]["paths"]  # type: ignore[index]
    assert any(p.endswith("todo.md") for p in paths)


def test_glob_no_match_returns_false(harness_config: Path) -> None:
    cfg = config.load()
    assert backup.run(cfg, glob=("*.nonexistent-xyz",)) is False


def test_backup_emits_valid_jsonl(harness_config: Path) -> None:
    cfg = config.load()
    backup.run(cfg)
    for line in (cfg.logging.dir / "backup.jsonl").read_text().splitlines():
        json.loads(line)  # must not raise

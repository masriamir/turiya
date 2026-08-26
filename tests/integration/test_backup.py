import json
from pathlib import Path
from typing import Any, cast

import pytest

from turiya import config, restic
from turiya.operations import backup


def test_plain_backup_creates_snapshot(harness_config: Path) -> None:
    cfg = config.load()
    assert backup.run(cfg) is True
    snaps = cast(
        list[dict[str, Any]],
        restic.run_json(cfg.repos[0].url, ["snapshots"], password="testpass123"),
    )
    assert len(snaps) == 1
    assert set(snaps[0]["paths"]) == {str(cfg.sources[0]), str(harness_config)}


def test_glob_restricts_targets(harness_config: Path) -> None:
    cfg = config.load()
    assert backup.run(cfg, glob=("todo.md",)) is True
    snaps = cast(
        list[dict[str, Any]],
        restic.run_json(cfg.repos[0].url, ["snapshots"], password="testpass123"),
    )
    paths = snaps[-1]["paths"]
    assert any(p.endswith("todo.md") for p in paths)
    assert str(harness_config) not in paths


def test_config_already_covered_by_source_is_not_added(
    harness_config: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg = config.load()
    monkeypatch.setattr(cfg, "_config_path", cfg.sources[0] / "config.toml")
    assert backup.resolve_targets(cfg, include=(), pattern=(), glob=()) == [str(cfg.sources[0])]


def test_glob_no_match_returns_false(harness_config: Path) -> None:
    cfg = config.load()
    assert backup.run(cfg, glob=("*.nonexistent-xyz",)) is False


def test_backup_emits_valid_jsonl(harness_config: Path) -> None:
    cfg = config.load()
    backup.run(cfg)
    for line in (cfg.logging.dir / "backup.jsonl").read_text().splitlines():
        json.loads(line)  # must not raise

import json
from pathlib import Path

import pytest

from turiya import config
from turiya.errors import ConfigError
from turiya.operations import backup, query


def test_find_locates_file(harness_config: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    cfg = config.load()
    backup.run(cfg)
    assert query.run(cfg, find="todo.md") is True
    assert "todo.md" in capsys.readouterr().out
    lines = [
        json.loads(line)
        for line in (cfg.logging.dir / "query.jsonl").read_text().splitlines()
    ]
    summary = next(x for x in lines if x["event"] == "summary")
    assert summary["mode"] == "find"
    assert summary["target"] == "todo.md"
    assert "match_count" in summary


def test_versions_emits_version_count(harness_config: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    cfg = config.load()
    backup.run(cfg)
    assert query.run(cfg, versions="todo.md") is True
    capsys.readouterr()
    lines = [
        json.loads(line)
        for line in (cfg.logging.dir / "query.jsonl").read_text().splitlines()
    ]
    summary = next(x for x in lines if x["event"] == "summary")
    assert summary["mode"] == "versions"
    assert summary["target"] == "todo.md"
    assert "version_count" in summary
    assert "match_count" not in summary


def test_since_past_lists(harness_config: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    cfg = config.load()
    backup.run(cfg)
    assert query.run(cfg, since="2020-01-01") is True
    assert capsys.readouterr().out.strip() != ""


def test_mutual_exclusivity(harness_config: Path) -> None:
    cfg = config.load()
    with pytest.raises(ConfigError):
        query.run(cfg, find="x", since="2020-01-01")

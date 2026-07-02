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


def test_since_past_lists(harness_config: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    cfg = config.load()
    backup.run(cfg)
    assert query.run(cfg, since="2020-01-01") is True
    assert capsys.readouterr().out.strip() != ""


def test_mutual_exclusivity(harness_config: Path) -> None:
    cfg = config.load()
    with pytest.raises(ConfigError):
        query.run(cfg, find="x", since="2020-01-01")

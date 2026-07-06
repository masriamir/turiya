from pathlib import Path

import pytest

from turiya import restic
from turiya.errors import ConfigError
from turiya.operations import recover_config


def test_run_writes_recovered_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    target = tmp_path / "config.toml"

    monkeypatch.setattr(
        restic, "find_path", lambda *a, **k: "/home/user/.config/turiya/config.toml"
    )
    monkeypatch.setattr(restic, "dump_file", lambda *a, **k: b"sources = []\n")

    assert recover_config.run(repo="repo", password="x", target=target) is True
    assert target.read_bytes() == b"sources = []\n"


def test_run_refuses_existing_target_without_force(tmp_path: Path) -> None:
    target = tmp_path / "config.toml"
    target.write_text("existing content")

    with pytest.raises(ConfigError, match="already exists"):
        recover_config.run(repo="repo", password="x", target=target)

    # refused before touching restic at all: original content untouched
    assert target.read_text() == "existing content"


def test_run_overwrites_existing_target_with_force(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    target = tmp_path / "config.toml"
    target.write_text("stale content")

    monkeypatch.setattr(restic, "find_path", lambda *a, **k: "/home/user/config.toml")
    monkeypatch.setattr(restic, "dump_file", lambda *a, **k: b"sources = ['fresh']\n")

    assert recover_config.run(repo="repo", password="x", target=target, force=True) is True
    assert target.read_bytes() == b"sources = ['fresh']\n"


def test_run_creates_parent_directories(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    target = tmp_path / "nested" / "dir" / "config.toml"

    monkeypatch.setattr(restic, "find_path", lambda *a, **k: "/x/config.toml")
    monkeypatch.setattr(restic, "dump_file", lambda *a, **k: b"sources = []\n")

    assert recover_config.run(repo="repo", password="x", target=target) is True
    assert target.exists()

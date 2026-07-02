from pathlib import Path

from turiya import config
from turiya.operations import backup, restore


def test_full_restore(harness_config: Path, tmp_path: Path) -> None:
    cfg = config.load()
    backup.run(cfg)
    out = tmp_path / "restore-out"
    assert restore.run(cfg, target=str(out)) is True
    files = list(out.rglob("*.txt")) + list(out.rglob("*.md"))
    assert any(f.name == "report.txt" for f in files)
    assert any(f.name == "todo.md" for f in files)


def test_glob_restore_one_file(harness_config: Path, tmp_path: Path) -> None:
    cfg = config.load()
    backup.run(cfg)
    out = tmp_path / "restore-glob"
    assert restore.run(cfg, target=str(out), glob=("todo.md",)) is True
    names = {f.name for f in out.rglob("*") if f.is_file()}
    assert "todo.md" in names
    assert "report.txt" not in names


def test_restore_bad_snapshot_returns_false(harness_config: Path, tmp_path: Path) -> None:
    cfg = config.load()
    backup.run(cfg)
    assert restore.run(cfg, snapshot="nonexistent", target=str(tmp_path / "x")) is False

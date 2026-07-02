from pathlib import Path

import pytest

from turiya import config
from turiya.errors import ConfigError

FIXTURE = Path(__file__).parent / "fixtures" / "valid_config.toml"


def test_load_valid_config() -> None:
    cfg = config.load(FIXTURE)
    assert cfg.identity.label == "com.example.turiya"
    assert cfg.keychain.account == "restic"
    assert [r.url for r in cfg.repos] == [
        "rclone:gdrive:turiya-backups",
        "rclone:dropbox:turiya-backups",
    ]
    assert len(cfg.schedules) == 1
    assert cfg.schedules[0].hour == 10
    assert cfg.retention.keep_daily == 7
    assert cfg.logging.max_bytes == 5242880
    assert cfg.logging.json_per_file is True


def test_paths_are_expanded() -> None:
    cfg = config.load(FIXTURE)
    assert cfg.sources[0] == Path.home() / "Documents"
    assert cfg.logging.dir == Path.home() / ".local/log/turiya"


def test_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TURIYA_CONFIG", str(FIXTURE))
    cfg = config.load()
    assert cfg.identity.label == "com.example.turiya"


def test_missing_file_raises_config_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="not found"):
        config.load(tmp_path / "does-not-exist.toml")


def test_empty_repos_rejected(tmp_path: Path) -> None:
    bad = tmp_path / "bad.toml"
    bad.write_text(
        '[identity]\nlabel="x"\n[keychain]\naccount="a"\nservice="s"\n'
        "[[schedule]]\nhour=1\nminute=0\n[power]\nwake_offset_minutes=5\n"
        'sources=["~/x"]\nexcludes=[]\n'
        "[retention]\nkeep_daily=1\nkeep_weekly=1\nkeep_monthly=1\nkeep_yearly=1\n"
        '[logging]\ndir="~/l"\nmax_bytes=1\njson_per_file=true\n'
    )
    with pytest.raises(ConfigError, match="repo"):
        config.load(bad)


def test_malformed_toml_raises_config_error(tmp_path: Path) -> None:
    bad = tmp_path / "broken.toml"
    bad.write_text("this is = = not valid toml")
    with pytest.raises(ConfigError):
        config.load(bad)

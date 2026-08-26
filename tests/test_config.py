import json
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from turiya import config
from turiya.errors import ConfigError

FIXTURE = Path(__file__).parent / "fixtures" / "valid_config.toml"

JSON_SCALAR = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(),
    st.floats(allow_nan=False, allow_infinity=False),
    st.text(max_size=80),
)
JSON_VALUE = st.recursive(
    JSON_SCALAR,
    lambda children: st.one_of(
        st.lists(children, max_size=4),
        st.dictionaries(st.text(max_size=30), children, max_size=4),
    ),
    max_leaves=12,
)


def _valid_config_data(
    *,
    weekday: int | None = 0,
    hour: int = 0,
    minute: int = 0,
    retention: int = 0,
    wake_offset_minutes: int = 0,
) -> dict[str, object]:
    return {
        "identity": {"label": "generated"},
        "keychain": {"account": "account", "service": "service"},
        "schedule": [{"weekday": weekday, "hour": hour, "minute": minute}],
        "repo": [{"url": "repo"}],
        "sources": ["~/generated"],
        "retention": {
            "keep_daily": retention,
            "keep_weekly": retention,
            "keep_monthly": retention,
            "keep_yearly": retention,
        },
        "power": {"wake_offset_minutes": wake_offset_minutes},
        "logging": {"dir": "~/logs", "max_bytes": 1},
    }


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


@given(st.binary(max_size=2048))
@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_load_arbitrary_bytes_returns_config_or_config_error(
    tmp_path: Path, contents: bytes
) -> None:
    generated = tmp_path / "generated.toml"
    generated.write_bytes(contents)

    try:
        result = config.load(generated)
    except ConfigError:
        return

    assert isinstance(result, config.Config)


@given(JSON_VALUE)
def test_config_validation_never_leaks_input_errors(raw: object) -> None:
    try:
        result = config.Config.model_validate(raw)
    except ValidationError:
        return

    assert isinstance(result, config.Config)


@given(
    weekday=st.one_of(st.none(), st.integers(min_value=0, max_value=6)),
    hour=st.integers(min_value=0, max_value=23),
    minute=st.integers(min_value=0, max_value=59),
    retention=st.integers(min_value=0),
    wake_offset_minutes=st.integers(min_value=0),
)
def test_config_accepts_generated_values_within_field_bounds(
    weekday: int | None,
    hour: int,
    minute: int,
    retention: int,
    wake_offset_minutes: int,
) -> None:
    result = config.Config.model_validate(
        _valid_config_data(
            weekday=weekday,
            hour=hour,
            minute=minute,
            retention=retention,
            wake_offset_minutes=wake_offset_minutes,
        )
    )

    assert result.schedules[0].weekday == weekday
    assert result.schedules[0].hour == hour
    assert result.schedules[0].minute == minute
    assert result.retention.keep_daily == retention
    assert result.power.wake_offset_minutes == wake_offset_minutes


@given(st.one_of(st.integers(max_value=-1), st.integers(min_value=24)))
def test_config_rejects_every_out_of_range_schedule_hour(hour: int) -> None:
    with pytest.raises(ValidationError):
        config.Config.model_validate(_valid_config_data(hour=hour))


@given(st.integers(max_value=-1))
def test_config_rejects_every_negative_retention_value(retention: int) -> None:
    with pytest.raises(ValidationError):
        config.Config.model_validate(_valid_config_data(retention=retention))


@given(st.integers())
@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_load_rejects_every_scalar_sources_value(tmp_path: Path, sources: int) -> None:
    generated = tmp_path / "invalid-sources.toml"
    generated.write_text(
        "\n".join(
            [
                f"sources = {json.dumps(sources)}",
                '[identity]\nlabel = "x"',
                '[keychain]\naccount = "a"\nservice = "s"',
                "[[schedule]]\nhour = 0\nminute = 0",
                '[[repo]]\nurl = "repo"',
                "[retention]\nkeep_daily = 0\nkeep_weekly = 0\nkeep_monthly = 0\nkeep_yearly = 0",
                '[logging]\ndir = "logs"',
            ]
        )
    )

    with pytest.raises(ConfigError):
        config.load(generated)

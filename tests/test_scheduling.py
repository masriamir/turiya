from pathlib import Path

from turiya import config, scheduling
from turiya.config import Schedule

FIXTURE = Path(__file__).parent / "fixtures" / "valid_config.toml"


def test_plist_label_uniqueness() -> None:
    cfg = config.load(FIXTURE)
    assert scheduling.plist_label(cfg, 0) == "com.example.turiya"
    assert scheduling.plist_label(cfg, 1) == "com.example.turiya.1"


def test_render_plist_includes_label_and_schedule() -> None:
    cfg = config.load(FIXTURE)
    xml = scheduling.render_plist(
        cfg,
        Schedule(weekday=0, hour=10, minute=0),
        label="com.example.turiya",
        program=["/opt/venv/bin/turiya", "backup"],
    )
    assert "<string>com.example.turiya</string>" in xml
    assert "<key>Weekday</key>" in xml
    assert "<integer>10</integer>" in xml  # hour
    assert "/opt/venv/bin/turiya" in xml


def test_render_plist_omits_weekday_when_none() -> None:
    cfg = config.load(FIXTURE)
    xml = scheduling.render_plist(
        cfg,
        Schedule(weekday=None, hour=3, minute=30),
        label="x",
        program=["turiya", "backup"],
    )
    assert "<key>Weekday</key>" not in xml
    assert "<key>Hour</key>" in xml


def test_earliest_wake_time_subtracts_offset() -> None:
    cfg = config.load(FIXTURE)  # single schedule 10:00, offset 5
    assert scheduling.earliest_wake_time(cfg) == (9, 55)

"""Render and install launchd schedules and the pmset wake (items 2 + 11)."""

from __future__ import annotations

import subprocess
from importlib.resources import files
from pathlib import Path
from string import Template
from xml.sax.saxutils import escape

from .config import Config, Schedule
from .errors import SchedulingError

_TEMPLATE = Template(
    (files("turiya") / "templates" / "launchd.plist.tmpl").read_text(encoding="utf-8")
)


def plist_label(cfg: Config, index: int) -> str:
    return cfg.identity.label if index == 0 else f"{cfg.identity.label}.{index}"


def render_plist(cfg: Config, schedule: Schedule, *, label: str, program: list[str]) -> str:
    program_args = "\n".join(f"        <string>{escape(arg)}</string>" for arg in program)
    cal_lines = []
    if schedule.weekday is not None:
        cal_lines.append(
            f"        <key>Weekday</key>\n        <integer>{schedule.weekday}</integer>"
        )
    cal_lines.append(f"        <key>Hour</key>\n        <integer>{schedule.hour}</integer>")
    cal_lines.append(f"        <key>Minute</key>\n        <integer>{schedule.minute}</integer>")
    return _TEMPLATE.substitute(
        label=escape(label),
        program_args=program_args,
        calendar="\n".join(cal_lines),
        stdout_path=escape(str(cfg.logging.dir / "launchd.log")),
        stderr_path=escape(str(cfg.logging.dir / "launchd-err.log")),
    )


def earliest_wake_time(cfg: Config) -> tuple[int, int]:
    earliest = min(cfg.schedules, key=lambda s: (s.hour, s.minute))
    total = earliest.hour * 60 + earliest.minute - cfg.power.wake_offset_minutes
    if total < 0:
        total = 0
    return total // 60, total % 60


def install(cfg: Config, *, program: list[str]) -> None:
    agents = Path("~/Library/LaunchAgents").expanduser()
    agents.mkdir(parents=True, exist_ok=True)
    for index, schedule in enumerate(cfg.schedules):
        label = plist_label(cfg, index)
        dest = agents / f"{label}.plist"
        dest.write_text(render_plist(cfg, schedule, label=label, program=program), encoding="utf-8")
        subprocess.run(["launchctl", "unload", str(dest)], capture_output=True, text=True)
        result = subprocess.run(["launchctl", "load", str(dest)], capture_output=True, text=True)
        if result.returncode != 0:
            raise SchedulingError(f"launchctl load failed for {label}: {result.stderr.strip()}")
    hour, minute = earliest_wake_time(cfg)
    result = subprocess.run(
        ["sudo", "pmset", "repeat", "wakeorpoweron", "MTWRFSU", f"{hour:02d}:{minute:02d}:00"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise SchedulingError(f"pmset schedule failed: {result.stderr.strip()}")


def uninstall(cfg: Config) -> None:
    agents = Path("~/Library/LaunchAgents").expanduser()
    for index in range(len(cfg.schedules)):
        label = plist_label(cfg, index)
        dest = agents / f"{label}.plist"
        if dest.exists():
            subprocess.run(["launchctl", "unload", str(dest)], capture_output=True, text=True)
            dest.unlink()
    subprocess.run(["sudo", "pmset", "repeat", "cancel"], check=False)

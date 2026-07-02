"""Structured JSON Lines logging plus human-readable logs (byte-compatible with v1.0.0)."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from .config import LoggingConfig


class StructuredLogger:
    def __init__(self, op: str, log_config: LoggingConfig) -> None:
        self.op = op
        self.json_per_file = log_config.json_per_file
        self._max_bytes = log_config.max_bytes
        log_config.dir.mkdir(parents=True, exist_ok=True)
        self.human = log_config.dir / f"{op}.log"
        self.jsonl = log_config.dir / f"{op}.jsonl"
        self.combined = log_config.dir / "ops.jsonl"
        for path in (self.human, self.jsonl, self.combined):
            self._rotate(path)

    def _rotate(self, path: Path) -> None:
        if path.exists() and path.stat().st_size > self._max_bytes:
            stamp = datetime.now().strftime("%Y%m%d%H%M%S")
            path.rename(path.with_name(f"{path.name}.{stamp}.bak"))

    def emit_event(self, *, repo: str | None, level: str, event: str, **fields: object) -> None:
        record: dict[str, object] = {
            "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
            "op": self.op,
            "repo": repo,
            "level": level,
            "event": event,
        }
        record.update(fields)
        line = json.dumps(record) + "\n"
        with self.jsonl.open("a") as fh:
            fh.write(line)
        with self.combined.open("a") as fh:
            fh.write(line)

    def log_human(self, message: str) -> None:
        stamped = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {message}"
        with self.human.open("a") as fh:
            fh.write(stamped + "\n")
        print(stamped)

    def run_start(self) -> None:
        self.emit_event(repo=None, level="info", event="run_start")

    def run_end(self, *, success: bool) -> None:
        self.emit_event(
            repo=None,
            level="info" if success else "error",
            event="run_end",
            status="success" if success else "failure",
        )

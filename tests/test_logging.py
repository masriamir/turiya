import json
import re
from pathlib import Path

from turiya.config import LoggingConfig
from turiya.logging import StructuredLogger


def _logcfg(tmp_path: Path, max_bytes: int = 5_000_000) -> LoggingConfig:
    return LoggingConfig(dir=tmp_path, max_bytes=max_bytes, json_per_file=True)


def test_emit_event_writes_both_files(tmp_path: Path) -> None:
    log = StructuredLogger("backup", _logcfg(tmp_path))
    log.emit_event(
        repo="rclone:gdrive:x", level="info", event="file", action="new", path="/a", size=12
    )
    for name in ("backup.jsonl", "ops.jsonl"):
        line = (tmp_path / name).read_text().strip()
        obj = json.loads(line)
        assert obj["op"] == "backup"
        assert obj["repo"] == "rclone:gdrive:x"
        assert obj["event"] == "file"
        assert obj["action"] == "new"
        assert obj["size"] == 12
        assert "ts" in obj
        # v1.0.0 byte-compatibility: `date '+%Y-%m-%dT%H:%M:%S%z'` has no colon in the tz offset.
        assert re.search(r"-\d{4}$|\+\d{4}$", obj["ts"]), obj["ts"]


def test_repo_none_serializes_as_null(tmp_path: Path) -> None:
    log = StructuredLogger("status", _logcfg(tmp_path))
    log.emit_event(repo=None, level="info", event="run_start")
    obj = json.loads((tmp_path / "status.jsonl").read_text().strip())
    assert obj["repo"] is None


def test_human_log_is_plaintext(tmp_path: Path) -> None:
    log = StructuredLogger("backup", _logcfg(tmp_path))
    log.log_human("hello world")
    content = (tmp_path / "backup.log").read_text().strip()
    assert content.endswith("hello world")
    assert content.startswith("[")


def test_rotation_when_over_max_bytes(tmp_path: Path) -> None:
    existing = tmp_path / "backup.jsonl"
    tmp_path.mkdir(exist_ok=True)
    existing.write_text("x" * 100)
    StructuredLogger("backup", _logcfg(tmp_path, max_bytes=50))
    backups = list(tmp_path.glob("backup.jsonl.*.bak"))
    assert len(backups) == 1
    assert not existing.exists()


def test_run_start_and_end(tmp_path: Path) -> None:
    log = StructuredLogger("query", _logcfg(tmp_path))
    log.run_start()
    log.run_end(success=False)
    lines = [json.loads(x) for x in (tmp_path / "query.jsonl").read_text().splitlines()]
    assert lines[0]["event"] == "run_start"
    assert lines[-1]["event"] == "run_end"
    assert lines[-1]["level"] == "error"
    assert lines[-1]["status"] == "failure"

"""Run restic via subprocess and parse its --json output into typed events."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field

from .errors import ResticError


@dataclass
class FileEvent:
    action: str
    path: str
    size: int


@dataclass
class SummaryEvent:
    data: dict[str, object] = field(default_factory=dict)


@dataclass
class ErrorEvent:
    message: str


ResticEvent = FileEvent | SummaryEvent | ErrorEvent


def parse_event(line: str) -> ResticEvent | None:
    line = line.strip()
    if not line:
        return None
    try:
        obj = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(obj, dict):
        return None
    mtype = obj.get("message_type")
    if mtype == "verbose_status":
        action = str(obj.get("action", "unknown"))
        if action == "scan_finished":
            return None
        size_raw = obj.get("data_size", obj.get("size", 0))
        size = int(size_raw) if isinstance(size_raw, int | float) else 0
        return FileEvent(action=action, path=str(obj.get("item", "")), size=size)
    if mtype == "summary":
        return SummaryEvent(data=obj)
    if mtype in ("error", "exit_error"):
        message = obj.get("message")
        if not isinstance(message, str):
            err = obj.get("error")
            message = err.get("message") if isinstance(err, dict) else "unknown restic error"
        return ErrorEvent(message=str(message))
    return None


def _env(password: str) -> dict[str, str]:
    import os

    env = os.environ.copy()
    env["RESTIC_PASSWORD"] = password
    return env


def stream(
    repo: str,
    args: Sequence[str],
    *,
    password: str,
    dry_run: bool = False,
) -> Iterator[ResticEvent]:
    cmd = ["restic", "-r", repo, *args, "--json", "--verbose=2"]
    if dry_run:
        cmd.append("--dry-run")
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=_env(password),
    )
    saw_error = False
    assert proc.stdout is not None
    try:
        for line in proc.stdout:
            event = parse_event(line)
            if event is None:
                continue
            if isinstance(event, ErrorEvent):
                saw_error = True
            yield event
        code = proc.wait()
        if code != 0 and not saw_error:
            yield ErrorEvent(message=f"restic exited with status {code}")
    finally:
        # If the consumer abandoned iteration early (GeneratorExit) the child
        # is still running and blocked writing to an unread pipe — terminate it.
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
        if proc.stdout is not None:
            proc.stdout.close()


def run_json(repo: str, args: Sequence[str], *, password: str) -> object:
    cmd = ["restic", "-r", repo, *args, "--json"]
    result = subprocess.run(cmd, capture_output=True, text=True, env=_env(password))
    if result.returncode != 0:
        message = f"restic exited with status {result.returncode}"
        for line in (result.stderr + result.stdout).splitlines():
            event = parse_event(line)
            if isinstance(event, ErrorEvent):
                message = event.message
                break
        raise ResticError(message)
    return json.loads(result.stdout)

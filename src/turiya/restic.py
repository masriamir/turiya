"""Run restic via subprocess and parse its --json output into typed events."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Generator, Sequence
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
) -> Generator[ResticEvent]:
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
    try:
        if proc.stdout is None:  # defensive: PIPE requested above, unreachable in practice
            raise ResticError("restic produced no output stream")
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


def _error_message(result: subprocess.CompletedProcess[str]) -> str:
    for line in (result.stderr + result.stdout).splitlines():
        event = parse_event(line)
        if isinstance(event, ErrorEvent):
            return event.message
    return f"restic exited with status {result.returncode}"


def run_json(repo: str, args: Sequence[str], *, password: str) -> object:
    cmd = ["restic", "-r", repo, *args, "--json"]
    result = subprocess.run(cmd, capture_output=True, text=True, env=_env(password))
    if result.returncode != 0:
        raise ResticError(_error_message(result))
    return json.loads(result.stdout)


def find_path(repo: str, snapshot: str, *, password: str, name: str) -> str:
    # No --recursive: restic already lists the full tree recursively when no
    # path-filter arguments are given (verified against a real repo) — the
    # flag only matters when scoping to specific directories.
    cmd = ["restic", "-r", repo, "ls", snapshot, "--json"]
    result = subprocess.run(cmd, capture_output=True, text=True, env=_env(password))
    if result.returncode != 0:
        raise ResticError(_error_message(result))
    matches: list[str] = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if (
            isinstance(obj, dict)
            and obj.get("message_type") == "node"
            and obj.get("type") == "file"
            and obj.get("name") == name
        ):
            path = obj.get("path")
            if isinstance(path, str):
                matches.append(path)
    if not matches:
        raise ResticError(f"no file named '{name}' found in {repo}'s {snapshot} snapshot")
    if len(matches) > 1:
        raise ResticError(
            f"multiple files named '{name}' found in {repo}'s {snapshot} snapshot: {matches}"
        )
    return matches[0]


def dump_file(repo: str, snapshot: str, path: str, *, password: str) -> bytes:
    cmd = ["restic", "-r", repo, "dump", snapshot, path]
    result = subprocess.run(cmd, capture_output=True, env=_env(password))
    if result.returncode != 0:
        stderr_text = result.stderr.decode(errors="replace").strip()
        raise ResticError(stderr_text or f"restic dump exited with status {result.returncode}")
    return result.stdout

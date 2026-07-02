"""Backup operation: port of v1.0.0 backup.sh."""

from __future__ import annotations

import subprocess
from collections.abc import Sequence
from typing import Any, cast

from ..config import Config
from ..keychain import get_password
from ..logging import StructuredLogger
from ..restic import ErrorEvent, FileEvent, SummaryEvent, run_json, stream


def _find(source: str, flag: str, value: str) -> list[str]:
    result = subprocess.run(
        ["find", source, flag, value], capture_output=True, text=True
    )
    return [line for line in result.stdout.splitlines() if line]


def resolve_targets(
    cfg: Config,
    *,
    include: Sequence[str],
    pattern: Sequence[str],
    glob: Sequence[str],
) -> list[str] | None:
    """Return target paths, or None if a pattern/glob/include matched nothing."""
    if not (include or pattern or glob):
        return [str(s) for s in cfg.sources]
    targets: list[str] = []
    for path in include:
        from pathlib import Path

        if not Path(path).exists():
            return None
        targets.append(path)
    for pat in pattern:
        matches = [m for s in cfg.sources for m in _find(str(s), "-path", f"*{pat}*")]
        if not matches:
            return None
        targets.extend(matches)
    for g in glob:
        matches = [m for s in cfg.sources for m in _find(str(s), "-name", g)]
        if not matches:
            return None
        targets.extend(matches)
    return targets


def run(
    cfg: Config,
    *,
    dry_run: bool = False,
    include: Sequence[str] = (),
    pattern: Sequence[str] = (),
    glob: Sequence[str] = (),
    exclude: Sequence[str] = (),
) -> bool:
    log = StructuredLogger("backup", cfg.logging)
    log.run_start()
    password = get_password(cfg)

    targets = resolve_targets(cfg, include=include, pattern=pattern, glob=glob)
    if targets is None:
        log.log_human("ERROR: include/pattern/glob matched no files.")
        log.run_end(success=False)
        return False

    exclude_flags = [f"--exclude={p}" for p in (*cfg.excludes, *exclude)]
    retention = [
        "--keep-daily", str(cfg.retention.keep_daily),
        "--keep-weekly", str(cfg.retention.keep_weekly),
        "--keep-monthly", str(cfg.retention.keep_monthly),
        "--keep-yearly", str(cfg.retention.keep_yearly),
    ]

    overall = True
    for repo in cfg.repos:
        url = repo.url
        log.log_human(f"--- Repository: {url} ---")
        repo_ok = True
        for event in stream(
            url, ["backup", *targets, *exclude_flags], password=password, dry_run=dry_run
        ):
            if isinstance(event, FileEvent):
                if log.json_per_file:
                    log.emit_event(repo=url, level="info", event="file",
                                   action=event.action, path=event.path, size=event.size)
                log.log_human(f"{event.action} {event.path}")
            elif isinstance(event, SummaryEvent):
                log.emit_event(repo=url, level="info", event="summary", **event.data)
            elif isinstance(event, ErrorEvent):
                repo_ok = False
                log.emit_event(repo=url, level="error", event="error", message=event.message)
                log.log_human(f"ERROR: {event.message}")
        if repo_ok and not dry_run:
            try:
                result = cast(
                    list[dict[str, Any]],
                    run_json(url, ["forget", *retention, "--prune"], password=password),
                )
                removed_count = sum(len(obj.get("remove") or []) for obj in result)
                log.emit_event(
                    repo=url, level="info", event="prune", removed_count=removed_count
                )
            except Exception as exc:  # noqa: BLE001
                log.emit_event(repo=url, level="warn", event="prune", message=str(exc))
        overall = overall and repo_ok

    log.run_end(success=overall)
    return overall

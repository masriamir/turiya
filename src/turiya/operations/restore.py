"""Restore operation: port of v1.0.0 restore.sh."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from ..config import Config
from ..errors import ConfigError
from ..keychain import get_password
from ..logging import StructuredLogger
from ..restic import ErrorEvent, FileEvent, SummaryEvent, stream


def resolve_repo(cfg: Config, repo_filter: str | None) -> str:
    if repo_filter:
        for repo in cfg.repos:
            if repo_filter in repo.url:
                return repo.url
        raise ConfigError(f"No repo matching '{repo_filter}' in config.")
    return cfg.repos[0].url


def run(
    cfg: Config,
    *,
    repo: str | None = None,
    snapshot: str = "latest",
    target: str,
    include: Sequence[str] = (),
    pattern: Sequence[str] = (),
    glob: Sequence[str] = (),
    exclude: Sequence[str] = (),
) -> bool:
    log = StructuredLogger("restore", cfg.logging)
    log.run_start()
    password = get_password(cfg)
    url = resolve_repo(cfg, repo)
    Path(target).mkdir(parents=True, exist_ok=True)

    args = ["restore", snapshot, "--target", target]
    for pat in (*include, *pattern, *glob):
        args += ["--include", pat]
    for pat in exclude:
        args += ["--exclude", pat]

    ok = True
    for event in stream(url, args, password=password):
        if isinstance(event, FileEvent):
            if log.json_per_file:
                log.emit_event(
                    repo=url,
                    level="info",
                    event="file",
                    action=event.action,
                    path=event.path,
                    size=event.size,
                )
            log.log_human(f"{event.action} {event.path}")
        elif isinstance(event, SummaryEvent):
            log.emit_event(repo=url, level="info", event="summary", **event.data)
        elif isinstance(event, ErrorEvent):
            ok = False
            log.emit_event(repo=url, level="error", event="error", message=event.message)
            log.log_human(f"ERROR: {event.message}")

    log.run_end(success=ok)
    return ok

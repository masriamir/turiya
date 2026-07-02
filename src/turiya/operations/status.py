"""Status operation: port of v1.0.0 status.sh."""

from __future__ import annotations

import fnmatch
from collections.abc import Sequence
from pathlib import PurePath
from typing import Any, cast

from ..config import Config
from ..errors import ResticError
from ..keychain import get_password
from ..logging import StructuredLogger
from ..restic import run_json


def snapshot_matches(
    paths: list[str],
    *,
    pattern: Sequence[str],
    glob: Sequence[str],
    exclude: Sequence[str],
) -> bool:
    if pattern or glob:
        keep = False
        for p in paths:
            if any(pat in p for pat in pattern):
                keep = True
            if any(fnmatch.fnmatch(PurePath(p).name, g) for g in glob):
                keep = True
        if not keep:
            return False
    for p in paths:
        name_matches = any(fnmatch.fnmatch(PurePath(p).name, ex) for ex in exclude)
        if any(ex in p for ex in exclude) or name_matches:
            return False
    return True


def run(
    cfg: Config,
    *,
    mode: str = "latest",
    include: Sequence[str] = (),
    pattern: Sequence[str] = (),
    glob: Sequence[str] = (),
    exclude: Sequence[str] = (),
) -> bool:
    log = StructuredLogger("status", cfg.logging)
    log.run_start()
    password = get_password(cfg)
    overall = True

    for repo in cfg.repos:
        url = repo.url
        print(f"\n=== {url} ===")
        if mode == "check":
            try:
                run_json(url, ["check"], password=password)
                log.emit_event(repo=url, level="info", event="summary", check="ok")
            except ResticError as exc:
                overall = False
                log.emit_event(repo=url, level="error", event="error", message=str(exc))
            continue

        args = ["snapshots"]
        for path in include:
            args += ["--path", path]
        if mode == "latest":
            args += ["--latest", "1"]
        try:
            snaps = cast(list[dict[str, Any]], run_json(url, args, password=password))
        except ResticError as exc:
            overall = False
            log.emit_event(repo=url, level="error", event="error", message=str(exc))
            continue

        for snap in snaps:
            paths = [str(p) for p in snap.get("paths", [])]
            if not snapshot_matches(paths, pattern=pattern, glob=glob, exclude=exclude):
                continue
            short = str(snap.get("short_id", ""))
            when = str(snap.get("time", ""))
            print(f"  {short}  {when}  {', '.join(paths)}")
            log.emit_event(repo=url, level="info", event="summary", snapshot_id=short, time=when)

    log.run_end(success=overall)
    return overall

"""Query operation: port of v1.0.0 query.sh."""

from __future__ import annotations

import json
from typing import Any, cast

from ..config import Config
from ..errors import ConfigError, ResticError
from ..keychain import get_password
from ..logging import StructuredLogger
from ..restic import run_json
from .restore import resolve_repo


def run(
    cfg: Config,
    *,
    repo: str | None = None,
    since: str | None = None,
    until: str | None = None,
    find: str | None = None,
    versions: str | None = None,
    json_output: bool = False,
) -> bool:
    modes = [bool(since or until), bool(find), bool(versions)]
    if sum(modes) != 1:
        raise ConfigError("Specify exactly one of --since/--until, --find, or --versions.")

    log = StructuredLogger("query", cfg.logging)
    log.run_start()
    password = get_password(cfg)
    repos = [resolve_repo(cfg, repo)] if repo else [r.url for r in cfg.repos]

    overall = True
    for url in repos:
        try:
            if since or until:
                snaps = cast(list[dict[str, Any]], run_json(url, ["snapshots"], password=password))
                rows = [
                    s for s in snaps
                    if (not since or str(s.get("time", "")) >= since)
                    and (not until or str(s.get("time", "")) <= until)
                ]
                log.emit_event(
                    repo=url, level="info", event="summary",
                    mode="date_range", match_count=len(rows),
                )
                _print_snaps(url, rows, json_output)
            else:
                target = find or versions
                args = ["find", cast(str, target)]
                if versions:
                    args.append("--reverse")
                result = cast(list[dict[str, Any]], run_json(url, args, password=password))
                matches = [m for entry in result for m in entry.get("matches", [])]
                if find:
                    log.emit_event(
                        repo=url, level="info", event="summary",
                        mode="find", target=target, match_count=len(matches),
                    )
                else:
                    log.emit_event(
                        repo=url, level="info", event="summary",
                        mode="versions", target=target, version_count=len(matches),
                    )
                _print_finds(url, result, json_output)
        except ResticError as exc:
            overall = False
            log.emit_event(repo=url, level="error", event="error", message=str(exc))
            print(f"ERROR: query on {url} failed: {exc}")

    log.run_end(success=overall)
    return overall


def _print_snaps(url: str, rows: list[dict[str, Any]], json_output: bool) -> None:
    if json_output:
        print(json.dumps(rows))
        return
    print(f"\n--- {url} ---")
    for s in rows:
        paths = ", ".join(str(p) for p in s.get("paths", []))
        print(f"  {s.get('short_id', '')}  {s.get('time', '')}  {paths}")


def _print_finds(url: str, result: list[dict[str, Any]], json_output: bool) -> None:
    if json_output:
        print(json.dumps(result))
        return
    for entry in result:
        snap = entry.get("snapshot", "")
        for m in entry.get("matches", []):
            print(f"  {snap}  {m.get('path', '')}  {m.get('size', 0)} bytes  {m.get('mtime', '')}")

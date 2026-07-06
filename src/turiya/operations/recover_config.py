"""Bootstrap recovery: restore config.toml from a snapshot given only a repo URL + password.

No existing config.toml is required to run this — it's the one operation in
this codebase that intentionally does not take a Config or use
StructuredLogger, because its entire purpose is to run before a Config can
be loaded. See docs/superpowers/specs/2026-07-05-recover-config-bootstrap-design.md.
"""

from __future__ import annotations

from pathlib import Path

from .. import restic
from ..errors import ConfigError


def run(*, repo: str, password: str, target: Path, force: bool = False) -> bool:
    if target.exists() and not force:
        raise ConfigError(
            f"{target} already exists; pass --force to overwrite with the recovered version."
        )
    path = restic.find_path(repo, "latest", password=password, name="config.toml")
    content = restic.dump_file(repo, "latest", path, password=password)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    print(f"Recovered {target} from {repo} (latest snapshot).")
    return True

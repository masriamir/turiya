"""Setup/teardown wiring: port of v1.0.0 install.sh / uninstall.sh."""

from __future__ import annotations

import subprocess
import sys

from .. import keychain, rclone, scheduling
from ..config import Config
from ..errors import RcloneError, ResticError
from ..restic import run_json


def default_program() -> list[str]:
    return [sys.executable, "-m", "turiya", "backup"]


def _repo_initialized(url: str, password: str) -> bool:
    try:
        run_json(url, ["snapshots"], password=password)
        return True
    except ResticError:
        return False


def run(cfg: Config, *, password: str | None = None, program: list[str] | None = None) -> None:
    if password is not None:
        keychain.set_password(cfg, password)
    resolved_password = keychain.get_password(cfg)

    missing = rclone.missing_remotes(cfg)
    if missing:
        raise RcloneError(
            f"rclone remotes not configured: {', '.join(missing)}. Run `rclone config`."
        )

    import os

    env = {**os.environ, "RESTIC_PASSWORD": resolved_password}
    for repo in cfg.repos:
        if not _repo_initialized(repo.url, resolved_password):
            result = subprocess.run(
                ["restic", "-r", repo.url, "init"], capture_output=True, text=True, env=env
            )
            if result.returncode != 0:
                raise ResticError(f"Failed to init repo {repo.url}: {result.stderr.strip()}")

    scheduling.install(cfg, program=program or default_program())


def teardown(cfg: Config) -> None:
    scheduling.uninstall(cfg)

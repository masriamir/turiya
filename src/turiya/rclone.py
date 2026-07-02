"""Verify that the rclone remotes referenced by the config exist."""

from __future__ import annotations

import subprocess

from .config import Config
from .errors import RcloneError


def list_remotes() -> list[str]:
    result = subprocess.run(["rclone", "listremotes"], capture_output=True, text=True)
    if result.returncode != 0:
        raise RcloneError(f"`rclone listremotes` failed: {result.stderr.strip()}")
    return [line.rstrip(":") for line in result.stdout.splitlines() if line.strip()]


def remote_of(repo_url: str) -> str | None:
    if not repo_url.startswith("rclone:"):
        return None
    rest = repo_url[len("rclone:") :]
    name, _, _ = rest.partition(":")
    return name or None


def missing_remotes(cfg: Config) -> list[str]:
    available = set(list_remotes())
    missing: list[str] = []
    for repo in cfg.repos:
        name = remote_of(repo.url)
        if name is not None and name not in available and name not in missing:
            missing.append(name)
    return missing

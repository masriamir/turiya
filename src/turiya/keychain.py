"""Retrieve and manage the restic repository password via the macOS Keychain."""

from __future__ import annotations

import os
import subprocess

from .config import Config
from .errors import KeychainError


def get_password(cfg: Config) -> str:
    env = os.environ.get("RESTIC_PASSWORD")
    if env:
        return env
    result = subprocess.run(
        [
            "security",
            "find-generic-password",
            "-a",
            cfg.keychain.account,
            "-s",
            cfg.keychain.service,
            "-w",
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise KeychainError(
            "Could not retrieve the restic password from the Keychain. "
            "Run `turiya setup`, or check keychain.account/keychain.service "
            f"in the config. (security exit {result.returncode})"
        )
    return result.stdout.strip()


def set_password(cfg: Config, password: str) -> None:
    result = subprocess.run(
        [
            "security",
            "add-generic-password",
            "-a",
            cfg.keychain.account,
            "-s",
            cfg.keychain.service,
            "-w",
            password,
            # Allow silent (non-interactive) reads: the scheduled backup fetches
            # this from a LaunchAgent with no one present to answer a prompt.
            "-A",
            # Update in place if the item already exists, so re-running `turiya
            # setup` (e.g. to pick up a new -A flag) is idempotent.
            "-U",
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise KeychainError(f"Failed to store password in the Keychain: {result.stderr.strip()}")


def delete_password(cfg: Config) -> None:
    subprocess.run(
        [
            "security",
            "delete-generic-password",
            "-a",
            cfg.keychain.account,
            "-s",
            cfg.keychain.service,
        ],
        capture_output=True,
        text=True,
    )

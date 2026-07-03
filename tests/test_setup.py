import subprocess
from pathlib import Path

import pytest

from turiya import config
from turiya.errors import RcloneError, SchedulingError
from turiya.operations import setup

FIXTURE = Path(__file__).parent / "fixtures" / "valid_config.toml"


def test_default_program_resolves_uv_tool_bin(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    shim = bin_dir / "turiya"
    shim.write_text("#!/bin/sh\n")

    def _fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        assert cmd == ["uv", "tool", "dir", "--bin"]
        return subprocess.CompletedProcess(cmd, 0, stdout=f"{bin_dir}\n", stderr="")

    monkeypatch.setattr(subprocess, "run", _fake_run)
    assert setup.default_program() == [str(shim), "backup"]


def test_default_program_falls_back_to_local_bin_when_uv_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    bin_dir = tmp_path / ".local" / "bin"
    bin_dir.mkdir(parents=True)
    shim = bin_dir / "turiya"
    shim.write_text("#!/bin/sh\n")

    def _boom(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        raise FileNotFoundError("uv not found")

    monkeypatch.setattr(subprocess, "run", _boom)
    assert setup.default_program() == [str(shim), "backup"]


def test_default_program_raises_when_shim_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()

    def _fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(cmd, 0, stdout=f"{bin_dir}\n", stderr="")

    monkeypatch.setattr(subprocess, "run", _fake_run)
    with pytest.raises(SchedulingError, match="not installed"):
        setup.default_program()


def test_setup_raises_on_missing_remotes(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = config.load(FIXTURE)
    # Avoid touching the real macOS Keychain: get_password() short-circuits on this env var.
    monkeypatch.setenv("RESTIC_PASSWORD", "irrelevant")
    monkeypatch.setattr("turiya.operations.setup.rclone.missing_remotes", lambda c: ["dropbox"])

    with pytest.raises(RcloneError, match="dropbox"):
        setup.run(cfg, program=["x"])

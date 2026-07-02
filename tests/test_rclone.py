import subprocess
from pathlib import Path

import pytest

from turiya import config, rclone

FIXTURE = Path(__file__).parent / "fixtures" / "valid_config.toml"


def test_remote_of_extracts_name() -> None:
    assert rclone.remote_of("rclone:gdrive:turiya-backups") == "gdrive"
    assert rclone.remote_of("/local/path") is None


def test_list_remotes_parses_output(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake(cmd: list[str], **k: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(cmd, 0, stdout="gdrive:\ndropbox:\n", stderr="")

    monkeypatch.setattr(subprocess, "run", _fake)
    assert rclone.list_remotes() == ["gdrive", "dropbox"]


def test_missing_remotes(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake(cmd: list[str], **k: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(cmd, 0, stdout="gdrive:\n", stderr="")

    monkeypatch.setattr(subprocess, "run", _fake)
    assert rclone.missing_remotes(config.load(FIXTURE)) == ["dropbox"]

import subprocess
from pathlib import Path

import pytest

from turiya import config, keychain
from turiya.errors import KeychainError

FIXTURE = Path(__file__).parent / "fixtures" / "valid_config.toml"


def _cfg() -> config.Config:
    return config.load(FIXTURE)


def test_env_password_short_circuits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RESTIC_PASSWORD", "from-env")

    def _boom(*a: object, **k: object) -> object:
        raise AssertionError("security must not be called when RESTIC_PASSWORD is set")

    monkeypatch.setattr(subprocess, "run", _boom)
    assert keychain.get_password(_cfg()) == "from-env"


def test_get_password_from_security(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RESTIC_PASSWORD", raising=False)
    calls: list[list[str]] = []

    def _fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="secret\n", stderr="")

    monkeypatch.setattr(subprocess, "run", _fake_run)
    assert keychain.get_password(_cfg()) == "secret"
    assert calls[0][0] == "security"
    assert "find-generic-password" in calls[0]


def test_get_password_failure_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RESTIC_PASSWORD", raising=False)

    def _fail(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(cmd, 44, stdout="", stderr="not found")

    monkeypatch.setattr(subprocess, "run", _fail)
    with pytest.raises(KeychainError, match="Keychain"):
        keychain.get_password(_cfg())

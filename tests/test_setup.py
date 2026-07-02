import sys
from pathlib import Path

from turiya import config
from turiya.operations import setup

FIXTURE = Path(__file__).parent / "fixtures" / "valid_config.toml"


def test_default_program_uses_module_entry() -> None:
    prog = setup.default_program()
    assert prog[0] == sys.executable
    assert prog[1:3] == ["-m", "turiya"]
    assert prog[-1] == "backup"


def test_setup_raises_on_missing_remotes(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    cfg = config.load(FIXTURE)
    # Avoid touching the real macOS Keychain: get_password() short-circuits on this env var.
    monkeypatch.setenv("RESTIC_PASSWORD", "irrelevant")
    monkeypatch.setattr("turiya.operations.setup.rclone.missing_remotes", lambda c: ["dropbox"])
    import pytest

    from turiya.errors import RcloneError

    with pytest.raises(RcloneError, match="dropbox"):
        setup.run(cfg, program=["x"])

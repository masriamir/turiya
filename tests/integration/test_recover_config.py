import os
import subprocess
from pathlib import Path

import pytest

from turiya.errors import ResticError
from turiya.operations import recover_config

from ..conftest import PASSWORD


def _backup_fake_config(repo: Path, config_path: Path) -> None:
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text('sources = ["~/Documents"]\n')
    env = {**os.environ, "RESTIC_PASSWORD": PASSWORD}
    subprocess.run(
        ["restic", "-r", str(repo), "backup", str(config_path)],
        check=True,
        capture_output=True,
        env=env,
    )


def test_recover_config_restores_real_snapshot(restic_repos: list[Path], tmp_path: Path) -> None:
    repo = restic_repos[0]
    source_config = tmp_path / "source-home" / ".config" / "turiya" / "config.toml"
    _backup_fake_config(repo, source_config)

    recovered_target = tmp_path / "recovered" / "config.toml"
    ok = recover_config.run(repo=str(repo), password=PASSWORD, target=recovered_target)
    assert ok is True
    assert recovered_target.read_text() == 'sources = ["~/Documents"]\n'


def test_recover_config_raises_when_repo_has_no_config(
    restic_repos: list[Path], tmp_path: Path
) -> None:
    repo = restic_repos[1]  # initialized but nothing ever backed up to it
    with pytest.raises(ResticError):
        recover_config.run(repo=str(repo), password=PASSWORD, target=tmp_path / "config.toml")

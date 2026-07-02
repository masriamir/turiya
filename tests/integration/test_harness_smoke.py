from pathlib import Path

from turiya import config, restic


def test_harness_repos_are_empty(harness_config: Path) -> None:
    cfg = config.load()
    for repo in cfg.repos:
        snaps = restic.run_json(repo.url, ["snapshots"], password="testpass123")
        assert snaps == []

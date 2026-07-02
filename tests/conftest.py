import os
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest

PASSWORD = "testpass123"


@pytest.fixture
def source_tree(tmp_path: Path) -> Path:
    root = tmp_path / "src"
    (root / "docs").mkdir(parents=True)
    (root / "notes").mkdir(parents=True)
    (root / "docs" / "report.txt").write_text("quarterly report\n")
    (root / "notes" / "todo.md").write_text("- buy milk\n")
    return root


@pytest.fixture
def restic_repos(tmp_path: Path) -> list[Path]:
    repos = [tmp_path / "repo-a", tmp_path / "repo-b"]
    env = {**os.environ, "RESTIC_PASSWORD": PASSWORD}
    for repo in repos:
        subprocess.run(
            ["restic", "-r", str(repo), "init"], check=True, capture_output=True, env=env
        )
    return repos


@pytest.fixture
def harness_config(
    tmp_path: Path,
    restic_repos: list[Path],
    source_tree: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[Path]:
    log_dir = tmp_path / "logs"
    repo_tables = "\n".join(f'[[repo]]\nurl = "{r}"\n' for r in restic_repos)
    cfg = tmp_path / "config.toml"
    # NOTE: root-level keys (sources/excludes) MUST come before any [table] or
    # [[array]] header, or TOML absorbs them into the preceding table.
    cfg.write_text(
        f'sources = ["{source_tree}"]\nexcludes = ["*.tmp"]\n'
        '[identity]\nlabel = "com.test.turiya"\n'
        '[keychain]\naccount = "restic-test"\nservice = "turiya-test"\n'
        "[[schedule]]\nweekday = 0\nhour = 10\nminute = 0\n"
        "[power]\nwake_offset_minutes = 5\n"
        f"{repo_tables}"
        "[retention]\nkeep_daily = 7\nkeep_weekly = 4\nkeep_monthly = 6\nkeep_yearly = 1\n"
        f'[logging]\ndir = "{log_dir}"\nmax_bytes = 5242880\njson_per_file = true\n'
    )
    monkeypatch.setenv("TURIYA_CONFIG", str(cfg))
    monkeypatch.setenv("RESTIC_PASSWORD", PASSWORD)
    yield cfg

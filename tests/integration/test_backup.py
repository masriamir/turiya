import json
from pathlib import Path
from typing import Any, cast

import pytest

from turiya import config, restic
from turiya.operations import backup


def test_plain_backup_creates_snapshot(harness_config: Path) -> None:
    cfg = config.load()
    assert backup.run(cfg) is True
    snaps = restic.run_json(cfg.repos[0].url, ["snapshots"], password="testpass123")
    assert isinstance(snaps, list) and len(snaps) == 1


def test_glob_restricts_targets(harness_config: Path) -> None:
    cfg = config.load()
    assert backup.run(cfg, glob=("todo.md",)) is True
    snaps = cast(
        list[dict[str, Any]],
        restic.run_json(cfg.repos[0].url, ["snapshots"], password="testpass123"),
    )
    paths = snaps[-1]["paths"]
    assert any(p.endswith("todo.md") for p in paths)


def test_glob_no_match_returns_false(harness_config: Path) -> None:
    cfg = config.load()
    assert backup.run(cfg, glob=("*.nonexistent-xyz",)) is False


def test_backup_emits_valid_jsonl(harness_config: Path) -> None:
    cfg = config.load()
    backup.run(cfg)
    for line in (cfg.logging.dir / "backup.jsonl").read_text().splitlines():
        json.loads(line)  # must not raise


def test_plain_backup_includes_own_config(harness_config: Path) -> None:
    cfg = config.load()
    assert backup.run(cfg) is True
    snaps = cast(
        list[dict[str, Any]],
        restic.run_json(cfg.repos[0].url, ["snapshots"], password="testpass123"),
    )
    paths = snaps[-1]["paths"]
    assert any(p == str(harness_config) for p in paths)


def test_glob_override_still_includes_own_config(harness_config: Path) -> None:
    cfg = config.load()
    assert backup.run(cfg, glob=("todo.md",)) is True
    snaps = cast(
        list[dict[str, Any]],
        restic.run_json(cfg.repos[0].url, ["snapshots"], password="testpass123"),
    )
    paths = snaps[-1]["paths"]
    assert any(p.endswith("todo.md") for p in paths)
    assert any(p == str(harness_config) for p in paths)


def test_pattern_override_still_includes_own_config(
    harness_config: Path, source_tree: Path
) -> None:
    # Companion to test_glob_override_still_includes_own_config: --pattern
    # takes a different branch through resolve_targets() than --glob, so it
    # needs its own regression coverage rather than relying on --glob's.
    cfg = config.load()
    assert backup.run(cfg, pattern=("todo.md",)) is True
    snaps = cast(
        list[dict[str, Any]],
        restic.run_json(cfg.repos[0].url, ["snapshots"], password="testpass123"),
    )
    paths = snaps[-1]["paths"]
    assert any(p.endswith("todo.md") for p in paths)
    assert any(p == str(harness_config) for p in paths)


def test_include_override_still_includes_own_config(
    harness_config: Path, source_tree: Path
) -> None:
    # Companion to test_glob_override_still_includes_own_config: --include
    # takes a different branch through resolve_targets() than --glob/--pattern,
    # so it needs its own regression coverage too.
    cfg = config.load()
    included_file = str(source_tree / "notes" / "todo.md")
    assert backup.run(cfg, include=(included_file,)) is True
    snaps = cast(
        list[dict[str, Any]],
        restic.run_json(cfg.repos[0].url, ["snapshots"], password="testpass123"),
    )
    paths = snaps[-1]["paths"]
    assert any(p == included_file for p in paths)
    assert any(p == str(harness_config) for p in paths)


def test_backup_uses_config_loaded_via_explicit_path_not_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    restic_repos: list[Path],
    source_tree: Path,
) -> None:
    # Regression test for Copilot review feedback on PR #18: resolve_targets()
    # must include the path this Config was actually loaded from
    # (cfg.config_path), not re-derive it from TURIYA_CONFIG/default -- a
    # library consumer calling config.load(path=explicit) directly (an
    # anticipated usage per CLAUDE.md's "future consumers import operations +
    # config directly") must have the *explicit* file backed up, even if
    # TURIYA_CONFIG points somewhere else entirely (here, somewhere that
    # doesn't even exist, to prove it's never touched).
    explicit_config = tmp_path / "explicit" / "config.toml"
    other_env_config = tmp_path / "other-env-path" / "config.toml"
    log_dir = tmp_path / "logs"
    repo_tables = "\n".join(f'[[repo]]\nurl = "{r}"\n' for r in restic_repos)
    explicit_config.parent.mkdir(parents=True, exist_ok=True)
    explicit_config.write_text(
        f'sources = ["{source_tree}"]\nexcludes = []\n'
        '[identity]\nlabel = "com.test.turiya"\n'
        '[keychain]\naccount = "restic-test"\nservice = "turiya-test"\n'
        "[[schedule]]\nweekday = 0\nhour = 10\nminute = 0\n"
        "[power]\nwake_offset_minutes = 5\n"
        f"{repo_tables}"
        "[retention]\nkeep_daily = 7\nkeep_weekly = 4\nkeep_monthly = 6\nkeep_yearly = 1\n"
        f'[logging]\ndir = "{log_dir}"\nmax_bytes = 5242880\njson_per_file = true\n'
    )
    monkeypatch.setenv("TURIYA_CONFIG", str(other_env_config))
    monkeypatch.setenv("RESTIC_PASSWORD", "testpass123")

    cfg = config.load(explicit_config)
    assert cfg.config_path == explicit_config
    assert backup.run(cfg) is True
    snaps = cast(
        list[dict[str, Any]],
        restic.run_json(cfg.repos[0].url, ["snapshots"], password="testpass123"),
    )
    paths = snaps[-1]["paths"]
    assert any(p == str(explicit_config) for p in paths)
    assert not any(p == str(other_env_config) for p in paths)


def test_own_config_not_duplicated_when_already_a_source(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    restic_repos: list[Path],
) -> None:
    # Regression test for Copilot review feedback on PR #18: resolve_targets()
    # must not append the resolved config path if it's already present in the
    # computed target list (e.g. the operator points a `sources` entry
    # directly at config.toml), or restic gets the same positional target
    # twice and the snapshot's paths list carries a duplicate entry.
    own_config = tmp_path / "config.toml"
    log_dir = tmp_path / "logs"
    repo_tables = "\n".join(f'[[repo]]\nurl = "{r}"\n' for r in restic_repos)
    own_config.write_text(
        f'sources = ["{own_config}"]\nexcludes = []\n'
        '[identity]\nlabel = "com.test.turiya"\n'
        '[keychain]\naccount = "restic-test"\nservice = "turiya-test"\n'
        "[[schedule]]\nweekday = 0\nhour = 10\nminute = 0\n"
        "[power]\nwake_offset_minutes = 5\n"
        f"{repo_tables}"
        "[retention]\nkeep_daily = 7\nkeep_weekly = 4\nkeep_monthly = 6\nkeep_yearly = 1\n"
        f'[logging]\ndir = "{log_dir}"\nmax_bytes = 5242880\njson_per_file = true\n'
    )
    monkeypatch.setenv("TURIYA_CONFIG", str(own_config))
    monkeypatch.setenv("RESTIC_PASSWORD", "testpass123")

    cfg = config.load()
    assert backup.run(cfg) is True
    snaps = cast(
        list[dict[str, Any]],
        restic.run_json(cfg.repos[0].url, ["snapshots"], password="testpass123"),
    )
    paths = snaps[-1]["paths"]
    assert paths.count(str(own_config)) == 1


def test_exclude_matching_config_filename_does_not_exclude_it(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    restic_repos: list[Path],
    source_tree: Path,
) -> None:
    # Regression test locking in the spec's empirically-verified restic
    # behavior: cfg.excludes matching the config filename must not exclude
    # the implicit config target, because restic never applies --exclude to
    # explicit positional targets (only to files found via directory
    # recursion). This uses its own config (not harness_config) because it
    # needs excludes = ["*.toml"], which harness_config hardcodes differently.
    own_config = tmp_path / "config.toml"
    log_dir = tmp_path / "logs"
    repo_tables = "\n".join(f'[[repo]]\nurl = "{r}"\n' for r in restic_repos)
    own_config.write_text(
        f'sources = ["{source_tree}"]\nexcludes = ["*.toml"]\n'
        '[identity]\nlabel = "com.test.turiya"\n'
        '[keychain]\naccount = "restic-test"\nservice = "turiya-test"\n'
        "[[schedule]]\nweekday = 0\nhour = 10\nminute = 0\n"
        "[power]\nwake_offset_minutes = 5\n"
        f"{repo_tables}"
        "[retention]\nkeep_daily = 7\nkeep_weekly = 4\nkeep_monthly = 6\nkeep_yearly = 1\n"
        f'[logging]\ndir = "{log_dir}"\nmax_bytes = 5242880\njson_per_file = true\n'
    )
    monkeypatch.setenv("TURIYA_CONFIG", str(own_config))
    monkeypatch.setenv("RESTIC_PASSWORD", "testpass123")

    cfg = config.load()
    assert backup.run(cfg) is True
    snaps = cast(
        list[dict[str, Any]],
        restic.run_json(cfg.repos[0].url, ["snapshots"], password="testpass123"),
    )
    paths = snaps[-1]["paths"]
    assert any(p == str(own_config) for p in paths)

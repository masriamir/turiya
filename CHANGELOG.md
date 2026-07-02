# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [2.0.0] - 2026-07-02

### Changed
- Rewrote the entire tool from bash to a library-first Python 3.14 package
  (`turiya`): layered core (config/keychain/restic/rclone/logging/
  scheduling + operations) with a thin Typer CLI. Behavior parity with 1.0.0.

### Added
- Item 2: launchd job label is config-driven (no hardcoded name).
- Item 10: full CLI help/validation via Typer.
- Item 11: multiple/flexible schedules via `[[schedule]]` config tables.

### Removed
- The bash implementation and its `jq` runtime dependency (recoverable at tag `v1.0.0`).

## [1.0.0] - 2026-07-01

First tagged release: the bash implementation of turiya — automated,
encrypted, scheduled backups to multiple cloud remotes via restic + rclone on
macOS (launchd + pmset), with the restic repository password stored in the
macOS Keychain.

### Added
- `backup.sh` — backup runner with `--dry-run` and repeatable `--include` /
  `--pattern` / `--glob` targeting flags (which replace the configured source
  list for that run) plus one-off `--exclude`; runs `restic forget --prune`
  per the configured retention policy after a successful backup.
- `restore.sh` — guided restore with `--repo` / `--snapshot` / `--target` and
  repeatable `--include` / `--pattern` / `--glob` / `--exclude` mapped to
  restic's native restore matchers.
- `status.sh` — snapshot inspection (`--latest` / `--all` / `--check`) with
  `--include` / `--pattern` / `--glob` / `--exclude` filters over which
  snapshots are shown, by top-level source path.
- `query.sh` — snapshot search by date range (`--since` / `--until`), by
  file/path (`--find`), and by version history across snapshots
  (`--versions`), with `--repo` scoping and `--json` output.
- `lib/common.sh` — shared configuration loading, Keychain access, dependency
  checks, and repository resolution.
- `lib/logging.sh` — structured JSON Lines logging (a combined `ops.jsonl`
  plus per-operation `.jsonl` files, with per-file granularity for
  backup/restore) alongside human-readable `.log` files, with size-based
  rotation. Per-file verbosity is toggleable via `LOG_JSON_PER_FILE`.
- `install.sh` / `uninstall.sh` — one-time setup and teardown of the launchd
  job, pmset wake schedule, Keychain entry, and restic repository
  initialization; dependency checks for `restic`, `rclone`, and `jq`.
- `backup.conf` — single source of truth for all configuration (schedule,
  Keychain names, repositories, sources, excludes, retention, logging).
- `com.amir.turiya.plist.template` — launchd plist template rendered by
  `install.sh`.
- Documentation: `README.md`, `CLAUDE.md`, and `.copilot-instructions.md`.

# Python Migration (v2.0.0) — Design & Architecture ADR

Date: 2026-07-01
Status: Approved
Sub-project: #1 of the post-v1.0.0 roadmap (gates items 3, 4-remainder, 8, 9, and the dashboard)

This document is both the design spec for the Python rewrite and the
architecture ADR for the language migration (the largest architectural
decision in the roadmap).

## Purpose

Rewrite the turiya tool from bash to Python to make it maintainable
and testable, and to establish a **library-first** core that later
sub-projects (notifications, integrity automation, and a read-only web
dashboard) consume directly instead of shelling out to CLI scripts.

The v1.0.0 bash implementation is complete, reviewed, and preserved at the
`v1.0.0` git tag. This rewrite ships as **v2.0.0** and replaces the bash
scripts on `main` once it reaches feature parity.

## Context (why migrate)

- Bash is painful to unit-test; the v1.0.0 work required three review rounds
  driven almost entirely by bash-3.2 footguns (empty-array expansion under
  `set -u`, stderr capture). A typed, tested language removes that whole class
  of problem.
- The roadmap adds a web dashboard (read-only to start) plus notification and
  integrity-automation features. All three are far cheaper if they import a
  well-bounded core library rather than parsing CLI output or duplicating
  logic. That requires a library-first architecture, which is the natural
  moment to change language.

## Scope

**In scope (this sub-project):**
- Feature parity with the v1.0.0 bash tool: `backup`, `restore`, `status`,
  `query`, and setup/teardown, including all v1.0.0 targeting/query flags and
  the structured JSONL + human logging.
- Fold in three items that are near-free during the rewrite:
  - **Item 2** — de-hardcode "amir": the launchd job label/identifier comes
    from config.
  - **Item 10** — better CLI UX: delivered for free by Typer (auto `--help`,
    argument validation; natively fixes the v1.0.0 "flag with no value
    crashes" wart).
  - **Item 11** — flexible scheduling: config expresses one or more schedules.
- Drop the `jq` runtime dependency (Python parses restic's `--json` natively).

**Explicitly out of scope (separate follow-on sub-projects):**
- Item 3 (more rclone providers), item 4 remainder (remote log shipping),
  items 8 (notifications) + 9 (integrity automation), and items 5+6 (web
  dashboard). The config and core API are shaped to *accommodate* these, but
  none are built here.

## Toolchain

- **Python 3.14**
- **uv** — virtual environment, dependency resolution, lockfile (`uv.lock`)
- **ruff** — linting + formatting
- **mypy** and **ty** — static type checking (both run as gates)
- **pytest** — testing
- All configuration in TOML: tool config in `pyproject.toml`
  (`[tool.ruff]`, `[tool.mypy]`, `[tool.ty]`, `[tool.pytest.ini_options]`),
  runtime config in a standalone `config.toml`.
- Runtime dependencies: `typer` (CLI), `pydantic` v2 (config validation).
  Config is read with stdlib `tomllib` (read-only; if programmatic *writing*
  of TOML is ever needed — e.g. a future dashboard editing config — add
  `tomlkit` then, not now).

## Architecture (layered, library-first)

```
pyproject.toml            # metadata + [tool.*] config + deps
uv.lock
src/turiya/
  __init__.py
  config.py               # load + validate config.toml -> typed Config (pydantic v2)
  keychain.py             # macOS `security` wrapper (get/set/delete password)
  restic.py               # subprocess wrapper: run restic --json, yield typed events
  rclone.py               # remote verification
  logging.py              # structured JSONL + human logging (ports lib/logging.sh)
  scheduling.py           # launchd plist rendering (items 2 + 11) + pmset
  errors.py               # typed exception hierarchy
  operations/
    __init__.py
    backup.py             # run(config, *, dry_run, include, pattern, glob, exclude)
    restore.py            # run(config, *, repo, snapshot, target, include, pattern, glob, exclude)
    status.py             # run(config, *, mode, include, pattern, glob, exclude)
    query.py              # run(config, *, repo, since, until, find, versions)
    setup.py              # run(config) / teardown(config)
  cli.py                  # thin Typer app; maps subcommands -> operations; console entry point
tests/
  unit/                   # per-module, subprocess mocked where logic is pure
  integration/            # drive real local restic repos via fixtures
  conftest.py             # fixtures: temp restic repos, sample config, TURIYA_CONFIG
templates/
  launchd.plist.tmpl      # de-hardcoded, rendered via stdlib string.Template (no jinja2)
```

**Layering rule:** `operations/*` contain the logic and depend on the
lower-level modules (`config`, `keychain`, `restic`, `rclone`, `logging`,
`scheduling`); `cli.py` is thin and depends only on `operations` + `config`.
The future dashboard imports `operations` + `config` directly — never `cli`.

**Public core API** (what the dashboard and future features consume):
- `config.load(path: Path | None = None) -> Config`
- `operations.backup.run(config, *, dry_run=False, include=(), pattern=(), glob=(), exclude=()) -> BackupResult`
- `operations.restore.run(config, *, repo=None, snapshot="latest", target, include=(), pattern=(), glob=(), exclude=()) -> RestoreResult`
- `operations.status.run(config, *, mode="latest", include=(), pattern=(), glob=(), exclude=()) -> list[RepoStatus]`
- `operations.query.run(config, *, repo=None, since=None, until=None, find=None, versions=None) -> QueryResult`
- `operations.setup.run(config) -> None` / `operations.setup.teardown(config) -> None`

Operations emit events through `logging.py` and return typed result objects.

## Configuration

Location: `~/.config/turiya/config.toml`, overridable with the
`TURIYA_CONFIG` environment variable (also the test-isolation hook,
mirroring the v1.0.0 harness). A `setup` run seeds it from a shipped template
if absent. Paths support `~` / `$HOME` expansion at load time.

Schema (illustrative):

```toml
[identity]
# Names the launchd job (replaces the hardcoded com.amir.turiya) — item 2
label = "com.amir.turiya"

[keychain]
account = "restic"
service = "turiya"

# One or more schedules — item 11. Each renders a launchd StartCalendarInterval.
[[schedule]]
weekday = 0        # 0=Sunday..6=Saturday; omit for every day
hour = 10
minute = 0

[power]
wake_offset_minutes = 5   # pmset wake, minutes before the earliest schedule

# Array-of-tables leaves room for per-provider options later — item 3
[[repo]]
url = "rclone:gdrive:turiya-backups"
[[repo]]
url = "rclone:dropbox:turiya-backups"

sources = ["~/Documents", "~/Desktop", "~/Projects"]
excludes = [".DS_Store", "node_modules", "*.tmp"]

[retention]
keep_daily = 7
keep_weekly = 4
keep_monthly = 6
keep_yearly = 1

[logging]
dir = "~/.local/log/turiya"
max_bytes = 5242880
json_per_file = true
```

Loaded with `tomllib`, validated into a pydantic v2 `Config` model — invalid
or missing fields produce clear, user-facing errors (the config is
hand-edited, so error quality matters). An empty `repos`/`sources` fails
validation with an actionable message (the v1.0.0 empty-array lesson, now
enforced by the type layer rather than defensive guards).

## restic / rclone integration

Subprocess only — restic and rclone have no Python API. `restic.py` runs
restic with `--json --verbose=2`, captures **both stdout and stderr**
(restic writes fatal errors as `message_type: "exit_error"` JSON to stderr —
the v1.0.0 lesson), and parses each line into typed event objects
(`FileEvent`, `SummaryEvent`, `ErrorEvent`). A non-zero exit with a parsed
error event surfaces the real restic message; it is never swallowed.
`rclone.py` verifies configured remotes during `setup`.

## Logging

The JSONL schema and file layout are **preserved exactly** from v1.0.0 so the
format stays forward-compatible and the future read-only dashboard can read it
unchanged:
- Envelope: `ts`, `op`, `repo` (null for repo-agnostic events), `level`
  (`info`/`warn`/`error`), `event` (`run_start`/`file`/`summary`/`error`/
  `run_end`/`prune`), plus event-specific fields.
- Files under the configured log dir: combined `ops.jsonl`, per-op
  `<op>.jsonl`, and human-readable `<op>.log`; all size-rotated at
  `max_bytes`.
- `logging.json_per_file = false` suppresses per-file `file` events only.

Implemented as a small structured emitter for the JSONL streams; the human log
uses the stdlib `logging` module. All JSON is serialized with `json.dumps`
(never hand-built strings).

## CLI (Typer)

Subcommands, each with auto-generated `--help` and native argument validation:
- `backup` — `--dry-run`, repeatable `--include`/`--pattern`/`--glob`,
  one-off `--exclude` (same replace-vs-add semantics as v1.0.0).
- `restore` — `--repo`, `--snapshot`, `--target`, repeatable
  `--include`/`--pattern`/`--glob`/`--exclude`.
- `status` — `--latest`/`--all`/`--check`, plus
  `--include`/`--pattern`/`--glob`/`--exclude` snapshot filters.
- `query` — `--since`/`--until`, `--find`, `--versions` (mutually exclusive),
  `--repo`, `--json`.
- `setup` / `teardown` — all OS wiring (Keychain prompt, rclone verification,
  restic repo init, launchd plist install/removal, pmset) in Python.

Installed as a console entry point (`turiya`) so launchd invokes it
directly. Bootstrap (install uv + the package) is a small documented step /
one-line command in the README, run once before `setup`.

## Scheduling (items 2 + 11)

`scheduling.py` renders one launchd plist per `[[schedule]]` entry, using the
config-driven `identity.label` (item 2) and each schedule's weekday/hour/minute
(item 11). `setup` installs the plist(s) via `launchctl` and configures the
`pmset` wake at `wake_offset_minutes` before the earliest scheduled time;
`teardown` unloads and removes them.

## Keychain

Shell out to macOS `security` (get/add/delete generic password) — zero
dependencies, already proven in v1.0.0. `RESTIC_PASSWORD` in the environment
short-circuits the lookup (the test hook, preserved from v1.0.0).

## Error handling

`errors.py` defines a typed exception hierarchy (e.g., `ConfigError`,
`KeychainError`, `ResticError`, `RcloneError`). Operations raise; `cli.py`
catches, prints a clean message, emits a structured `error` event, and returns
a meaningful exit code. restic/rclone failures always surface their real
message.

## Testing

- **pytest.** Unit tests per module (subprocess mocked where the logic under
  test is pure — argument assembly, event parsing, config validation, plist
  rendering).
- **Integration tests** drive **real local restic repos** via fixtures that
  `restic init` temporary repos and set `TURIYA_CONFIG` +
  `RESTIC_PASSWORD` — the v1.0.0 `.test-harness` approach, now as pytest
  fixtures. These exercise real backup/restore/status/query round-trips and
  assert on the emitted JSONL.
- `ruff`, `mypy`, and `ty` run clean as gates before cutover.
- Parity bar: every v1.0.0 behavior (all flags, all four operations, the
  logging schema, setup/teardown wiring where testable) is covered before the
  bash scripts are removed.

## Cutover & versioning

- Build on a local `feat/python-migration` branch so `main` stays at the
  working v1.0.0 bash tool until the Python version reaches parity.
- At parity: remove the six `.sh` files and the shell `backup.conf`, merge to
  `main`, tag **v2.0.0**, and add a `## [2.0.0]` CHANGELOG entry. Bash remains
  recoverable at the `v1.0.0` tag.
- PRs remain deferred (no git remote yet, per the user's choice); when a remote
  is added, the branch → PR workflow resumes.

## Decisions & alternatives considered (ADR)

- **Language: Python** (vs. Go, vs. staying on bash). Python chosen for
  iteration speed, `pytest`, clean subprocess/JSON handling, and pydantic/typer
  fit. Go was viable (single static binary, same language as restic) but heavier
  ceremony for a personal tool; staying on bash was rejected because
  testability is the whole motivation.
- **Architecture: layered library-first** (vs. a single service class, vs. a
  thin 1:1 port). Chosen so the dashboard and items 8/9 consume a bounded core
  API; the alternatives blur boundaries or under-deliver the reuse goal.
- **CLI: Typer** (vs. Click, vs. argparse). Type-hint-driven, free `--help`
  and validation (delivers item 10), built on Click.
- **Config: TOML + pydantic v2** (vs. dataclasses, vs. attrs/cattrs). TOML is
  the user's standard; pydantic gives the best validation errors for a
  hand-edited file.
- **Config location: `~/.config/turiya/config.toml`** (vs. macOS
  Application Support, vs. explicit-path-only). Conventional, greppable, works
  installed or from a venv.
- **Setup/teardown: Python subcommands** (vs. bash wrappers). One testable
  codebase; a small bootstrap remains the only non-Python step.
- **Keychain: `security` subprocess** (vs. `keyring`). No dependency, proven.

## Success criteria

- `backup`/`restore`/`status`/`query`/`setup`/`teardown` all work against real
  local restic repos with behavior matching v1.0.0.
- Items 2, 10, 11 are delivered.
- `ruff`, `mypy`, `ty`, and `pytest` all pass clean.
- The JSONL log schema is byte-compatible with v1.0.0's.
- The bash tool is removed from `main` and the repo is tagged v2.0.0, with the
  core importable as a library (dashboard-ready).

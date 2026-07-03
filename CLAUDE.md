# CLAUDE.md

## Project purpose

turiya automates encrypted, versioned backups of this Mac's important
directories to configured cloud remotes (Google Drive, Dropbox, pCloud) via
restic + rclone, on a configurable `launchd` schedule with `pmset` wake
support. It is a **library-first Python 3.14 package**: a layered core
(`config`/`keychain`/`restic`/`rclone`/`logging`/`scheduling`) plus
`operations/*` (the actual business logic) sit behind a thin
[Typer](https://typer.tiangolo.com/) CLI. Future consumers (a read-only
dashboard, notifications, integrity automation) import `operations` +
`config` directly — never the CLI.

## File map

| File | Responsibility |
|---|---|
| `config.example.toml` | Template for `~/.config/turiya/config.toml` — schedule, identity, Keychain names, repos, sources, excludes, retention, logging. Nothing should hardcode a value that belongs here. |
| `src/turiya/config.py` | `load(path=None) -> Config`: reads TOML via stdlib `tomllib`, validates into a pydantic v2 `Config` model. `TURIYA_CONFIG` env var overrides the path (also the test-isolation hook). |
| `src/turiya/keychain.py` | macOS `security` subprocess wrapper: get/set/delete the restic password. `RESTIC_PASSWORD` env var short-circuits the lookup (test hook, preserved from v1.0.0). |
| `src/turiya/restic.py` | Subprocess wrapper: runs restic with `--json --verbose=2`, captures **both** stdout and stderr (restic writes fatal errors as `exit_error` JSON to stderr), parses lines into typed `FileEvent`/`SummaryEvent`/`ErrorEvent`. |
| `src/turiya/rclone.py` | Verifies configured remotes exist (used by `setup`). |
| `src/turiya/logging.py` | `StructuredLogger`: structured JSONL + human-readable logging. Implements the JSONL schema below — **format is unchanged from v1.0.0**. |
| `src/turiya/scheduling.py` | Renders launchd plist(s) from `identity.label` + each `[[schedule]]` entry (items 2 + 11); installs/removes via `launchctl`; sets/clears `pmset` wake. |
| `src/turiya/errors.py` | Typed exception hierarchy: `TuriyaError` (base) → `ConfigError`, `KeychainError`, `ResticError`, `RcloneError`, `SchedulingError`. |
| `src/turiya/operations/backup.py` | `run(config, *, dry_run, include, pattern, glob, exclude) -> bool`. `--dry-run`; `--include`/`--pattern`/`--glob` replace this run's source list; `--exclude` adds one-off restic excludes. |
| `src/turiya/operations/restore.py` | `run(config, *, repo, snapshot, target, include, pattern, glob, exclude) -> bool`. Guided restore mapped to restic's native restore flags. Defines `resolve_repo`, reused by `query`. |
| `src/turiya/operations/status.py` | `run(config, *, mode, include, pattern, glob, exclude) -> bool`. Snapshot inspection across all configured repos; `mode` is `latest`/`all`/`check`. |
| `src/turiya/operations/query.py` | `run(config, *, repo, since, until, find, versions, json_output) -> bool`. Snapshot search: date range, file/glob find, per-file version history. |
| `src/turiya/operations/setup.py` | `run(config, *, password=None, program=None)` / `teardown(config)`. Keychain prompt, rclone remote check, restic repo init, launchd plist install/removal, pmset. |
| `src/turiya/templates/launchd.plist.tmpl` | launchd plist template, rendered via stdlib `string.Template` — de-hardcoded (item 2), no jinja2 dependency. |
| `src/turiya/cli.py` | Thin Typer app; maps `backup`/`restore`/`status`/`query`/`setup`/`teardown` subcommands to `operations.*.run`; console entry point `turiya`. |
| `README.md` | User-facing usage docs. |
| `.github/copilot-instructions.md` | Copilot-facing project instructions — this file's counterpart. |

The original bash v1.0.0 implementation (shell backup/restore/status/query
runners, the setup/teardown shell scripts, shared shell helper libraries, the
shell config file, and the launchd plist shell template) has been removed
from `main` and remains recoverable at the `v1.0.0` git tag.

## Conventions

- **Toolchain:** Python 3.14, managed with [uv](https://docs.astral.sh/uv/). Use `uv run <cmd>` for everything (`uv run pytest`, `uv run turiya ...`) rather than activating the venv manually. Add dependencies with `uv add` / dev dependencies with `uv add --dev`; `uv.lock` is committed and must stay in sync with `pyproject.toml`.
- **Gates, run before every commit:**
  ```bash
  uv run pytest
  uv run ruff check .
  uv run mypy src tests
  uv run ty check
  ```
  All four must be clean. `ruff` also handles formatting (`uv run ruff format .`).
- **Layering rule:** `operations/*` contain the logic and depend on the lower-level modules (`config`, `keychain`, `restic`, `rclone`, `logging`, `scheduling`). `cli.py` is thin and depends only on `operations` + `config` — it must never contain business logic, only argument wiring and error-to-exit-code translation. Anything importable by a future dashboard belongs in `operations` or below, not in `cli.py`.
- **Config:** all runtime configuration lives in TOML at `~/.config/turiya/config.toml` (template: `config.example.toml`), loaded with stdlib `tomllib` and validated into a pydantic v2 `Config` model (`src/turiya/config.py`). Root-level keys (`sources`, `excludes`) must precede all `[table]`/`[[array]]` headers in the TOML file, or TOML will silently absorb them into the preceding table. Two env var overrides exist for testing, not normal use: `TURIYA_CONFIG` (override which file `config.load` reads) and `RESTIC_PASSWORD` (skip the Keychain lookup if already set).
- **Errors:** every operation-level failure is a subclass of `TuriyaError` (`src/turiya/errors.py`). `cli.py` catches `TuriyaError`, prints a clean message to stderr, and exits non-zero — never let a raw traceback reach the user for an expected failure mode. restic/rclone failures always surface their real underlying message (never swallowed).
- **restic pattern semantics** (used by `--pattern`/`--glob`/`--include`/`--exclude` on `restore`): a pattern containing `/` is path-anchored; a bare pattern (no `/`) matches the filename at any depth. This is restic's own behavior, not something this codebase implements — see `restic backup --help` / `restic restore --help`.
- **Subprocess JSON handling:** restic is invoked with `--json --verbose=2`; both stdout and stderr are captured (restic writes fatal errors as `message_type: "exit_error"` JSON to stderr). All JSON output is via `json.dumps` — never hand-built strings.
- **Testing:** unit tests mock subprocess calls where the logic under test is pure (argument assembly, event parsing, config validation, plist rendering); integration tests drive real local restic repos via fixtures that `restic init` a temp repo and set `TURIYA_CONFIG` + `RESTIC_PASSWORD`.
- **Logging lifecycle:** every operation creates a `StructuredLogger(op, config.logging)`, calls `.run_start()` immediately, and `.run_end(success=...)` at the very end — mirroring v1.0.0's `init_logging` / `emit_event run_start` / `emit_event run_end` lifecycle.

## How to add a new operation

1. Add `src/turiya/operations/<name>.py` with a `run(config: Config, **kwargs) -> ...` function; import only `config`, `keychain`, `restic`, `rclone`, `logging`, `scheduling`, `errors` — never `cli`.
2. Wire it into `src/turiya/cli.py` as a new `@app.command()`, thin argument mapping only.
3. Add the file to the file map above and to `README.md`'s CLI reference.
4. Write unit tests (subprocess mocked) and, if it touches restic, an integration test against a real temp repo fixture.
5. Run the full gate (`pytest`, `ruff check`, `mypy`, `ty check`) before considering the change done.

## Working a PR (Copilot review loop)

This repo has GitHub Copilot's automatic PR review enabled. The standard way
to drive a PR to mergeable state, when asked to "address PR comments" or
"work on PR #N":

1. Fetch all review comments (`gh api repos/<owner>/<repo>/pulls/<n>/comments`
   for inline comments, `.../reviews` for review summaries).
2. Fix each comment in code, with tests where applicable, and run the full
   gate before committing.
3. Commit and push. If the remote branch has moved on (e.g. `main` got
   merged in), `git pull --rebase` before pushing rather than force-pushing.
4. Reply to each review comment thread explaining the fix (commit sha + what
   changed): `gh api repos/<owner>/<repo>/pulls/<n>/comments/<id>/replies -f body=...`.
5. Resolve each thread with the GraphQL `resolveReviewThread` mutation (the
   thread's node id comes from a `reviewThreads` GraphQL query, not the REST
   comment id).
6. Re-request a Copilot review: `gh pr edit <n> --add-reviewer
   copilot-pull-request-reviewer`.
7. Wait for the new review. If it has new comments, repeat from step 2.
8. When a re-review comes back clean, stop and hand back for manual review.
   Never merge the PR yourself — that decision is always the user's.

## Logging schema

JSONL envelope, one object per line, written only via `json.dumps` (see `StructuredLogger.emit_event` in `src/turiya/logging.py`):
```json
{"ts":"...","op":"backup|restore|status|query","repo":"<repo-string>|null","level":"info|warn|error","event":"run_start|file|summary|error|run_end|prune", ...event-specific fields}
```
- `file` events (backup/restore only): `action`, `path`, `size`.
- `summary` events: the entire raw restic summary/check object is merged in as-is — field names vary by restic subcommand (backup's summary differs from restore's), so don't assume a fixed shape beyond the envelope itself.
- `error` events: `message`.
- `prune` events (backup only): `removed_count`.
- Files, all under `logging.dir`: `ops.jsonl` (combined, every op interleaved), `<op>.jsonl` (per-operation: `backup.jsonl`, `restore.jsonl`, `status.jsonl`, `query.jsonl`). `backup`/`restore` additionally write a human-readable `<op>.log` via the logger; `status`/`query` print their listings to stdout instead (v1.0.0 console parity) and don't produce a `.log` file. All log files rotate at `logging.max_bytes`.
- `logging.json_per_file = false` in the config suppresses `file` events only; `summary`/`error`/`run_start`/`run_end`/`prune` are always logged.

This schema and file layout are **preserved exactly** from v1.0.0 (byte-compatible) so a future read-only dashboard can consume it unchanged.

## What not to touch

- **The core public API** that the future dashboard and other sub-projects depend on:
  - `config.load(path=None) -> Config`
  - `operations.backup.run(config, *, dry_run=False, include=(), pattern=(), glob=(), exclude=()) -> bool`
  - `operations.restore.run(config, *, repo=None, snapshot="latest", target, include=(), pattern=(), glob=(), exclude=()) -> bool`
  - `operations.status.run(config, *, mode="latest", include=(), pattern=(), glob=(), exclude=()) -> bool`
  - `operations.query.run(config, *, repo=None, since=None, until=None, find=None, versions=None, json_output=False) -> bool`
  - `operations.setup.run(config, *, password=None, program=None) -> None` / `operations.setup.teardown(config) -> None`

  Don't change these signatures without a deliberate, coordinated update — external consumers are expected to import them directly. Richer typed result objects (e.g. a `BackupResult`/`QueryResult`) are deliberately deferred to the future dashboard sub-project; until then, structured per-run detail is available via the JSONL logs, and these functions return a plain success `bool` (setup/teardown return `None`).
- **The JSONL logging schema** documented above — it must stay byte-compatible with v1.0.0 so existing log archives and the future dashboard keep working.
- `identity.label` / `keychain.account` / `keychain.service` in the config must stay in sync with whatever `turiya setup` wrote to Keychain and installed via `launchctl` — don't change one without the other (or without re-running `turiya setup`).
- The retention/forget logic in `operations/backup.py` — it's intentionally simple and matches the documented retention policy; don't add extra forget flags without updating `config.example.toml` and `README.md` together.
- Don't hardcode a path, repo name, or credential anywhere — it belongs in `config.toml`.
- Don't add a parallel logging mechanism — always go through `StructuredLogger` in `src/turiya/logging.py`.

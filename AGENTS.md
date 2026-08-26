# AGENTS.md

Shared, tool-neutral guidance for any agent working in `turiya`. Claude reads it via the
`@AGENTS.md` import in `CLAUDE.md`; GitHub Copilot code review reads it directly. Sections
marked with `meta:` markers are canonical blocks synced from `masriamir/.github` — edit them
upstream, not here (see `.meta-manifest.toml` and `make meta-check`).

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
| `src/turiya/operations/setup.py` | `run(config, *, password=None, program=None)` / `teardown(config)`. Keychain prompt, rclone remote check, restic repo init, launchd plist install/removal, pmset. `default_program()` resolves the launchd `ProgramArguments` to the `uv tool`-installed `turiya` binary (via `uv tool dir --bin`), raising `SchedulingError` if it isn't installed yet — see `Makefile`. |
| `src/turiya/templates/launchd.plist.tmpl` | launchd plist template, rendered via stdlib `string.Template` — de-hardcoded (item 2), no jinja2 dependency. |
| `src/turiya/cli.py` | Thin Typer app; maps `backup`/`restore`/`status`/`query`/`setup`/`teardown` subcommands to `operations.*.run`; console entry point `turiya`. |
| `Makefile` | `install` (`uv tool install . --reinstall`, pins `turiya` on `PATH` — required before `turiya setup`, see `operations/setup.py`), `dev` (`uv sync`), `gates` (mirrors CI), `release` (tags + pushes + publishes a GitHub release for the current `pyproject.toml` version, with notes sliced from the matching `CHANGELOG.md` section). The installed `turiya` and `uv run turiya` are the same entry point via two separate environments (a pinned `uv tool` env vs. the project `.venv`). |
| `README.md` | User-facing usage docs. |
| `RECOVERY.md` | Disaster-recovery runbook: restoring turiya's backups onto a replacement Mac after the original is lost/dead/wiped. |
| `.github/copilot-instructions.md` | Copilot-facing project instructions — this file's counterpart. |
| `AGENTS.md` | This file — tool-neutral shared guidance. Repo-authored sections plus four canonical blocks (`language-en-us`, `commit-conventions`, `branch-naming`, `copilot-review-loop`) synced from `masriamir/.github` via `.meta-manifest.toml`. |
| `CLAUDE.md` | Claude-specific entry point at the repo root; imports this file with `@AGENTS.md`. |
| `.meta-manifest.toml` | Manifest of shared files/blocks synced from `masriamir/.github`, consumed by `scripts/meta_sync.py`. Bump a `ref` deliberately, then run `make meta-sync`. |
| `lefthook.yml` | Git hooks configuration, synced from `masriamir/.github`'s Python template. |
| `scripts/` | Vendored sync tooling: `meta_sync.py` (checks/applies the shared-file manifest) and `check-conventional-subject.py` / `test-conventional-subject.sh` (commit-subject linting), all synced from `masriamir/.github`. |

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

## Language

<!-- >>> meta:language-en-us -->
- **American English spelling everywhere** — not only documentation: identifiers, code comments, doc comments, CLI and other user-visible output, commit messages and PR text. Take the American form of every `-ise`/`-ize`, `-our`/`-or`, `-re`/`-er` and `-ae`/`-e` pair: `initialize`, `honor`, `center`, `artifact`, `color`, `behavior`, `analyze`.
- **Third-party vocabulary keeps its own spelling.** GitHub Actions' job-status literal is `cancelled`; a status value, API field or dependency identifier is quoted, never corrected. The rule governs our words, not other people's.
- **Applying or flagging this is not a mechanical find-and-replace.** Skip backticked code spans, and match the *pattern* (`-ise`/`-ize`, and the others above) rather than a literal wrong word — the American forms listed above are the intended spellings, not violations. Because a rule like this must name the very spellings it forbids, a blind sweep rewrites its own counter-examples: a bullet meaning "write `color`, not the `-our` form" gets flattened to "write `color`, not `color`", which forbids nothing.
- **Check spelling as you write, not only when reviewing** — text copied verbatim from upstream is the usual source of slips.
<!-- <<< meta:language-en-us -->

## Commit conventions

<!-- >>> meta:commit-conventions -->
Follow [Conventional Commits](https://www.conventionalcommits.org/): `feat` (new functionality), `fix` (bug fix), `docs` (documentation only), `test` (test-only), `refactor` (no behavior change), `chore` (build/tooling), `ci` (CI workflows). Scope is encouraged — `feat(map):`, `fix(cli):`.

**Mark breaking changes** with `!` (`feat(map)!: remove RejectLump`) or a `BREAKING CHANGE:` footer. Release automation derives the version bump from these annotations, so an unmarked breaking change proposes a semver-violating patch release.

**The PR title is the changelog entry and the version bump.** PRs squash-merge to a single commit whose subject is the PR title and whose body is blank — every branch commit subject is discarded. So the PR title alone selects the changelog section and drives the derived bump. Write it as a real Conventional Commit describing the shipped outcome; never `gh pr create --fill` (it takes the title from the branch name). Title a mixed PR by its highest-impact change (`!` > `feat` > `fix` > everything else), or split it into one PR per type when both halves each earn a changelog line. Never hand-force a version to compensate for a title.
<!-- <<< meta:commit-conventions -->

## Git branching workflow

<!-- >>> meta:branch-naming -->
Branch from `main` after a `git pull`. Name every branch `<type>/<slug>` where `type` is one of `feature`, `bugfix`, `hotfix`, `docs`, or `chore`. The slug is descriptive and always required — a bare number such as `feature/42` is rejected — and is prefixed with the issue number when a tracking issue exists (`feature/42-mmap-support`). The number is optional in the pre-push hook but expected for the issue-driven `feature`/`bugfix`/`hotfix` types; `docs`/`chore` branches commonly omit it.

**Release branches are not used.** Release automation handles version bumps, changelog, and tags from the Conventional Commits on `main`; merge the release PR to ship.
<!-- <<< meta:branch-naming -->

## Copilot review

<!-- >>> meta:copilot-review-loop -->
PRs are reviewed automatically by `copilot-pull-request-reviewer`. Work through its comments — review threads **and** the suppressed comments in the review body — across as many rounds as needed. Verify each finding against the actual code before acting; bots are sometimes wrong or working from a stale diff.

A PR is ready for human review only when **all** of these hold:

- every automated review thread is resolved,
- every required CI check passes (`gh pr checks`), and
- the codecov comment reports no uncovered changed lines (or each remaining miss is consciously justified).

Resolved threads over a red required check — or unaddressed missing coverage — do **not** make a PR ready. Whether a fresh review is auto-requested on push or must be requested by hand is a per-repo ruleset detail (`review_on_push`); check the ruleset when a request seems stuck rather than assuming.
<!-- <<< meta:copilot-review-loop -->

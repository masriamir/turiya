# GitHub Copilot Instructions — turiya

## What this project is

turiya automates encrypted, versioned backups of this Mac's important
directories to configured cloud remotes (Google Drive, Dropbox, pCloud) via
restic + rclone, on a configurable `launchd` schedule with `pmset` wake
support. It is a library-first Python 3.14 package: a layered core
(`config`/`keychain`/`restic`/`rclone`/`logging`/`scheduling`) plus
`operations/*` behind a thin Typer CLI. All runtime configuration lives in
`~/.config/turiya/config.toml` (template: `config.example.toml`).

## File map

| File | Responsibility |
|---|---|
| `config.example.toml` | Template for the runtime config. Never hardcode a value that belongs here instead. |
| `src/turiya/config.py` | `load()` — reads TOML, validates into a pydantic v2 `Config` model. |
| `src/turiya/keychain.py` | macOS `security` wrapper: get/set/delete the restic password. |
| `src/turiya/restic.py` | Subprocess wrapper: runs restic `--json`, parses typed events. |
| `src/turiya/rclone.py` | Verifies configured remotes. |
| `src/turiya/logging.py` | `StructuredLogger` — structured JSONL + human-readable logging. |
| `src/turiya/scheduling.py` | Renders/installs launchd plist(s), configures `pmset`. |
| `src/turiya/errors.py` | Typed exception hierarchy rooted at `TuriyaError`. |
| `src/turiya/operations/backup.py` | Backup runner. `dry_run`, `include`/`pattern`/`glob`/`exclude`. |
| `src/turiya/operations/restore.py` | Guided restore. `repo`/`snapshot`/`target`/`include`/`pattern`/`glob`/`exclude`. |
| `src/turiya/operations/status.py` | Snapshot listing/check. `mode` (`latest`/`all`/`check`) + targeting flags. |
| `src/turiya/operations/query.py` | Snapshot search by date/path/version history. `since`/`until`/`find`/`versions`/`repo`/`json_output`. |
| `src/turiya/operations/setup.py` | `run()` / `teardown()` — Keychain, rclone, restic init, launchd, pmset. |
| `src/turiya/cli.py` | Thin Typer app mapping CLI subcommands to `operations.*.run`. |

## Rules for generating or editing code in this repo

- **Python 3.14**, managed with `uv`. Always run tooling as `uv run <cmd>` (`uv run pytest`, `uv run turiya ...`), never invoke a bare system Python.
- **Layering is strict:** `operations/*` hold the logic and may import `config`/`keychain`/`restic`/`rclone`/`logging`/`scheduling`/`errors`. `cli.py` is thin — argument parsing and error-to-exit-code translation only, no business logic, and it must not be imported by `operations/*`.
- **All runtime config** lives in `~/.config/turiya/config.toml` (TOML, validated by pydantic v2 in `src/turiya/config.py`). Root-level keys (`sources`, `excludes`) must appear before any `[table]`/`[[array]]` header, or TOML silently absorbs them into the preceding table. Never hardcode a path, repo name, retention value, or credential — add it to the config schema instead.
- **Errors:** raise a subclass of `TuriyaError` (`src/turiya/errors.py`) for any expected failure. Let `cli.py`'s single `except TuriyaError` handler print the message and set the exit code — don't `sys.exit` directly from `operations/*`.
- Build all JSON output with `json.dumps` — never string-concatenated JSON.
- Log via `StructuredLogger.emit_event` / `.log_human` / `.run_start` / `.run_end` from `src/turiya/logging.py` — don't write to a log file directly, and don't invent a parallel logging mechanism. Operations do print: `backup`/`restore` route their human-readable narration through `log_human` (which both prints and writes `<op>.log`); `status`/`query` print their tabular/JSON listings straight to stdout (v1.0.0 console parity) and have no `.log` file. Either way, `cli.py` stays thin and owns exit codes — it doesn't format operation output itself.
- restic pattern semantics: a pattern containing `/` is path-anchored, a bare pattern matches the filename at any depth — this is restic's own behavior (`restic restore --help`), not something to reimplement.
- New operations follow the skeleton documented in `CLAUDE.md`'s "How to add a new operation" section.
- Run the full gate before considering any change done: `uv run pytest`, `uv run ruff check .`, `uv run mypy src tests`, `uv run ty check` — all clean, zero warnings.

## Logging schema

One JSON object per line (JSONL), written only via `json.dumps` (unchanged from v1.0.0):
```json
{"ts":"...","op":"backup|restore|status|query","repo":"<repo-string>|null","level":"info|warn|error","event":"run_start|file|summary|error|run_end|prune", ...}
```
Files under `logging.dir`: `ops.jsonl` (combined), `<op>.jsonl` (per-op). `backup`/`restore` also write `<op>.log` (human-readable); `status`/`query` print listings to stdout instead and have no `.log` file. `logging.json_per_file = false` in the config suppresses only `file` events.

## Do not

- Change the core public API (`config.load`, `operations.*.run`) that a future dashboard and other sub-projects depend on — see `CLAUDE.md`'s "What not to touch" for the exact signatures.
- Change the JSONL logging schema — it must stay byte-compatible with v1.0.0.
- Change `identity.label`/`keychain.account`/`keychain.service` without also updating what's stored in Keychain and installed via `launchctl` (re-run `turiya setup`).
- Edit the generated `.plist` directly (gitignored, regenerated from `src/turiya/templates/launchd.plist.tmpl` by `turiya setup`).
- Add a new logging mechanism instead of using `StructuredLogger`.
- Import `cli` from anything under `operations/` or the core modules — dependencies flow one way: `cli` → `operations` → core.

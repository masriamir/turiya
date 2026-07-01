# CLAUDE.md

## Project purpose

restic-backup automates encrypted, versioned backups of this Mac's important
directories to three cloud remotes (Google Drive, Dropbox, pCloud) via
restic + rclone, on a weekly `launchd` schedule with `pmset` wake support.
All configuration lives in `backup.conf`; the scripts are thin orchestration
around `restic`, `rclone`, and `jq`.

## File map

| File | Responsibility |
|---|---|
| `backup.conf` | Single source of truth for all configuration: schedule, Keychain names, repos, sources, excludes, retention, logging. Nothing else should hardcode a value that belongs here. |
| `lib/common.sh` | Sourced helper library: `load_config`, `check_dependencies`, `get_restic_password`, `resolve_repo`. Not executable on its own. |
| `lib/logging.sh` | Sourced helper library: `init_logging`, `log_human`, `emit_event`, `emit_summary`, `process_restic_json_stream`, `rotate_log_file`. Implements the JSONL logging schema below. |
| `backup.sh` | Runs the weekly backup (invoked by launchd). `--dry-run`; `--include`/`--pattern`/`--glob` restrict this run's source list; `--exclude` adds one-off restic excludes. |
| `restore.sh` | Interactive guided restore. `--repo`/`--snapshot`/`--target` plus repeatable `--include`/`--pattern`/`--glob`/`--exclude`, mapped directly to restic's native restore flags. |
| `status.sh` | Snapshot inspection across all configured repos. `--latest` (default)/`--all`/`--check` plus `--include`/`--pattern`/`--glob`/`--exclude` to filter which snapshots are shown, by top-level source path. |
| `query.sh` | Snapshot search: `--since`/`--until` (date range), `--find` (which snapshot contains a path/glob), `--versions` (every version of a file across snapshots), `--repo` to scope, `--json` for raw output. |
| `install.sh` | One-time setup: dependency check, Keychain password prompt, rclone remote check, restic repo init, launchd plist render + load, pmset wake schedule. |
| `uninstall.sh` | Reverses install.sh: unloads the launchd job, clears the pmset schedule, optionally removes the Keychain entry and `LOG_DIR`. |
| `com.amir.restic-backup.plist.template` | launchd plist template, rendered by `install.sh`. Don't edit the generated `.plist` directly — it's gitignored and regenerated on every `install.sh` run. |
| `README.md` | User-facing usage docs. |
| `.copilot-instructions.md` | Copilot-facing project instructions — this file's counterpart. |

## Conventions

- Every script: `set -euo pipefail`; resolves its own `SCRIPT_DIR` from `BASH_SOURCE[0]`; sources `lib/common.sh` then `lib/logging.sh`; calls `load_config "$SCRIPT_DIR"` before touching any config variable.
- **macOS ships bash 3.2.57 at `/bin/bash`** — confirmed on this machine via `/bin/bash --version`. Homebrew's newer bash on `PATH` is irrelevant: the `#!/bin/bash` shebang always resolves to the system one. Bash 3.2 throws "unbound variable" when expanding `"${ARR[@]}"` on a *declared-but-empty* array under `set -u` (bash 4.4+ doesn't have this bug). **Never expand a possibly-empty array directly** — guard first: `if [[ ${#ARR[@]} -gt 0 ]]; then ... fi`. This won't reproduce if you test under an interactively-launched Homebrew bash 5 — only under the real `/bin/bash` the scripts run with.
- No associative arrays, `mapfile`/`readarray`, `${var,,}`/`${var^^}`, `local -n` namerefs, or other bash-4+-only features.
- All JSON construction goes through `jq` (`jq -c`, `jq -nc`) — never hand-built JSON strings.
- restic pattern semantics (used by `--pattern`/`--glob`/`--include`/`--exclude` on `restore.sh`): a pattern containing `/` is path-anchored; a bare pattern (no `/`) matches the filename at any depth. This is restic's own behavior, not something these scripts implement — see `restic backup --help` / `restic restore --help`.
- Config lives only in `backup.conf`. Two env var overrides exist for testing, not normal use: `RESTIC_BACKUP_CONFIG` (override which file `load_config` reads) and `RESTIC_PASSWORD` (if already set, `get_restic_password` skips the Keychain lookup).
- Logging lifecycle: every operation calls `init_logging <op>` once at startup, `emit_event <op> "" info run_start` immediately after, and `emit_event <op> "" info|error run_end --str status success|failure` at the very end.

## How to add a new script

1. Start from this skeleton:
   ```bash
   #!/bin/bash
   set -euo pipefail
   SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
   # shellcheck source=lib/common.sh
   source "$SCRIPT_DIR/lib/common.sh"
   # shellcheck source=lib/logging.sh
   source "$SCRIPT_DIR/lib/logging.sh"
   load_config "$SCRIPT_DIR"
   # ... parse args ...
   init_logging <opname>
   emit_event <opname> "" info run_start
   check_dependencies restic rclone security jq
   get_restic_password
   # ... business logic, using log_human / emit_event / process_restic_json_stream ...
   emit_event <opname> "" info run_end --str status "success"
   ```
2. Add `<opname>` to the file map above and to `README.md`'s script reference.
3. If the script invokes restic `backup`/`restore` (or anything else that emits `--json` progress), pipe it through `process_restic_json_stream <opname> "$REPO"` rather than parsing restic's plain-text output.
4. Run `shellcheck -x path/to/script.sh` before committing — zero warnings required.

## Logging schema

JSONL envelope, one object per line, written only via `jq -c`:
```json
{"ts":"...","op":"backup|restore|status|query","repo":"<repo-string>|null","level":"info|warn|error","event":"run_start|file|summary|error|run_end|prune", ...event-specific fields}
```
- `file` events (backup/restore only): `action`, `path`, `size`.
- `summary` events: the entire raw restic summary/check object is merged in as-is — field names vary by restic subcommand (backup's summary differs from restore's), so don't assume a fixed shape beyond the envelope itself.
- `error` events: `message`.
- `prune` events (backup only): `removed_count`.
- Files, all under `LOG_DIR`: `ops.jsonl` (combined, every op interleaved), `<op>.jsonl` (per-operation: `backup.jsonl`, `restore.jsonl`, `status.jsonl`, `query.jsonl`), `<op>.log` (human-readable equivalent). All rotate at `LOG_MAX_BYTES`.
- `LOG_JSON_PER_FILE=false` in `backup.conf` suppresses `file` events only; `summary`/`error`/`run_start`/`run_end`/`prune` are always logged.

## What not to touch

- `KEYCHAIN_ACCOUNT`/`KEYCHAIN_SERVICE` in `backup.conf` must stay in sync with whatever `install.sh` wrote to Keychain — don't change one without the other (or without re-running `install.sh`).
- `com.amir.restic-backup.plist.template`'s placeholder tokens (`{{HOME}}`, `{{SCRIPT_DIR}}`, `{{BACKUP_WEEKDAY}}`, `{{BACKUP_HOUR}}`, `{{BACKUP_MINUTE}}`) — `install.sh`'s `sed` render step depends on these exact strings.
- The retention/forget logic in `backup.sh` — it's intentionally simple and matches the documented retention policy; don't add extra forget flags without updating `backup.conf` and `README.md` together.
- `set -euo pipefail` at the top of every script — don't remove it to silence an error; fix the underlying issue (usually the bash 3.2 empty-array gotcha above).
- Don't hardcode a path, repo name, or credential anywhere — it belongs in `backup.conf`.

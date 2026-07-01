# restic-backup: targeting flags, query.sh, and structured JSON logging

Date: 2026-07-01
Status: Approved

## Purpose

Extend the existing restic-backup scaffold (`backup.sh`, `restore.sh`, `status.sh`,
`install.sh`, `uninstall.sh`, `backup.conf`) with:

1. Consistent `--include` / `--exclude` / `--pattern` / `--glob` targeting flags
   across `backup.sh`, `restore.sh`, and `status.sh`.
2. A new `query.sh` for snapshot search: by date range, by file/path, and file
   version history across snapshots.
3. Structured JSON Lines (JSONL) logging for every operation, with per-file
   granularity for backup/restore, alongside the existing human-readable logs.
4. Documentation: `CLAUDE.md`, `.copilot-instructions.md`, and a `README.md`
   overhaul.
5. A clean `shellcheck` pass across all scripts.

Environment: macOS Intel, Homebrew at `/usr/local/bin`, restic 0.19.0, rclone
1.74.3, jq 1.7.1 present. `shellcheck` not currently installed — will be
installed via `brew install shellcheck` for the lint pass.

## Unified targeting-flag model

`--include` / `--pattern` / `--glob` are three ways to express *what to
target*. `--exclude` is the one negative flag. All four are repeatable. They
resolve differently per script because restic's own flag support differs per
subcommand:

- **`--include PATH`**: an exact literal path.
- **`--pattern P`**: a restic-style pattern, path-aware (may contain `/` and
  is anchored to that path).
- **`--glob G`**: a filename-only shorthand (e.g. `*.pdf`) that matches at any
  depth.
- **`--exclude P`**: a restic-style exclude pattern.

Restic's native pattern syntax already treats bare patterns (no `/`) as
"match this filename anywhere" and patterns containing `/` as anchored —
which is exactly the pattern/glob distinction above. This means restore.sh
needs no extra logic: `--include`, `--pattern`, and `--glob` all feed the
same underlying restic `--include` list.

### backup.sh

Restic's `backup` subcommand has **no** include/pattern flag — only
`--exclude`/`--iexclude`. So targeting must be resolved by the script itself:

- `--include PATH`: use the literal path, replacing this run's source list
  (`SOURCES` from `backup.conf` is not used for this invocation).
- `--pattern P`: resolve matches under the configured `SOURCES` via
  `find <source> -path "*$P*"` (or similarly anchored), collect matches,
  replace the source list with the resolved paths.
- `--glob G`: resolve matches under `SOURCES` via `find <source> -name "$G"`,
  replace the source list with the resolved paths.
- `--exclude P`: appended to the existing `EXCLUDES` restic `--exclude` flags
  for this run only (config file `EXCLUDES` unaffected).
- If multiple of `--include`/`--pattern`/`--glob` are passed in the same
  invocation, their resolved path sets are unioned before replacing the
  source list.
- If `--pattern`/`--glob` resolve to zero matches, exit with an error rather
  than silently backing up nothing.

### restore.sh

Restic's `restore` subcommand has native `--include`/`--exclude`, both
pattern-capable and repeatable.

- `--include`, `--pattern`, `--glob` all append directly to restic's native
  `--include` list (repeatable flag, `-i`/`--include` under the hood).
- `--exclude` appends directly to restic's native `--exclude` list.
- Existing `--repo`, `--snapshot`, `--target` flags are unchanged. The
  existing single-value `--include` is upgraded to repeatable (array).

### status.sh

`status.sh` doesn't touch files — it lists snapshots — so targeting filters
*which snapshots are displayed*, not restic backup/restore behavior:

- `--include PATH`: passed to restic's `snapshots --path <path>` filter
  (server-side, exact path match, snapshot must include it).
- `--pattern P` / `--glob G`: client-side filtering. Fetch
  `restic snapshots --json`, use `jq` to pull each snapshot's `.paths[]`,
  glob-match in bash (`[[ "$path" == $pattern ]]`), keep snapshots with at
  least one match.
- `--exclude P`: inverse of the pattern/glob filter — drop snapshots where
  any path matches.
- `--check` and `--all` modes are unchanged; targeting flags apply only to
  the default (latest-per-repo) and `--all` listing modes.

## query.sh (new)

Read-only snapshot inspection tool. Same config sourcing, Keychain retrieval,
and repo iteration pattern as `status.sh`.

Flags:
- `--repo NAME`: substring-match against configured `REPOS` (same convention
  as `restore.sh`); defaults to searching all configured repos.
- `--since DATE --until DATE`: list snapshots with `.time` in range (either
  bound optional). Implemented via `restic snapshots --json` + `jq` date
  comparison.
- `--find PATH_OR_GLOB`: report which snapshot(s) contain a matching
  file/path, using `restic find --json PATTERN` per repo.
- `--versions PATH_OR_GLOB`: list every snapshot containing a matching file,
  tabulated by snapshot ID / date / size, so the user can see how a file
  changed over time. Also built on `restic find --json`.
- `--json`: emit raw JSON instead of a formatted table (applies to all three
  modes).
- Exactly one of `--since`/`--until`, `--find`, `--versions` must be given
  per invocation (mutually exclusive modes); error otherwise.

## Structured JSON logging

`jq` becomes a hard dependency, checked in the same dependency-check block as
`restic`/`rclone`/`security` in `backup.sh`, `restore.sh`, `status.sh`,
`query.sh`, and `install.sh`.

### Files (all under `LOG_DIR`)

| File | Contents |
|---|---|
| `ops.jsonl` | Combined JSONL, every operation, interleaved |
| `backup.jsonl` | JSONL for backup.sh runs only |
| `restore.jsonl` | JSONL for restore.sh runs only |
| `status.jsonl` | JSONL for status.sh runs only |
| `query.jsonl` | JSONL for query.sh runs only |
| `backup.log` | Human-readable, backup.sh only (existing format) |
| `restore.log` | Human-readable, restore.sh only (new) |
| `status.log` | Human-readable, status.sh only (new) |
| `query.log` | Human-readable, query.sh only (new) |

All `.jsonl` and `.log` files rotate at `LOG_MAX_BYTES`, reusing/generalizing
the existing `rotate_log` function in `backup.sh` to loop over a list of log
paths instead of a single hardcoded one.

### JSONL envelope

One JSON object per line, written via `jq -c` (never hand-built strings):

```json
{"ts":"2026-07-01T10:00:03-07:00","op":"backup","repo":"rclone:gdrive:restic-backups","level":"info","event":"file","action":"new","path":"/Users/amir/Documents/foo.txt","size":1234}
{"ts":"2026-07-01T10:04:11-07:00","op":"backup","repo":"rclone:gdrive:restic-backups","level":"info","event":"summary","snapshot_id":"a1b2c3d4","files_new":42,"files_changed":3,"data_added":10485760,"duration_s":247.8}
{"ts":"2026-07-01T10:04:12-07:00","op":"backup","repo":"rclone:gdrive:restic-backups","level":"error","event":"error","message":"repository lock failed"}
```

Fields:
- `ts`: ISO-8601 local time, from `date -Iseconds` (or equivalent).
- `op`: one of `backup | restore | status | query`.
- `repo`: the configured repo string, or `null` for repo-agnostic events.
- `level`: `info | warn | error`.
- `event`: `run_start | file | summary | error | run_end`.
- Event-specific fields: `file` events carry `action`/`path`/`size`;
  `summary` carries restic's summary stats; `error` carries `message`.

### Per-file capture (backup/restore)

Invoke restic with `--json --verbose=2`, pipe stdout through `jq` to both:
1. Reshape matching `verbose_status` messages into `file` events → append to
   `<op>.jsonl` and `ops.jsonl`.
2. Reshape the terminal `summary` message into a `summary` event → same
   files.

Simultaneously, still write a human-readable line to `<op>.log` per file
(derived from the same jq-parsed stream, not a second restic invocation).

`status.sh`/`query.sh` don't touch files, so they only ever emit
`run_start`/`summary`/`error`/`run_end` events (one summary per repo /
per query mode), never `file` events.

### New `backup.conf` knob

```
LOG_JSON_PER_FILE=true   # when false, suppress "file" events (keep summary/error/run_start/run_end)
```

Large backups can generate very large `.jsonl` files; this knob lets the user
trade off granularity vs. disk usage without touching scripts. All other log
paths derive from `LOG_DIR` by naming convention (no new per-file path
variables needed).

## Documentation

- **`CLAUDE.md`**: project purpose, full file map with responsibilities,
  conventions (`set -euo pipefail`, config-only values, jq for JSON, restic
  pattern semantics), how to add a new script (dependency check block,
  Keychain retrieval, log wiring, argument parsing shape), the JSONL logging
  schema (as above), and an explicit "what not to touch" section (Keychain
  service/account names, `com.amir.restic-backup.plist.template` structure,
  `set -euo pipefail`, not hardcoding values that belong in `backup.conf`).
- **`.copilot-instructions.md`**: same content, restructured into Copilot's
  expected instructions format.
- **`README.md`**: Quick Start section, first-run sequence (rclone config →
  edit `backup.conf` → `install.sh` → `backup.sh --dry-run` → `backup.sh`),
  full flag reference per script (including all new targeting flags and
  `query.sh`), updated repository structure diagram, updated log file list.

## Out of scope / not touched

- `install.sh` / `uninstall.sh`: only change is adding `jq` to the dependency
  check in `install.sh`. Log cleanup in `uninstall.sh` already
  `rm -rf`s the whole `LOG_DIR`, so no change needed there.
- `com.amir.restic-backup.plist.template`: untouched.
- Retention/forget logic in `backup.sh`: untouched.
- No new runtime dependency beyond `jq` (already present on this machine).

## Testing / verification plan

- `bash -n` on every script (syntax check).
- `shellcheck` (install via Homebrew) on every `.sh` file, zero warnings
  before finishing.
- Manual dry-run exercises: `backup.sh --dry-run` with each new targeting
  flag against a scratch directory; `status.sh` with `--pattern`/`--glob`
  against a real (or freshly-initialized scratch) repo; `query.sh` in all
  three modes; verify `.jsonl` files are valid JSON (`jq -c . < file.jsonl`
  over every line) and `.log` files are unaffected in format from today.

# Targeting Flags, query.sh, and Structured JSON Logging — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `--include`/`--exclude`/`--pattern`/`--glob` targeting flags to `backup.sh`/`restore.sh`/`status.sh`, add a new `query.sh` for snapshot search, replace plain-text logging with structured JSONL (combined + per-op, per-file granularity for backup/restore) alongside human-readable logs, and update config/docs accordingly.

**Architecture:** Two new shared libraries (`lib/common.sh` for config/Keychain/dependency helpers, `lib/logging.sh` for the JSONL/human logging machinery) are sourced by all four operational scripts, eliminating duplicated boilerplate. Per-file logging is built by piping restic's own `--json --verbose=2` output through `jq`, not by parsing plain text.

**Tech Stack:** bash (must run under macOS's system `/bin/bash`, version 3.2.57 — see Global Constraints), restic 0.19.0, rclone 1.74.3, jq (new hard dependency), shellcheck (dev-only, for the lint pass).

## Global Constraints

- Every script keeps `set -euo pipefail` and resolves `SCRIPT_DIR` from `BASH_SOURCE[0]`.
- **Target shell is bash 3.2.57** (macOS's `/bin/bash` — confirmed via `/bin/bash --version` on this machine; shebangs always resolve here regardless of Homebrew bash on `PATH`). Bash 3.2 throws "unbound variable" when expanding `"${ARR[@]}"` on a declared-but-empty array under `set -u`. **Every possibly-empty array must be guarded** with `if [[ ${#ARR[@]} -gt 0 ]]; then ... fi` before expansion. Confirmed empirically:
  ```
  $ /bin/bash -c 'set -u; arr=(); for x in "${arr[@]}"; do echo "$x"; done'
  /bin/bash: arr[@]: unbound variable
  ```
- No bash-4+-only features anywhere: no associative arrays, no `mapfile`/`readarray`, no `${var,,}`/`${var^^}`, no `local -n` namerefs.
- `jq` is a new hard dependency, added to the dependency check in `backup.sh`, `restore.sh`, `status.sh`, `query.sh`, and `install.sh`. Confirmed present on this machine: `jq-1.7.1-apple` at `/usr/bin/jq`.
- All JSON is built via `jq -c`/`jq -nc`, never hand-built strings.
- All config lives in `backup.conf`; no hardcoded paths/repo names/credentials in any script.
- Restic version on this machine is 0.19.0 — confirmed JSON shapes empirically (see task notes below); do not assume older-restic shapes.
- Test isolation: two testing-only env var hooks are added to `lib/common.sh` — `TURIYA_CONFIG` (override which config file `load_config` reads) and honoring a pre-set `RESTIC_PASSWORD` (skips Keychain lookup). These let every task's tests run against a local scratch restic repo without touching the user's real `backup.conf`, real cloud repos, or real Keychain entry.
- Spec reference: `docs/superpowers/specs/2026-07-01-flags-query-and-json-logging-design.md`.

---

### Task 1: Test harness (local scratch repo, isolated from real config/Keychain)

**Files:**
- Create: `.test-harness/backup.conf`
- Create: `.test-harness/src/docs/report.txt`
- Create: `.test-harness/src/notes/todo.md`
- Modify: `.gitignore` (add `.test-harness/`)

**Interfaces:**
- Produces: a local-backend restic repo at `.test-harness/repo-a` (and a second, uninitialized-until-needed `.test-harness/repo-b`) that later tasks' tests read/write against, using `RESTIC_PASSWORD=testpass123` and `TURIYA_CONFIG=<repo>/.test-harness/backup.conf`.

- [ ] **Step 1: Add the harness directory to .gitignore**

Add this line to `.gitignore` (anywhere under the existing "macOS" or a new section):
```
# Local test harness (scratch restic repos + fixtures, never committed)
.test-harness/
```

- [ ] **Step 2: Create fixture source files**

```bash
mkdir -p .test-harness/src/docs .test-harness/src/notes
printf 'quarterly report draft\n' > .test-harness/src/docs/report.txt
printf '- buy milk\n- fix backup script\n' > .test-harness/src/notes/todo.md
```

- [ ] **Step 3: Write the test backup.conf**

Create `.test-harness/backup.conf` with this exact content (absolute paths, since this file will be sourced with `set -u` and no shell expansion of `$PWD` at source time is safe to rely on):

```bash
# Test harness config — never used by real backup.sh runs, only via
# TURIYA_CONFIG override in test steps. Not committed to git.
BACKUP_WEEKDAY=0
BACKUP_HOUR=10
BACKUP_MINUTE=0
PMSET_WAKE_OFFSET_MINUTES=5

KEYCHAIN_ACCOUNT="restic-test"
KEYCHAIN_SERVICE="turiya-test"

REPOS=(
    "/Users/amir/workspace/turiya/.test-harness/repo-a"
    "/Users/amir/workspace/turiya/.test-harness/repo-b"
)

SOURCES=(
    "/Users/amir/workspace/turiya/.test-harness/src/docs"
    "/Users/amir/workspace/turiya/.test-harness/src/notes"
)

EXCLUDES=(
    "*.tmp"
)

RETENTION_KEEP_DAILY=7
RETENTION_KEEP_WEEKLY=4
RETENTION_KEEP_MONTHLY=6
RETENTION_KEEP_YEARLY=1

LOG_DIR="/Users/amir/workspace/turiya/.test-harness/logs"
LOG_MAX_BYTES=5242880
LOG_JSON_PER_FILE=true
```

- [ ] **Step 4: Initialize the two local restic repos and verify isolation**

```bash
export RESTIC_PASSWORD=testpass123
restic -r .test-harness/repo-a init
restic -r .test-harness/repo-b init
restic -r .test-harness/repo-a snapshots --json
```

Expected: both `init` commands print "created restic repository ..."; the final `snapshots --json` prints `[]` (empty — nothing backed up yet). This confirms the harness repos exist independently of the real `backup.conf`'s `REPOS` (Google Drive/Dropbox/pCloud) and the real Keychain entry (`restic`/`turiya`), which are never touched.

- [ ] **Step 5: Commit**

```bash
git add .gitignore
git commit -m "test: add local restic test harness for isolated script testing"
```

(`.test-harness/` itself is gitignored and won't be staged — only the `.gitignore` change is committed. The harness directory persists on disk for reuse by later tasks' tests.)

---

### Task 2: `lib/common.sh` — config, Keychain, dependency helpers

**Files:**
- Create: `lib/common.sh`

**Interfaces:**
- Produces: `load_config(script_dir)`, `check_dependencies(cmd...)`, `get_restic_password()` (sets/exports `RESTIC_PASSWORD`), `resolve_repo(filter)` (echoes a matching entry from `REPOS`, or the first entry if `filter` is empty; exits 1 if `filter` is non-empty and matches nothing).
- Consumes: nothing (this is the first library).

- [ ] **Step 1: Create the directory and file**

```bash
mkdir -p lib
```

Create `lib/common.sh`:

```bash
#!/bin/bash
# =============================================================================
# lib/common.sh — shared config loading, Keychain, and dependency helpers
# =============================================================================
# Sourced by backup.sh, restore.sh, status.sh, and query.sh. Not meant to be
# executed directly — it has no effect on its own.
# =============================================================================

load_config() {
    local script_dir="$1"
    CONFIG_FILE="${TURIYA_CONFIG:-$script_dir/backup.conf}"

    if [[ ! -f "$CONFIG_FILE" ]]; then
        echo "ERROR: config file not found at $CONFIG_FILE" >&2
        exit 1
    fi

    # shellcheck source=backup.conf
    source "$CONFIG_FILE"
}

check_dependencies() {
    local cmd
    for cmd in "$@"; do
        if ! command -v "$cmd" &>/dev/null; then
            echo "ERROR: '$cmd' not found in PATH. Is Homebrew on your PATH?" >&2
            exit 1
        fi
    done
}

get_restic_password() {
    if [[ -n "${RESTIC_PASSWORD:-}" ]]; then
        export RESTIC_PASSWORD
        return 0
    fi

    local password
    password=$(security find-generic-password \
        -a "$KEYCHAIN_ACCOUNT" \
        -s "$KEYCHAIN_SERVICE" \
        -w 2>/dev/null) || {
        echo "ERROR: Could not retrieve password from Keychain." >&2
        echo "       Run install.sh to set it up, or check account/service names in backup.conf." >&2
        exit 1
    }
    RESTIC_PASSWORD="$password"
    export RESTIC_PASSWORD
}

resolve_repo() {
    local filter="$1"
    local repo
    if [[ -n "$filter" ]]; then
        for repo in "${REPOS[@]}"; do
            if [[ "$repo" == *"$filter"* ]]; then
                echo "$repo"
                return 0
            fi
        done
        echo "ERROR: No repo matching '$filter' found in backup.conf." >&2
        exit 1
    fi
    echo "${REPOS[0]}"
}
```

- [ ] **Step 2: Verify it loads the test harness config**

```bash
bash -c '
  source lib/common.sh
  load_config "/Users/amir/workspace/turiya"
' 2>&1 | head -5
```

Expected: with the real `.test-harness/backup.conf` not being the default, this should actually load the *real* `backup.conf` (since `TURIYA_CONFIG` isn't set) — expect no output and exit 0, proving `load_config` finds and sources the real config without error. Now verify the override:

```bash
TURIYA_CONFIG="/Users/amir/workspace/turiya/.test-harness/backup.conf" bash -c '
  source lib/common.sh
  load_config "/Users/amir/workspace/turiya"
  echo "REPOS[0]=${REPOS[0]}"
  check_dependencies bash jq
  echo "deps ok"
  echo "resolved=$(resolve_repo "")"
  echo "resolved-b=$(resolve_repo "repo-b")"
'
```

Expected output:
```
REPOS[0]=/Users/amir/workspace/turiya/.test-harness/repo-a
deps ok
resolved=/Users/amir/workspace/turiya/.test-harness/repo-a
resolved-b=/Users/amir/workspace/turiya/.test-harness/repo-b
```

- [ ] **Step 3: Commit**

```bash
git add lib/common.sh
git commit -m "feat: add lib/common.sh for shared config, Keychain, and dependency helpers"
```

---

### Task 3: `lib/logging.sh` — JSONL + human logging

**Files:**
- Create: `lib/logging.sh`

**Interfaces:**
- Consumes: `LOG_DIR`, `LOG_MAX_BYTES`, `LOG_JSON_PER_FILE` (from sourced `backup.conf`, via Task 2's `load_config`).
- Produces: `init_logging(op)` (sets `LOG_HUMAN`, `LOG_JSONL`, `LOG_COMBINED_JSONL`; creates/rotates files), `log_human(msg...)`, `emit_event(op, repo, level, event, [--str key value]... [--num key value]...)`, `emit_summary(op, repo, raw_json)`, `process_restic_json_stream(op, repo)` (reads restic `--json` lines from stdin).

- [ ] **Step 1: Create the file**

```bash
#!/bin/bash
# =============================================================================
# lib/logging.sh — structured JSONL + human-readable logging
# =============================================================================
# Sourced by backup.sh, restore.sh, status.sh, and query.sh, after
# lib/common.sh and load_config. Requires LOG_DIR, LOG_MAX_BYTES, and
# LOG_JSON_PER_FILE (from backup.conf) plus jq on PATH.
# =============================================================================

rotate_log_file() {
    local file="$1"
    if [[ -f "$file" ]]; then
        local size
        size=$(stat -f%z "$file" 2>/dev/null || echo 0)
        if (( size > LOG_MAX_BYTES )); then
            mv "$file" "${file}.$(date +%Y%m%d%H%M%S).bak"
        fi
    fi
}

init_logging() {
    local op="$1"
    mkdir -p "$LOG_DIR"
    LOG_HUMAN="$LOG_DIR/${op}.log"
    LOG_JSONL="$LOG_DIR/${op}.jsonl"
    LOG_COMBINED_JSONL="$LOG_DIR/ops.jsonl"
    rotate_log_file "$LOG_HUMAN"
    rotate_log_file "$LOG_JSONL"
    rotate_log_file "$LOG_COMBINED_JSONL"
}

log_human() {
    local msg="[$(date '+%Y-%m-%d %H:%M:%S')] $*"
    echo "$msg" | tee -a "$LOG_HUMAN"
}

emit_event() {
    # Usage: emit_event <op> <repo> <level> <event> [--str key value]... [--num key value]...
    local op="$1" repo="$2" level="$3" event="$4"
    shift 4
    local jq_args=(-nc --arg ts "$(date '+%Y-%m-%dT%H:%M:%S%z')" \
                       --arg op "$op" --arg repo "$repo" \
                       --arg level "$level" --arg event "$event")
    local filter='{ts:$ts, op:$op, repo:(if $repo == "" then null else $repo end), level:$level, event:$event}'
    local n=0 kind key value argname
    while [[ $# -gt 0 ]]; do
        kind="$1"; key="$2"; value="$3"
        shift 3
        n=$((n+1))
        argname="f${n}"
        if [[ "$kind" == "--num" ]]; then
            jq_args+=(--argjson "$argname" "$value")
        else
            jq_args+=(--arg "$argname" "$value")
        fi
        filter="${filter} + {\"${key}\": \$${argname}}"
    done
    local line
    line=$(jq "${jq_args[@]}" "$filter")
    echo "$line" >> "$LOG_JSONL"
    echo "$line" >> "$LOG_COMBINED_JSONL"
}

emit_summary() {
    local op="$1" repo="$2" raw_json="$3"
    local out
    out=$(jq -nc --arg ts "$(date '+%Y-%m-%dT%H:%M:%S%z')" --arg op "$op" --arg repo "$repo" \
        --argjson restic "$raw_json" \
        '{ts:$ts, op:$op, repo:$repo, level:"info", event:"summary"} + $restic')
    echo "$out" >> "$LOG_JSONL"
    echo "$out" >> "$LOG_COMBINED_JSONL"
}

process_restic_json_stream() {
    # Usage: restic ... --json --verbose=2 | process_restic_json_stream <op> <repo>
    local op="$1" repo="$2"
    local line msg_type
    while IFS= read -r line; do
        msg_type=$(jq -r '.message_type // empty' <<<"$line" 2>/dev/null) || continue
        case "$msg_type" in
            verbose_status)
                local action item size
                action=$(jq -r '.action // "unknown"' <<<"$line")
                [[ "$action" == "scan_finished" ]] && continue
                item=$(jq -r '.item // .path // ""' <<<"$line")
                size=$(jq -r '.data_size // .size // 0' <<<"$line")
                if [[ "${LOG_JSON_PER_FILE:-true}" == "true" ]]; then
                    emit_event "$op" "$repo" info file --str action "$action" --str path "$item" --num size "$size"
                fi
                log_human "[$op] $repo: $action $item"
                ;;
            summary)
                local raw
                raw=$(jq -c '.' <<<"$line")
                emit_summary "$op" "$repo" "$raw"
                log_human "[$op] $repo: summary $(jq -r 'to_entries | map("\(.key)=\(.value)") | join(" ")' <<<"$raw")"
                ;;
            error)
                local err_msg
                err_msg=$(jq -r '.message // (.error.message // "unknown error")' <<<"$line")
                emit_event "$op" "$repo" error error --str message "$err_msg"
                log_human "[$op] $repo: ERROR $err_msg"
                ;;
            *)
                :
                ;;
        esac
    done
}
```

- [ ] **Step 2: Verify against a real restic JSON stream**

Using the Task 1 harness:

```bash
export RESTIC_PASSWORD=testpass123
export TURIYA_CONFIG="/Users/amir/workspace/turiya/.test-harness/backup.conf"
bash -c '
  source lib/common.sh
  source lib/logging.sh
  load_config "/Users/amir/workspace/turiya"
  init_logging testop
  emit_event testop "" info run_start
  restic -r "/Users/amir/workspace/turiya/.test-harness/repo-a" backup \
    "/Users/amir/workspace/turiya/.test-harness/src/docs" \
    --json --verbose=2 | process_restic_json_stream testop "/Users/amir/workspace/turiya/.test-harness/repo-a"
  emit_event testop "" info run_end --str status success
  echo "--- ops.jsonl ---"
  cat "$LOG_DIR/ops.jsonl"
  echo "--- validate every line is valid JSON ---"
  jq -c . < "$LOG_DIR/ops.jsonl" | wc -l
'
```

Expected: prints one JSON object per line (run_start, file events for `report.txt` and the `docs` dir, a summary event, run_end) and the final `jq -c . | wc -l` count matches the number of lines with no parse errors. Also confirm the human log:

```bash
cat "/Users/amir/workspace/turiya/.test-harness/logs/testop.log"
```

Expected: readable timestamped lines, one per file plus a summary line, no raw JSON.

Clean up the test-only log files (not part of the harness's permanent fixtures, and not gitignored-relevant since `.test-harness/` is already ignored — just tidy):

```bash
rm -f "/Users/amir/workspace/turiya/.test-harness/logs/testop.log" \
      "/Users/amir/workspace/turiya/.test-harness/logs/testop.jsonl" \
      "/Users/amir/workspace/turiya/.test-harness/logs/ops.jsonl"
```

- [ ] **Step 3: Commit**

```bash
git add lib/logging.sh
git commit -m "feat: add lib/logging.sh for structured JSONL and human-readable logging"
```

---

### Task 4: `backup.conf` — new logging knob, derived log paths, doc comments

**Files:**
- Modify: `backup.conf`

**Interfaces:**
- Produces: `LOG_JSON_PER_FILE` config variable, consumed by `lib/logging.sh`'s `process_restic_json_stream` (Task 3).

- [ ] **Step 1: Update the header comment to mention testing env hooks**

Replace the file's opening comment block:
```bash
# =============================================================================
# turiya configuration
# =============================================================================
# All user-facing settings live here. backup.sh, restore.sh, status.sh,
# query.sh, and install.sh source this file — you should rarely need to
# edit anything else.
#
# Testing hooks (not used in normal operation):
#   TURIYA_CONFIG  — override which config file is sourced
#   RESTIC_PASSWORD       — if already set in the environment, skips the
#                           Keychain lookup entirely
# =============================================================================
```

- [ ] **Step 2: Replace the Logging section**

Replace:
```bash
# -----------------------------------------------------------------------------
# Logging
# -----------------------------------------------------------------------------
LOG_DIR="$HOME/.local/log/turiya"
LOG_FILE="$LOG_DIR/backup.log"

# Max log size in bytes before rotation (default: 5MB)
LOG_MAX_BYTES=5242880
```

With:
```bash
# -----------------------------------------------------------------------------
# Logging
# -----------------------------------------------------------------------------
# LOG_DIR holds both human-readable and structured JSON Lines (JSONL) logs.
# File names are derived automatically per operation — there is nothing
# else to configure here:
#   <op>.log     — human-readable (backup.log, restore.log, status.log, query.log)
#   <op>.jsonl   — structured JSONL for that operation only
#   ops.jsonl    — combined structured JSONL across all operations
LOG_DIR="$HOME/.local/log/turiya"

# Max size in bytes before a log file is rotated (default: 5MB). Applies to
# every .log and .jsonl file under LOG_DIR.
LOG_MAX_BYTES=5242880

# When true, every file restic touches during backup/restore gets its own
# JSONL "file" event (action, path, size). Large backups can produce large
# .jsonl files — set to false to keep only run_start/summary/error/run_end
# events.
LOG_JSON_PER_FILE=true
```

- [ ] **Step 3: Verify the config still parses**

```bash
bash -c 'source backup.conf; echo "LOG_JSON_PER_FILE=$LOG_JSON_PER_FILE"; echo "LOG_DIR=$LOG_DIR"'
```

Expected:
```
LOG_JSON_PER_FILE=true
LOG_DIR=/Users/amir/.local/log/turiya
```

- [ ] **Step 4: Commit**

```bash
git add backup.conf
git commit -m "feat: derive log file paths from LOG_DIR and add LOG_JSON_PER_FILE knob"
```

---

### Task 5: Rewrite `backup.sh`

**Files:**
- Modify: `backup.sh` (full rewrite)

**Interfaces:**
- Consumes: `lib/common.sh` (`load_config`, `check_dependencies`, `get_restic_password`), `lib/logging.sh` (`init_logging`, `log_human`, `emit_event`, `process_restic_json_stream`), `backup.conf` (`SOURCES`, `EXCLUDES`, `REPOS`, `RETENTION_KEEP_*`).
- Produces: `--dry-run`, `--include PATH` (repeatable), `--pattern PATTERN` (repeatable), `--glob GLOB` (repeatable), `--exclude PATTERN` (repeatable).

- [ ] **Step 1: Replace the full contents of `backup.sh`**

```bash
#!/bin/bash
# =============================================================================
# backup.sh — Restic backup runner
# =============================================================================
# Reads all config from backup.conf. Do not hardcode anything here.
#
# Usage:
#   bash backup.sh                                  — back up all configured SOURCES
#   bash backup.sh --dry-run                        — dry run, no changes
#   bash backup.sh --include ~/Documents/taxes      — back up only this path
#   bash backup.sh --pattern 'Documents/*/invoices' — back up paths matching this pattern
#   bash backup.sh --glob '*.pdf'                   — back up only files matching this filename glob
#   bash backup.sh --exclude '*.iso'                — add an extra exclude pattern for this run
#
# --include/--pattern/--glob are repeatable and may be combined; their
# resolved paths are unioned to REPLACE this run's source list (SOURCES from
# backup.conf is not used when any of these are given). --exclude is
# repeatable and adds to backup.conf's EXCLUDES for this run only.
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# shellcheck source=lib/common.sh
source "$SCRIPT_DIR/lib/common.sh"
# shellcheck source=lib/logging.sh
source "$SCRIPT_DIR/lib/logging.sh"

load_config "$SCRIPT_DIR"

# ── Parse arguments ───────────────────────────────────────────────────────────
DRY_RUN=false
INCLUDE_PATHS=()
PATTERN_ARGS=()
GLOB_ARGS=()
EXTRA_EXCLUDES=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        --dry-run) DRY_RUN=true; shift ;;
        --include) INCLUDE_PATHS+=("$2"); shift 2 ;;
        --pattern) PATTERN_ARGS+=("$2"); shift 2 ;;
        --glob)    GLOB_ARGS+=("$2"); shift 2 ;;
        --exclude) EXTRA_EXCLUDES+=("$2"); shift 2 ;;
        *) echo "Unknown argument: $1" >&2; exit 1 ;;
    esac
done

init_logging backup
emit_event backup "" info run_start

check_dependencies restic rclone security jq

get_restic_password

# ── Resolve target paths (--include/--pattern/--glob) ────────────────────────
TARGET_PATHS=()

if [[ ${#INCLUDE_PATHS[@]} -gt 0 ]]; then
    for path in "${INCLUDE_PATHS[@]}"; do
        if [[ ! -e "$path" ]]; then
            log_human "ERROR: --include path does not exist: $path"
            exit 1
        fi
        TARGET_PATHS+=("$path")
    done
fi

if [[ ${#PATTERN_ARGS[@]} -gt 0 ]]; then
    for pattern in "${PATTERN_ARGS[@]}"; do
        MATCHES=()
        for source in "${SOURCES[@]}"; do
            while IFS= read -r match; do
                MATCHES+=("$match")
            done < <(find "$source" -path "*${pattern}*" 2>/dev/null)
        done
        if [[ ${#MATCHES[@]} -eq 0 ]]; then
            log_human "ERROR: --pattern '$pattern' matched no files under configured SOURCES."
            exit 1
        fi
        TARGET_PATHS+=("${MATCHES[@]}")
    done
fi

if [[ ${#GLOB_ARGS[@]} -gt 0 ]]; then
    for glob in "${GLOB_ARGS[@]}"; do
        MATCHES=()
        for source in "${SOURCES[@]}"; do
            while IFS= read -r match; do
                MATCHES+=("$match")
            done < <(find "$source" -name "$glob" 2>/dev/null)
        done
        if [[ ${#MATCHES[@]} -eq 0 ]]; then
            log_human "ERROR: --glob '$glob' matched no files under configured SOURCES."
            exit 1
        fi
        TARGET_PATHS+=("${MATCHES[@]}")
    done
fi

if [[ ${#TARGET_PATHS[@]} -eq 0 ]]; then
    TARGET_PATHS=("${SOURCES[@]}")
fi

# ── Build exclude flags ───────────────────────────────────────────────────────
EXCLUDE_FLAGS=()
for pattern in "${EXCLUDES[@]}"; do
    EXCLUDE_FLAGS+=("--exclude=${pattern}")
done
if [[ ${#EXTRA_EXCLUDES[@]} -gt 0 ]]; then
    for pattern in "${EXTRA_EXCLUDES[@]}"; do
        EXCLUDE_FLAGS+=("--exclude=${pattern}")
    done
fi

# ── Build retention flags ─────────────────────────────────────────────────────
RETENTION_FLAGS=(
    --keep-daily   "$RETENTION_KEEP_DAILY"
    --keep-weekly  "$RETENTION_KEEP_WEEKLY"
    --keep-monthly "$RETENTION_KEEP_MONTHLY"
    --keep-yearly  "$RETENTION_KEEP_YEARLY"
)

if $DRY_RUN; then
    log_human "=== DRY RUN MODE — no changes will be made ==="
fi

log_human "=========================================="
log_human "Restic backup started"
log_human "Targets: ${TARGET_PATHS[*]}"
log_human "Repos:   ${REPOS[*]}"
log_human "=========================================="

OVERALL_SUCCESS=true

for REPO in "${REPOS[@]}"; do
    log_human ""
    log_human "--- Repository: $REPO ---"

    BACKUP_CMD=(
        restic -r "$REPO" backup
        "${TARGET_PATHS[@]}"
        "${EXCLUDE_FLAGS[@]}"
        --json --verbose=2
    )

    if $DRY_RUN; then
        BACKUP_CMD+=(--dry-run)
    fi

    if "${BACKUP_CMD[@]}" | process_restic_json_stream backup "$REPO"; then
        log_human "Backup to $REPO: SUCCESS"

        if ! $DRY_RUN; then
            log_human "Running forget/prune on $REPO..."
            FORGET_JSON=$(restic -r "$REPO" forget "${RETENTION_FLAGS[@]}" --prune --json 2>&1) && {
                REMOVED_COUNT=$(jq '[.[].remove // [] | length] | add // 0' <<<"$FORGET_JSON" 2>/dev/null || echo 0)
                emit_event backup "$REPO" info prune --num removed_count "$REMOVED_COUNT"
                log_human "Prune on $REPO: SUCCESS (removed $REMOVED_COUNT snapshot(s))"
            } || {
                emit_event backup "$REPO" warn prune --str message "prune failed"
                log_human "WARNING: Prune on $REPO failed. Backup data is safe; run manually to clean up."
            }
        fi
    else
        emit_event backup "$REPO" error error --str message "backup command failed"
        log_human "ERROR: Backup to $REPO FAILED."
        OVERALL_SUCCESS=false
    fi
done

log_human ""
log_human "=========================================="
if $OVERALL_SUCCESS; then
    log_human "All backups completed successfully."
else
    log_human "One or more backups FAILED. Check log above."
fi
log_human "Finished at $(date)"
log_human "=========================================="

if $OVERALL_SUCCESS; then
    emit_event backup "" info run_end --str status "success"
else
    emit_event backup "" error run_end --str status "failure"
fi

$OVERALL_SUCCESS  # exit 0 if all succeeded, 1 otherwise
```

- [ ] **Step 2: Run `bash -n` syntax check**

```bash
bash -n backup.sh
```

Expected: no output, exit 0.

- [ ] **Step 3: Verify against the test harness — plain run, --dry-run, and each targeting flag**

```bash
export RESTIC_PASSWORD=testpass123
export TURIYA_CONFIG="/Users/amir/workspace/turiya/.test-harness/backup.conf"

# Plain run: backs up both SOURCES to both repos
bash backup.sh
restic -r .test-harness/repo-a snapshots --json | jq 'length'
# Expected: 1 (one snapshot now exists)

# --include: restrict to one file
bash backup.sh --include /Users/amir/workspace/turiya/.test-harness/src/notes/todo.md
restic -r .test-harness/repo-a snapshots --json | jq -r '.[-1].paths'
# Expected: ["/Users/amir/workspace/turiya/.test-harness/src/notes/todo.md"]

# --glob: restrict to files matching *.md
bash backup.sh --glob '*.md'
restic -r .test-harness/repo-a snapshots --json | jq -r '.[-1].paths'
# Expected: contains todo.md's path, not report.txt

# --exclude: dry-run excluding todo.md, confirm it's not scanned
bash backup.sh --dry-run --exclude 'todo.md' 2>&1 | grep -c 'todo.md' || true
# Expected: 0 (todo.md never appears in the dry-run output)

# Unknown targeting flag with no matches errors out
bash backup.sh --glob '*.nonexistent-extension' ; echo "exit=$?"
# Expected: prints "ERROR: --glob '*.nonexistent-extension' matched no files..." and exit=1

# Verify JSONL logs are valid
jq -c . < .test-harness/logs/backup.jsonl > /dev/null && echo "backup.jsonl valid"
jq -c . < .test-harness/logs/ops.jsonl > /dev/null && echo "ops.jsonl valid"
```

Expected: each command's stated expectation holds; both `jq -c .` validation commands print their "valid" line with no errors.

- [ ] **Step 4: Commit**

```bash
git add backup.sh
git commit -m "feat(backup): add --include/--pattern/--glob/--exclude flags and JSONL logging"
```

---

### Task 6: Rewrite `restore.sh`

**Files:**
- Modify: `restore.sh` (full rewrite)

**Interfaces:**
- Consumes: `lib/common.sh` (`load_config`, `check_dependencies`, `get_restic_password`, `resolve_repo`), `lib/logging.sh` (`init_logging`, `log_human` implicitly via `emit_event`, `emit_event`, `process_restic_json_stream`).
- Produces: `--repo`, `--snapshot`, `--target` (unchanged), `--include`/`--pattern`/`--glob` (repeatable, all map to restic's native `--include`), `--exclude` (repeatable, maps to restic's native `--exclude`).

- [ ] **Step 1: Replace the full contents of `restore.sh`**

```bash
#!/bin/bash
# =============================================================================
# restore.sh — Restore files from a restic snapshot
# =============================================================================
# Usage:
#   bash restore.sh                                    — interactive guided restore
#   bash restore.sh --repo gdrive                      — use specific remote (gdrive/dropbox/pcloud)
#   bash restore.sh --snapshot abc123                  — restore a specific snapshot ID
#   bash restore.sh --include ~/Documents/invoice.pdf  — restore a specific path
#   bash restore.sh --pattern 'Documents/*/invoices'   — restore paths matching this pattern
#   bash restore.sh --glob '*.pdf'                     — restore files matching this filename glob
#   bash restore.sh --exclude '*.tmp'                  — skip files matching this pattern
#   bash restore.sh --target /tmp/restore              — restore to a custom location
#
# --include/--pattern/--glob are repeatable and all map directly to restic's
# native --include restore flag (restic patterns are already path-aware when
# they contain "/", and match any depth when they don't — --pattern and
# --glob are just clearer names for the same underlying matcher).
# --exclude is repeatable and maps to restic's native --exclude.
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# shellcheck source=lib/common.sh
source "$SCRIPT_DIR/lib/common.sh"
# shellcheck source=lib/logging.sh
source "$SCRIPT_DIR/lib/logging.sh"

load_config "$SCRIPT_DIR"

# ── Parse arguments ───────────────────────────────────────────────────────────
REPO_FILTER=""
SNAPSHOT="latest"
TARGET_DIR="$HOME/restic-restore"
INCLUDE_PATTERNS=()
EXCLUDE_PATTERNS=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        --repo)     REPO_FILTER="$2"; shift 2 ;;
        --snapshot) SNAPSHOT="$2"; shift 2 ;;
        --target)   TARGET_DIR="$2"; shift 2 ;;
        --include)  INCLUDE_PATTERNS+=("$2"); shift 2 ;;
        --pattern)  INCLUDE_PATTERNS+=("$2"); shift 2 ;;
        --glob)     INCLUDE_PATTERNS+=("$2"); shift 2 ;;
        --exclude)  EXCLUDE_PATTERNS+=("$2"); shift 2 ;;
        *) echo "Unknown argument: $1" >&2; exit 1 ;;
    esac
done

init_logging restore
emit_event restore "" info run_start

check_dependencies restic rclone security jq

get_restic_password

SELECTED_REPO=$(resolve_repo "$REPO_FILTER")

echo ""
echo "Restore settings:"
echo "  Repo:     $SELECTED_REPO"
echo "  Snapshot: $SNAPSHOT"
echo "  Target:   $TARGET_DIR"
if [[ ${#INCLUDE_PATTERNS[@]} -gt 0 ]]; then
    echo "  Include:  ${INCLUDE_PATTERNS[*]}"
fi
if [[ ${#EXCLUDE_PATTERNS[@]} -gt 0 ]]; then
    echo "  Exclude:  ${EXCLUDE_PATTERNS[*]}"
fi
echo ""

read -r -p "Proceed? [y/N] " CONFIRM
if [[ ! "$CONFIRM" =~ ^[Yy]$ ]]; then
    echo "Aborted."
    emit_event restore "$SELECTED_REPO" info run_end --str status "aborted"
    exit 0
fi

mkdir -p "$TARGET_DIR"

RESTORE_CMD=(
    restic -r "$SELECTED_REPO"
    restore "$SNAPSHOT"
    --target "$TARGET_DIR"
    --json --verbose=2
)

if [[ ${#INCLUDE_PATTERNS[@]} -gt 0 ]]; then
    for p in "${INCLUDE_PATTERNS[@]}"; do
        RESTORE_CMD+=(--include "$p")
    done
fi

if [[ ${#EXCLUDE_PATTERNS[@]} -gt 0 ]]; then
    for p in "${EXCLUDE_PATTERNS[@]}"; do
        RESTORE_CMD+=(--exclude "$p")
    done
fi

if "${RESTORE_CMD[@]}" | process_restic_json_stream restore "$SELECTED_REPO"; then
    echo ""
    echo "Restore complete → $TARGET_DIR"
    emit_event restore "$SELECTED_REPO" info run_end --str status "success"
else
    emit_event restore "$SELECTED_REPO" error run_end --str status "failure"
    echo "ERROR: Restore failed." >&2
    exit 1
fi
```

- [ ] **Step 2: Run `bash -n` syntax check**

```bash
bash -n restore.sh
```

Expected: no output, exit 0.

- [ ] **Step 3: Verify against the test harness**

```bash
export RESTIC_PASSWORD=testpass123
export TURIYA_CONFIG="/Users/amir/workspace/turiya/.test-harness/backup.conf"
rm -rf .test-harness/restore-out

# Full restore, non-interactive via piped "y"
echo y | bash restore.sh --target .test-harness/restore-out
find .test-harness/restore-out -type f
# Expected: both report.txt and todo.md present under the restored tree

rm -rf .test-harness/restore-out2

# --glob restricts to one file
echo y | bash restore.sh --target .test-harness/restore-out2 --glob 'todo.md'
find .test-harness/restore-out2 -type f
# Expected: only todo.md, not report.txt

# Abort path
echo n | bash restore.sh --target .test-harness/restore-out3
echo "exit=$?"
# Expected: prints "Aborted." and exit=0, no .test-harness/restore-out3 created (mkdir happens after confirm)

jq -c . < .test-harness/logs/restore.jsonl > /dev/null && echo "restore.jsonl valid"
```

Expected: each stated expectation holds; final validation line prints.

- [ ] **Step 4: Clean up restore scratch output (not needed for later tasks)**

```bash
rm -rf .test-harness/restore-out .test-harness/restore-out2 .test-harness/restore-out3
```

- [ ] **Step 5: Commit**

```bash
git add restore.sh
git commit -m "feat(restore): support repeatable --include/--pattern/--glob/--exclude and JSONL logging"
```

---

### Task 7: Rewrite `status.sh`

**Files:**
- Modify: `status.sh` (full rewrite)

**Interfaces:**
- Consumes: `lib/common.sh`, `lib/logging.sh`.
- Produces: `--latest` (default)/`--all`/`--check` (unchanged modes), `--include PATH` (repeatable, restic `--path` filter), `--pattern`/`--glob` (repeatable, client-side filter on snapshot `.paths[]`), `--exclude` (repeatable, inverse client-side filter). Targeting flags filter by which top-level configured source path a snapshot includes — not file-level search inside snapshots (that's `query.sh`'s job).

- [ ] **Step 1: Replace the full contents of `status.sh`**

```bash
#!/bin/bash
# =============================================================================
# status.sh — Check snapshot status across all configured repos
# =============================================================================
# Usage:
#   bash status.sh                       — show latest snapshot per repo
#   bash status.sh --all                 — show all snapshots per repo
#   bash status.sh --check               — run restic check (integrity verification)
#   bash status.sh --include ~/Documents — only snapshots that include this exact source path
#   bash status.sh --pattern 'Doc*'      — only snapshots with a source path matching this pattern
#   bash status.sh --glob 'Documents'    — only snapshots whose source path's basename matches
#   bash status.sh --exclude Music       — drop snapshots whose source path matches
#
# Targeting flags filter *which snapshots are shown*, by matching against a
# snapshot's top-level configured source paths — they do not search file
# contents inside a snapshot. For file-level search, use query.sh.
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# shellcheck source=lib/common.sh
source "$SCRIPT_DIR/lib/common.sh"
# shellcheck source=lib/logging.sh
source "$SCRIPT_DIR/lib/logging.sh"

load_config "$SCRIPT_DIR"

MODE="--latest"
INCLUDE_PATHS=()
PATTERN_ARGS=()
GLOB_ARGS=()
EXCLUDE_ARGS=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        --all)     MODE="--all"; shift ;;
        --check)   MODE="--check"; shift ;;
        --latest)  MODE="--latest"; shift ;;
        --include) INCLUDE_PATHS+=("$2"); shift 2 ;;
        --pattern) PATTERN_ARGS+=("$2"); shift 2 ;;
        --glob)    GLOB_ARGS+=("$2"); shift 2 ;;
        --exclude) EXCLUDE_ARGS+=("$2"); shift 2 ;;
        *) echo "Unknown argument: $1" >&2; exit 1 ;;
    esac
done

init_logging status
emit_event status "" info run_start

check_dependencies restic rclone security jq

get_restic_password

# Returns 0 (keep) or 1 (drop) for a snapshot given its paths array (JSON).
snapshot_matches_filters() {
    local paths_json="$1"
    local pattern p keep

    if [[ ${#PATTERN_ARGS[@]} -gt 0 || ${#GLOB_ARGS[@]} -gt 0 ]]; then
        keep=false
        if [[ ${#PATTERN_ARGS[@]} -gt 0 ]]; then
            for pattern in "${PATTERN_ARGS[@]}"; do
                while IFS= read -r p; do
                    [[ "$p" == *"$pattern"* ]] && keep=true
                done < <(jq -r '.[]' <<<"$paths_json")
            done
        fi
        if [[ ${#GLOB_ARGS[@]} -gt 0 ]]; then
            for pattern in "${GLOB_ARGS[@]}"; do
                while IFS= read -r p; do
                    [[ "$(basename "$p")" == $pattern ]] && keep=true
                done < <(jq -r '.[]' <<<"$paths_json")
            done
        fi
        $keep || return 1
    fi

    if [[ ${#EXCLUDE_ARGS[@]} -gt 0 ]]; then
        for pattern in "${EXCLUDE_ARGS[@]}"; do
            while IFS= read -r p; do
                if [[ "$p" == *"$pattern"* || "$(basename "$p")" == $pattern ]]; then
                    return 1
                fi
            done < <(jq -r '.[]' <<<"$paths_json")
        done
    fi

    return 0
}

for REPO in "${REPOS[@]}"; do
    echo ""
    echo "════════════════════════════════════════"
    echo "  Repo: $REPO"
    echo "════════════════════════════════════════"

    RESTIC_PATH_FLAGS=()
    if [[ ${#INCLUDE_PATHS[@]} -gt 0 ]]; then
        for p in "${INCLUDE_PATHS[@]}"; do
            RESTIC_PATH_FLAGS+=(--path "$p")
        done
    fi

    case "$MODE" in
        --check)
            log_human "Running integrity check on $REPO (this may take a while)..."
            if restic -r "$REPO" check --json 2>&1 | tee -a "$LOG_HUMAN"; then
                emit_event status "$REPO" info summary --str check "ok"
            else
                emit_event status "$REPO" error summary --str check "failed"
            fi
            ;;
        --all|--latest)
            SNAP_ARGS=(snapshots --json)
            if [[ ${#RESTIC_PATH_FLAGS[@]} -gt 0 ]]; then
                SNAP_ARGS+=("${RESTIC_PATH_FLAGS[@]}")
            fi
            [[ "$MODE" == "--latest" ]] && SNAP_ARGS+=(--latest 1)

            SNAPSHOTS_JSON=$(restic -r "$REPO" "${SNAP_ARGS[@]}")
            COUNT=$(jq 'length' <<<"$SNAPSHOTS_JSON")

            idx=0
            while [[ $idx -lt $COUNT ]]; do
                SNAP=$(jq -c ".[$idx]" <<<"$SNAPSHOTS_JSON")
                PATHS_JSON=$(jq -c '.paths' <<<"$SNAP")
                if snapshot_matches_filters "$PATHS_JSON"; then
                    SHORT_ID=$(jq -r '.short_id' <<<"$SNAP")
                    TIME=$(jq -r '.time' <<<"$SNAP")
                    PATHS=$(jq -r '.paths | join(", ")' <<<"$SNAP")
                    echo "  $SHORT_ID  $TIME  $PATHS"
                    emit_event status "$REPO" info summary --str snapshot_id "$SHORT_ID" --str time "$TIME"
                fi
                idx=$((idx+1))
            done
            ;;
    esac
done

emit_event status "" info run_end --str status "success"
```

- [ ] **Step 2: Run `bash -n` syntax check**

```bash
bash -n status.sh
```

Expected: no output, exit 0.

- [ ] **Step 3: Verify against the test harness**

```bash
export RESTIC_PASSWORD=testpass123
export TURIYA_CONFIG="/Users/amir/workspace/turiya/.test-harness/backup.conf"

bash status.sh --all
# Expected: lists every snapshot in both repo-a and repo-b, from Tasks 5/6's test runs

bash status.sh --pattern 'notes'
# Expected: only snapshots whose paths include the "notes" source directory

bash status.sh --exclude 'notes'
# Expected: only snapshots whose paths do NOT include "notes"

bash status.sh --include /Users/amir/workspace/turiya/.test-harness/src/docs
# Expected: only snapshots whose paths exactly include the docs source path

jq -c . < .test-harness/logs/status.jsonl > /dev/null && echo "status.jsonl valid"
```

Expected: each stated expectation holds.

- [ ] **Step 4: Commit**

```bash
git add status.sh
git commit -m "feat(status): add --include/--pattern/--glob/--exclude snapshot filters and JSONL logging"
```

---

### Task 8: `query.sh` (new)

**Files:**
- Create: `query.sh`

**Interfaces:**
- Consumes: `lib/common.sh`, `lib/logging.sh`.
- Produces: `--repo`, `--since`/`--until`, `--find`, `--versions`, `--json`. Exactly one of `--since`/`--until`, `--find`, `--versions` per invocation.

- [ ] **Step 1: Create `query.sh`**

```bash
#!/bin/bash
# =============================================================================
# query.sh — Search restic snapshots by date, file path, or file history
# =============================================================================
# Usage:
#   bash query.sh --since 2026-01-01 --until 2026-06-01     — snapshots in a date range
#   bash query.sh --find ~/Documents/taxes/2025.pdf         — which snapshot(s) contain this file
#   bash query.sh --find '*.pdf'                            — which snapshot(s) contain files matching this glob
#   bash query.sh --versions ~/Documents/notes.md           — every version of this file across snapshots
#   bash query.sh --repo dropbox --versions '*.pdf'         — restrict to one repo
#   bash query.sh --find notes.md --json                    — raw JSON output
#
# Exactly one of --since/--until, --find, or --versions must be given.
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# shellcheck source=lib/common.sh
source "$SCRIPT_DIR/lib/common.sh"
# shellcheck source=lib/logging.sh
source "$SCRIPT_DIR/lib/logging.sh"

load_config "$SCRIPT_DIR"

REPO_FILTER=""
SINCE=""
UNTIL=""
FIND_TARGET=""
VERSIONS_TARGET=""
JSON_OUTPUT=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --repo)     REPO_FILTER="$2"; shift 2 ;;
        --since)    SINCE="$2"; shift 2 ;;
        --until)    UNTIL="$2"; shift 2 ;;
        --find)     FIND_TARGET="$2"; shift 2 ;;
        --versions) VERSIONS_TARGET="$2"; shift 2 ;;
        --json)     JSON_OUTPUT=true; shift ;;
        *) echo "Unknown argument: $1" >&2; exit 1 ;;
    esac
done

MODE_COUNT=0
[[ -n "$SINCE$UNTIL" ]] && MODE_COUNT=$((MODE_COUNT+1))
[[ -n "$FIND_TARGET" ]] && MODE_COUNT=$((MODE_COUNT+1))
[[ -n "$VERSIONS_TARGET" ]] && MODE_COUNT=$((MODE_COUNT+1))

if [[ "$MODE_COUNT" -ne 1 ]]; then
    echo "ERROR: specify exactly one of --since/--until, --find, or --versions." >&2
    exit 1
fi

init_logging query
emit_event query "" info run_start

check_dependencies restic rclone security jq

get_restic_password

REPOS_TO_QUERY=()
if [[ -n "$REPO_FILTER" ]]; then
    REPOS_TO_QUERY+=("$(resolve_repo "$REPO_FILTER")")
else
    REPOS_TO_QUERY=("${REPOS[@]}")
fi

for REPO in "${REPOS_TO_QUERY[@]}"; do
    if [[ -n "$SINCE$UNTIL" ]]; then
        SNAPSHOTS_JSON=$(restic -r "$REPO" snapshots --json)
        FILTER='.[]'
        [[ -n "$SINCE" ]] && FILTER="$FILTER | select(.time >= \"$SINCE\")"
        [[ -n "$UNTIL" ]] && FILTER="$FILTER | select(.time <= \"$UNTIL\")"
        RESULT=$(jq -c "[$FILTER]" <<<"$SNAPSHOTS_JSON")

        emit_event query "$REPO" info summary --str mode "date_range" --num match_count "$(jq 'length' <<<"$RESULT")"

        if $JSON_OUTPUT; then
            echo "$RESULT"
        else
            echo ""
            echo "--- $REPO ---"
            jq -r '.[] | "\(.short_id)  \(.time)  \(.paths | join(", "))"' <<<"$RESULT"
        fi

    elif [[ -n "$FIND_TARGET" ]]; then
        RESULT=$(restic -r "$REPO" find --json "$FIND_TARGET" 2>/dev/null || echo "[]")
        MATCH_COUNT=$(jq '[.[].matches[]] | length' <<<"$RESULT")

        emit_event query "$REPO" info summary --str mode "find" --str target "$FIND_TARGET" --num match_count "$MATCH_COUNT"

        if $JSON_OUTPUT; then
            echo "$RESULT"
        elif [[ "$MATCH_COUNT" -gt 0 ]]; then
            echo ""
            echo "--- $REPO ---"
            jq -r '.[] | .snapshot as $s | .matches[] | "\($s)  \(.path)  \(.size) bytes  \(.mtime)"' <<<"$RESULT"
        fi

    elif [[ -n "$VERSIONS_TARGET" ]]; then
        RESULT=$(restic -r "$REPO" find --json "$VERSIONS_TARGET" --reverse 2>/dev/null || echo "[]")
        MATCH_COUNT=$(jq '[.[].matches[]] | length' <<<"$RESULT")

        emit_event query "$REPO" info summary --str mode "versions" --str target "$VERSIONS_TARGET" --num version_count "$MATCH_COUNT"

        if $JSON_OUTPUT; then
            echo "$RESULT"
        elif [[ "$MATCH_COUNT" -gt 0 ]]; then
            echo ""
            echo "--- $REPO: versions of $VERSIONS_TARGET (oldest first) ---"
            jq -r '.[] | .snapshot as $s | .matches[] | "\($s)  \(.mtime)  \(.size) bytes  \(.path)"' <<<"$RESULT"
        fi
    fi
done

emit_event query "" info run_end --str status "success"
```

- [ ] **Step 2: Make it executable and run `bash -n`**

```bash
chmod +x query.sh
bash -n query.sh
```

Expected: no output, exit 0.

- [ ] **Step 3: Verify against the test harness**

```bash
export RESTIC_PASSWORD=testpass123
export TURIYA_CONFIG="/Users/amir/workspace/turiya/.test-harness/backup.conf"

bash query.sh --find 'todo.md'
# Expected: prints snapshot(s) containing todo.md, with size/mtime

bash query.sh --versions 'todo.md' --repo repo-a
# Expected: same file's history within repo-a, oldest first

bash query.sh --since 2020-01-01
# Expected: lists all snapshots in both repos (everything is after 2020)

bash query.sh --since 2099-01-01
# Expected: no output rows (nothing matches a future date)

bash query.sh --find 'todo.md' --json | jq -c . > /dev/null && echo "json output valid"

bash query.sh --find x --since 2020-01-01 ; echo "exit=$?"
# Expected: "ERROR: specify exactly one of..." and exit=1

jq -c . < .test-harness/logs/query.jsonl > /dev/null && echo "query.jsonl valid"
```

Expected: each stated expectation holds.

- [ ] **Step 4: Commit**

```bash
git add query.sh
git commit -m "feat: add query.sh for snapshot search by date, path, and file version history"
```

---

### Task 9: `install.sh` — add `jq` to dependency check

**Files:**
- Modify: `install.sh:26-32`

**Interfaces:** none (self-contained change).

- [ ] **Step 1: Update the dependency check loop**

Change:
```bash
info "Checking dependencies..."
for cmd in restic rclone; do
    if ! command -v "$cmd" &>/dev/null; then
        error "'$cmd' not found. Run: brew install restic rclone"
    fi
done
success "restic and rclone found."
```

To:
```bash
info "Checking dependencies..."
for cmd in restic rclone jq; do
    if ! command -v "$cmd" &>/dev/null; then
        error "'$cmd' not found. Run: brew install restic rclone jq"
    fi
done
success "restic, rclone, and jq found."
```

- [ ] **Step 2: Run `bash -n` syntax check**

```bash
bash -n install.sh
```

Expected: no output, exit 0.

- [ ] **Step 3: Commit**

```bash
git add install.sh
git commit -m "chore(install): check for jq alongside restic and rclone"
```

---

### Task 10: `CLAUDE.md`

**Files:**
- Create: `CLAUDE.md`

- [ ] **Step 1: Create `CLAUDE.md`**

```markdown
# CLAUDE.md

## Project purpose

turiya automates encrypted, versioned backups of this Mac's important
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
| `com.amir.turiya.plist.template` | launchd plist template, rendered by `install.sh`. Don't edit the generated `.plist` directly — it's gitignored and regenerated on every `install.sh` run. |
| `README.md` | User-facing usage docs. |
| `.copilot-instructions.md` | Copilot-facing project instructions — this file's counterpart. |

## Conventions

- Every script: `set -euo pipefail`; resolves its own `SCRIPT_DIR` from `BASH_SOURCE[0]`; sources `lib/common.sh` then `lib/logging.sh`; calls `load_config "$SCRIPT_DIR"` before touching any config variable.
- **macOS ships bash 3.2.57 at `/bin/bash`** — confirmed on this machine via `/bin/bash --version`. Homebrew's newer bash on `PATH` is irrelevant: the `#!/bin/bash` shebang always resolves to the system one. Bash 3.2 throws "unbound variable" when expanding `"${ARR[@]}"` on a *declared-but-empty* array under `set -u` (bash 4.4+ doesn't have this bug). **Never expand a possibly-empty array directly** — guard first: `if [[ ${#ARR[@]} -gt 0 ]]; then ... fi`. This won't reproduce if you test under an interactively-launched Homebrew bash 5 — only under the real `/bin/bash` the scripts run with.
- No associative arrays, `mapfile`/`readarray`, `${var,,}`/`${var^^}`, `local -n` namerefs, or other bash-4+-only features.
- All JSON construction goes through `jq` (`jq -c`, `jq -nc`) — never hand-built JSON strings.
- restic pattern semantics (used by `--pattern`/`--glob`/`--include`/`--exclude` on `restore.sh`): a pattern containing `/` is path-anchored; a bare pattern (no `/`) matches the filename at any depth. This is restic's own behavior, not something these scripts implement — see `restic backup --help` / `restic restore --help`.
- Config lives only in `backup.conf`. Two env var overrides exist for testing, not normal use: `TURIYA_CONFIG` (override which file `load_config` reads) and `RESTIC_PASSWORD` (if already set, `get_restic_password` skips the Keychain lookup).
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
- `com.amir.turiya.plist.template`'s placeholder tokens (`{{HOME}}`, `{{SCRIPT_DIR}}`, `{{BACKUP_WEEKDAY}}`, `{{BACKUP_HOUR}}`, `{{BACKUP_MINUTE}}`) — `install.sh`'s `sed` render step depends on these exact strings.
- The retention/forget logic in `backup.sh` — it's intentionally simple and matches the documented retention policy; don't add extra forget flags without updating `backup.conf` and `README.md` together.
- `set -euo pipefail` at the top of every script — don't remove it to silence an error; fix the underlying issue (usually the bash 3.2 empty-array gotcha above).
- Don't hardcode a path, repo name, or credential anywhere — it belongs in `backup.conf`.
```

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: add CLAUDE.md covering file map, conventions, and logging schema"
```

---

### Task 11: `.copilot-instructions.md`

**Files:**
- Create: `.copilot-instructions.md`

- [ ] **Step 1: Create `.copilot-instructions.md`**

```markdown
# GitHub Copilot Instructions — turiya

## What this project is

turiya automates encrypted, versioned backups of this Mac's important
directories to three cloud remotes (Google Drive, Dropbox, pCloud) via
restic + rclone, on a weekly `launchd` schedule with `pmset` wake support.
All configuration lives in `backup.conf`.

## File map

| File | Responsibility |
|---|---|
| `backup.conf` | All configuration. Never hardcode a value that belongs here instead. |
| `lib/common.sh` | Shared: `load_config`, `check_dependencies`, `get_restic_password`, `resolve_repo`. |
| `lib/logging.sh` | Shared: `init_logging`, `log_human`, `emit_event`, `emit_summary`, `process_restic_json_stream`. |
| `backup.sh` | Weekly backup runner. `--dry-run`, `--include`/`--pattern`/`--glob`/`--exclude`. |
| `restore.sh` | Guided restore. `--repo`/`--snapshot`/`--target`/`--include`/`--pattern`/`--glob`/`--exclude`. |
| `status.sh` | Snapshot listing/check. `--latest`/`--all`/`--check`/`--include`/`--pattern`/`--glob`/`--exclude`. |
| `query.sh` | Snapshot search by date/path/version history. `--since`/`--until`/`--find`/`--versions`/`--repo`/`--json`. |
| `install.sh` / `uninstall.sh` | Setup/teardown for launchd, pmset, Keychain, restic repos. |

## Rules for generating or editing code in this repo

- **Target bash 3.2 syntax** — macOS's system `/bin/bash` is 3.2.57, and shebangs always resolve there regardless of Homebrew bash on `PATH`. No associative arrays, no `mapfile`/`readarray`, no `${var,,}`/`${var^^}`, no `local -n` namerefs.
- **Guard every possibly-empty array** before expanding it: `if [[ ${#ARR[@]} -gt 0 ]]; then for x in "${ARR[@]}"; do ...; done; fi`. Expanding `"${ARR[@]}"` directly on a declared-but-empty array throws "unbound variable" under `set -u` in bash 3.2 — this is the most common source of runtime crashes in this repo.
- Start every script with `set -euo pipefail`, resolve `SCRIPT_DIR` from `BASH_SOURCE[0]`, source `lib/common.sh` then `lib/logging.sh`, and call `load_config "$SCRIPT_DIR"` before touching any config variable.
- Never hardcode a path, repo name, retention value, or credential — add it to `backup.conf` instead.
- Build JSON only with `jq -c`/`jq -nc` — never string-concatenated JSON.
- Log via `log_human` / `emit_event` / `process_restic_json_stream` from `lib/logging.sh` — don't `echo >>` a log file directly, and don't invent a parallel logging mechanism.
- New scripts follow the skeleton documented in `CLAUDE.md`'s "How to add a new script" section.
- Run `shellcheck -x` on any `.sh` file you generate or modify; it must be warning-free before you consider the change done.
- restic pattern semantics: a pattern containing `/` is path-anchored, a bare pattern matches the filename at any depth — this is restic's own behavior (`restic restore --help`), not something to reimplement.

## Logging schema

One JSON object per line (JSONL), written only via `jq`:
```json
{"ts":"...","op":"backup|restore|status|query","repo":"<repo-string>|null","level":"info|warn|error","event":"run_start|file|summary|error|run_end|prune", ...}
```
Files under `LOG_DIR`: `ops.jsonl` (combined), `<op>.jsonl` (per-op), `<op>.log` (human-readable). `LOG_JSON_PER_FILE=false` in `backup.conf` suppresses only `file` events.

## Do not

- Change `KEYCHAIN_ACCOUNT`/`KEYCHAIN_SERVICE` without also updating what's stored in Keychain (via `install.sh`).
- Edit the generated `.plist` directly (gitignored, regenerated from `com.amir.turiya.plist.template`).
- Remove `set -euo pipefail` to work around an error.
- Add a new logging mechanism instead of using `lib/logging.sh`.
```

- [ ] **Step 2: Commit**

```bash
git add .copilot-instructions.md
git commit -m "docs: add .copilot-instructions.md"
```

---

### Task 12: `README.md` overhaul

**Files:**
- Modify: `README.md` (full rewrite)

- [ ] **Step 1: Replace the full contents of `README.md`**

```markdown
# turiya

Automated weekly cloud backups using [Restic](https://restic.net/) and [rclone](https://rclone.org/), managed via macOS `launchd` and `pmset`.

Targets: **Google Drive**, **Dropbox**, **pCloud** (and optionally Mega).

---

## Quick Start

```bash
brew install restic rclone jq
rclone config                    # create remotes matching backup.conf's REPOS
$EDITOR backup.conf              # adjust sources, excludes, retention, schedule
bash install.sh                  # Keychain password, repo init, launchd, pmset
bash backup.sh --dry-run         # sanity check
bash backup.sh                   # first real backup
```

---

## How it works

- `backup.conf` is the single source of truth for all configuration
- `lib/common.sh` / `lib/logging.sh` are shared helpers sourced by every script (config loading, Keychain access, dependency checks, structured logging)
- `install.sh` reads `backup.conf` and wires everything up (Keychain, rclone check, repo init, launchd, pmset)
- `backup.sh` is what launchd runs — it reads `backup.conf` at runtime, pulls the password from Keychain, and backs up to all configured repos
- The generated `.plist` (gitignored) is rendered from `com.amir.turiya.plist.template` by `install.sh`

---

## Prerequisites

```bash
brew install restic rclone jq
```

---

## First-run sequence

1. **Configure rclone remotes** — run `rclone config` and create remotes matching the names in `backup.conf`:

   | Remote name | Provider     |
   |-------------|--------------|
   | `gdrive`    | Google Drive |
   | `dropbox`   | Dropbox      |
   | `pcloud`    | pCloud       |
   | `mega`      | Mega (optional) |

   Google Drive, Dropbox, and pCloud use OAuth (browser popup). Mega uses email/password.

   > **Do not commit `~/.config/rclone/rclone.conf`** — it contains OAuth tokens.

2. **Edit `backup.conf`** — adjust source directories, exclusions, retention policy, and schedule to taste. Everything is documented inline.

3. **Run the installer**:
   ```bash
   bash install.sh
   ```
   It checks that `restic`, `rclone`, and `jq` are installed; prompts for your restic password and stores it in macOS Keychain; verifies all rclone remotes exist; initializes any uninitialized restic repos; renders and installs the launchd plist; loads the launchd job; and sets a `pmset` wake schedule so the machine wakes before the backup runs.

4. **Verify with a dry run, then a real backup**:
   ```bash
   bash backup.sh --dry-run
   bash backup.sh
   ```

---

## Daily usage

### backup.sh

```bash
bash backup.sh                                  # back up all configured SOURCES
bash backup.sh --dry-run                        # dry run, no changes
bash backup.sh --include ~/Documents/taxes      # back up only this path, this run
bash backup.sh --pattern 'Documents/*/invoices' # back up paths matching this restic-style pattern
bash backup.sh --glob '*.pdf'                   # back up only files matching this filename glob
bash backup.sh --exclude '*.iso'                # add an extra exclude pattern, this run only
```

`--include`/`--pattern`/`--glob` are repeatable and combinable; when any are given, they **replace** the configured `SOURCES` for that run (the scheduled weekly backup, run with no flags, always uses the full `SOURCES` list). `--exclude` is repeatable and adds to `backup.conf`'s `EXCLUDES` for that run only.

### restore.sh

```bash
bash restore.sh                                     # interactive guided restore (latest snapshot, primary repo)
bash restore.sh --repo dropbox                       # use a specific remote
bash restore.sh --snapshot abc12345                  # restore a specific snapshot ID
bash restore.sh --include ~/Documents/invoice.pdf    # restore a specific path
bash restore.sh --pattern 'Documents/*/invoices'     # restore paths matching this pattern
bash restore.sh --glob '*.pdf'                       # restore files matching this filename glob
bash restore.sh --exclude '*.tmp'                    # skip files matching this pattern
bash restore.sh --target /tmp/restore                # restore to a custom location
```

`--include`/`--pattern`/`--glob` are repeatable and all map to restic's native include matcher (a pattern containing `/` is path-anchored, a bare pattern matches the filename at any depth). `--exclude` is repeatable.

### status.sh

```bash
bash status.sh                        # latest snapshot per repo
bash status.sh --all                  # all snapshots
bash status.sh --check                # integrity check (slow)
bash status.sh --include ~/Documents  # only snapshots whose source paths include this exact path
bash status.sh --pattern 'Doc*'       # only snapshots with a source path matching this pattern
bash status.sh --glob 'Documents'     # only snapshots whose source path's basename matches
bash status.sh --exclude Music        # drop snapshots matching this pattern
```

Targeting flags filter *which snapshots are listed*, by the top-level source paths recorded on each snapshot — they don't search file contents inside a snapshot. For that, use `query.sh`.

### query.sh

```bash
bash query.sh --since 2026-01-01 --until 2026-06-01   # snapshots in a date range
bash query.sh --find ~/Documents/taxes/2025.pdf       # which snapshot(s) contain this file
bash query.sh --find '*.pdf'                          # which snapshot(s) contain files matching this glob
bash query.sh --versions ~/Documents/notes.md         # every version of this file across snapshots, oldest first
bash query.sh --repo dropbox --versions '*.pdf'       # restrict the search to one repo
bash query.sh --find notes.md --json                  # raw JSON output instead of a formatted table
```

Exactly one of `--since`/`--until`, `--find`, or `--versions` is required per invocation. `--repo` defaults to searching all configured repos.

---

## Changing the schedule

Edit `backup.conf`:

```bash
BACKUP_WEEKDAY=0      # 0=Sunday
BACKUP_HOUR=10
BACKUP_MINUTE=0
PMSET_WAKE_OFFSET_MINUTES=5
```

Then re-run `install.sh` to apply. It's idempotent — safe to re-run at any time.

---

## Logs

All logs live under `LOG_DIR` (default `~/.local/log/turiya`), one pair of files per operation plus a combined structured log:

```
backup.log      restore.log      status.log      query.log        # human-readable, one per operation
backup.jsonl    restore.jsonl    status.jsonl    query.jsonl       # structured JSON Lines, one per operation
ops.jsonl                                                          # combined structured JSON Lines, every operation interleaved
launchd.log                                                        # stdout from launchd
launchd-err.log                                                    # stderr from launchd
```

Each line of a `.jsonl` file is a standalone JSON object — e.g. `jq -c 'select(.event == "file")' backup.jsonl` shows every file restic touched on the last few runs, or `jq -c 'select(.level == "error")' ops.jsonl` surfaces every error across every operation. Set `LOG_JSON_PER_FILE=false` in `backup.conf` if per-file entries make the `.jsonl` files too large for your taste — you'll still get run/summary/error events. All log files (`.log` and `.jsonl`) rotate automatically at `LOG_MAX_BYTES`.

---

## Uninstall

```bash
bash uninstall.sh
```

Removes the launchd job and pmset schedule. Optionally removes the Keychain entry and logs. **Does not touch your restic repos on the cloud providers.**

---

## Repository structure

```
turiya/
├── backup.conf                              # ← all config lives here
├── lib/
│   ├── common.sh                            # config loading, Keychain, dependency checks
│   └── logging.sh                           # structured JSONL + human-readable logging
├── backup.sh                                # backup runner (called by launchd)
├── install.sh                               # one-time setup
├── uninstall.sh                             # teardown
├── status.sh                                # snapshot inspection
├── restore.sh                               # guided restore helper
├── query.sh                                 # snapshot search (date range, file, version history)
├── com.amir.turiya.plist.template    # launchd plist template
├── CLAUDE.md                                # project conventions for AI-assisted development
├── .copilot-instructions.md                 # same, for GitHub Copilot
├── .gitignore
└── README.md
```

---

## Security notes

- The restic password is stored in **macOS Keychain** — never in any file tracked by git
- All backups are **AES-256 encrypted by restic** before leaving your machine
- rclone OAuth tokens live in `~/.config/rclone/rclone.conf` — keep this out of version control
- The generated `.plist` is gitignored since it contains your absolute home path

---

## Retention policy (default)

| Interval | Snapshots kept |
|----------|---------------|
| Daily    | 7             |
| Weekly   | 4             |
| Monthly  | 6             |
| Yearly   | 1             |

Configurable in `backup.conf`.

---

## Troubleshooting

**`rclone`, `restic`, or `jq` not found when launchd runs**
The `PATH` in the plist template includes `/usr/local/bin` (Homebrew Intel default). If you installed via a non-standard path, update `EnvironmentVariables > PATH` in the template and re-run `install.sh`.

**Backup didn't run at the scheduled time**
Check that the machine was awake — `pmset` should handle this, but verify with:
```bash
pmset -g sched
```

**Keychain password prompt appears during backup**
macOS may prompt to allow `security` to access the keychain on first run. Click **Always Allow** to prevent future prompts.

**Repo initialisation fails**
Usually a rclone auth issue. Re-run `rclone config reconnect <remote>:` for the affected provider.

**A `--pattern` or `--glob` flag on `backup.sh` errors with "matched no files"**
The pattern didn't match anything under the configured `SOURCES`. Check the pattern against `find <source> -path "*<pattern>*"` (for `--pattern`) or `find <source> -name "<glob>"` (for `--glob`) directly to debug.
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: overhaul README with Quick Start, first-run sequence, and full flag reference"
```

---

### Task 13: shellcheck pass

**Files:**
- Modify: any of `backup.sh`, `restore.sh`, `status.sh`, `query.sh`, `install.sh`, `uninstall.sh`, `lib/common.sh`, `lib/logging.sh` as needed to clear warnings.

- [ ] **Step 1: Install shellcheck**

```bash
brew install shellcheck
shellcheck --version
```

Expected: version output, no errors.

- [ ] **Step 2: Run shellcheck against every script**

```bash
shellcheck -x backup.sh restore.sh status.sh query.sh install.sh uninstall.sh lib/common.sh lib/logging.sh
```

- [ ] **Step 3: Fix every reported warning**

Common fixes to expect and apply, based on this codebase's patterns:
- Quote all variable expansions that aren't already quoted (`SC2086`).
- Any `local var=$(cmd)` that masks a non-zero exit code (`SC2155`) — split into `local var; var=$(cmd)`.
- Unused variables (`SC2034`) — remove them, or add a targeted `# shellcheck disable=SC2034` with a one-line reason only if the variable is intentionally unused (e.g. a documented interface field).
- Sourcing a file shellcheck can't statically resolve (`SC1091`) — confirm the `# shellcheck source=...` directive immediately precedes each `source` line in every file (already present per this plan's code); add any that are missing.
- Re-run the exact command from Step 2 after each fix.

- [ ] **Step 4: Confirm a clean run**

```bash
shellcheck -x backup.sh restore.sh status.sh query.sh install.sh uninstall.sh lib/common.sh lib/logging.sh
echo "shellcheck exit=$?"
```

Expected: no output from `shellcheck`, `shellcheck exit=0`.

- [ ] **Step 5: Full regression pass against the test harness**

Re-run every verification command from Tasks 5–8 (backup.sh, restore.sh, status.sh, query.sh) end to end, since Step 3's fixes may have touched any of them:

```bash
export RESTIC_PASSWORD=testpass123
export TURIYA_CONFIG="/Users/amir/workspace/turiya/.test-harness/backup.conf"

bash -n backup.sh && bash -n restore.sh && bash -n status.sh && bash -n query.sh && bash -n install.sh && bash -n uninstall.sh
echo "syntax ok"

bash backup.sh --dry-run
bash status.sh --all
bash query.sh --find 'todo.md'
echo y | bash restore.sh --target .test-harness/restore-final --glob 'todo.md'
find .test-harness/restore-final -type f
rm -rf .test-harness/restore-final

for f in .test-harness/logs/*.jsonl; do
  jq -c . < "$f" > /dev/null && echo "$f valid"
done
```

Expected: all syntax checks pass, all commands run without error, restored file is `todo.md`, every `.jsonl` file validates.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "chore: fix shellcheck warnings across all scripts"
```

---

## Self-Review Notes

- **Spec coverage:** Task 5 covers backup.sh flags; Task 6 covers restore.sh flags; Task 7 covers status.sh flags; Task 8 covers query.sh's three search modes; Tasks 2–3 cover the JSONL logging library and schema; Task 4 covers the `LOG_JSON_PER_FILE` config knob and derived log paths; Task 9 covers install.sh's jq check; Tasks 10–12 cover CLAUDE.md, .copilot-instructions.md, and README.md; Task 13 covers the shellcheck requirement. All spec sections have a corresponding task.
- **Placeholder scan:** no TBD/TODO markers; every code step has complete, runnable content; every test step has a concrete expected outcome.
- **Type/interface consistency:** `emit_event`'s `--str`/`--num` calling convention is identical across `lib/logging.sh` (Task 3) and every call site in `backup.sh`/`restore.sh`/`status.sh`/`query.sh` (Tasks 5–8). `resolve_repo` (Task 2) is used identically by `restore.sh` and `query.sh` (Tasks 6, 8). `process_restic_json_stream <op> <repo>` signature (Task 3) matches its invocation in `backup.sh` and `restore.sh` (Tasks 5, 6).
